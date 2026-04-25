import base64
import contextlib
import gc
import json
import math
import os
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path
from typing import Any

import structlog
import yaml
from build123d import Compound

from shared.agents.config import load_agents_config
from shared.current_role import current_role_agent_name
from shared.enums import (
    BenchmarkRefusalReason,
    FailureReason,
    SimulationConfidence,
)
from shared.git_utils import repo_revision
from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    PayloadTrajectoryDefinition,
)
from shared.models.simulation import (
    SimulationFailure,
    SimulationMetrics,
    SimulationResult,
)
from shared.observability.storage import S3Client, S3Config
from shared.rendering import (
    append_render_bundle_index,
    build_render_bundle_index_entry,
    normalize_render_manifest,
    select_scratch_preview_render_subdir,
)
from shared.script_contracts import (
    role_family_for_agent,
)
from shared.simulation.scene_builder import (
    PAYLOAD_SCENE_PREFIX,
    build_payload_start_geometry,
)
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.workers.schema import RenderManifest
from shared.workers.workbench_models import ManufacturingConfig
from worker_heavy.simulation.factory import (
    close_all_session_backends,
    get_simulation_builder,
)
from worker_heavy.simulation.object_pose import (
    summarize_payload_position_history,
)
from worker_heavy.simulation.payload_trajectory_monitor import (
    load_payload_trajectory_definition,
)
from worker_heavy.utils.rendering import prerender_24_views
from worker_heavy.workbenches.config import load_config, load_merged_config

from .dfm import (
    MIN_OBJECTIVE_ZONE_SPAN_MM,
    _objective_zone_bounds_mm_for_compare,
    resolve_requested_quantity,
    validate_and_price,
)

logger = structlog.get_logger(__name__)


def _stack_profile_s3_endpoint() -> str | None:
    profile = os.getenv("PROBLEMOLOGIST_STACK_PROFILE", "").strip().lower()
    if profile == "integration":
        return "http://127.0.0.1:19000"
    if profile == "eval":
        return "http://127.0.0.1:29000"
    return None


def _find_workspace_assembly_definition(
    root: Path, *, prefer_benchmark: bool = False
) -> Path | None:
    """Resolve the assembly-definition artifact for the active workflow."""
    benchmark_path = root / "benchmark_assembly_definition.yaml"
    engineer_path = root / "assembly_definition.yaml"
    candidates = (
        (benchmark_path, engineer_path) if prefer_benchmark else (engineer_path,)
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def _load_valid_benchmark_definition(
    content: str, *, session_id: str | None = None
) -> BenchmarkDefinition:
    from .file_validation import validate_benchmark_definition_yaml

    is_valid, result = validate_benchmark_definition_yaml(
        content, session_id=session_id
    )
    if not is_valid:
        raise ValueError("; ".join(result))
    return result


def _benchmark_requires_genesis(objectives: BenchmarkDefinition | None) -> bool:
    """Return whether the benchmark requires the Genesis backend."""
    return False


def _finite_float(value: float, default: float = 0.0) -> float:
    """Coerce NaN/Inf to a finite fallback for JSON-safe API responses."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _shape_volume(shape: Any) -> float:
    """Return a numeric volume for a build123d shape or shape list."""
    if shape is None:
        return 0.0

    volume = getattr(shape, "volume", None)
    if volume is not None:
        try:
            return float(volume)
        except (TypeError, ValueError):
            pass

    if isinstance(shape, (str, bytes, dict)):
        return 0.0

    try:
        iterator = iter(shape)
    except TypeError:
        return 0.0

    total = 0.0
    for item in iterator:
        item_volume = getattr(item, "volume", None)
        if item_volume is None:
            continue
        try:
            total += float(item_volume)
        except (TypeError, ValueError):
            continue
    return total


def _workspace_relative_render_paths(
    render_paths: list[str], workspace_root: Path
) -> list[str]:
    """Normalize render paths so serialized artifacts stay workspace-relative."""
    resolved_root = workspace_root.resolve()
    normalized: list[str] = []
    for raw_path in render_paths:
        candidate = Path(raw_path)
        if candidate.is_absolute():
            try:
                normalized.append(str(candidate.resolve().relative_to(resolved_root)))
                continue
            except Exception:
                normalized.append(str(candidate))
                continue
        normalized.append(str(candidate))
    return normalized


def _simulation_video_s3_client() -> S3Client | None:
    access_key = (
        os.getenv("S3_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or "minioadmin"
    )
    secret_key = (
        os.getenv("S3_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or "minioadmin"
    )
    if not access_key or not secret_key:
        return None

    endpoint_url = _stack_profile_s3_endpoint()
    if endpoint_url is None:
        endpoint_url = os.getenv("S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT")
    return S3Client(
        S3Config(
            endpoint_url=endpoint_url,
            access_key_id=access_key,
            secret_access_key=secret_key,
            bucket_name=os.getenv("ASSET_S3_BUCKET", "problemologist"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    )


def _register_simulation_video_object_store_key(
    *,
    video_path: Path,
    working_dir: Path,
    render_object_store_keys: dict[str, str],
    session_id: str | None,
) -> None:
    rel_key = str(video_path.relative_to(working_dir))
    client = _simulation_video_s3_client()
    if client is None:
        logger.info(
            "simulation_video_object_store_skipped",
            session_id=session_id,
            rel_path=rel_key,
            reason="storage_unavailable",
        )
        return

    object_key = client.upload_file(video_path, rel_key)
    render_object_store_keys[rel_key] = object_key


def _prerender_24_views_isolated(
    *,
    working_dir: Path,
    output_dir: Path,
    backend_type: SimulatorBackendType | None,
    session_id: str | None,
    smoke_test_mode: bool,
    particle_budget: int | None,
    revision: str | None = None,
    script_path: Path | str | None = None,
    script_content: str | None = None,
    objectives: BenchmarkDefinition | None = None,
    publish_bundle_index: bool = False,
) -> list[str]:
    """Render previews in a fresh subprocess to avoid GL state contamination.

    The child process must render the exact source snapshot already loaded by
    the parent. That keeps validation previews aligned with inline
    `script_content` and non-default `script_path` entrypoints instead of
    rediscovering `working_dir/script.py` from disk.
    """

    repo_root = Path(__file__).resolve().parents[2]
    child_env = os.environ.copy()
    child_pythonpath = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = (
        f"{repo_root}{os.pathsep}{child_pythonpath}"
        if child_pythonpath
        else str(repo_root)
    )
    child_env["IS_HEAVY_WORKER"] = "1"
    current_revision = repo_revision(repo_root)
    if current_revision:
        child_env.setdefault("REPO_REVISION", current_revision)

    render_paths_fd, render_paths_name = tempfile.mkstemp(
        prefix="prerender_paths_", suffix=".json"
    )
    os.close(render_paths_fd)
    render_paths_file = Path(render_paths_name)

    backend_value = backend_type.value if backend_type is not None else ""
    script_source_path = (
        Path(script_path) if script_path is not None else (working_dir / "script.py")
    )
    script_content_b64 = (
        base64.b64encode(script_content.encode("utf-8")).decode("ascii")
        if script_content is not None
        else ""
    )
    objectives_b64 = (
        base64.b64encode(objectives.model_dump_json(indent=2).encode("utf-8")).decode(
            "ascii"
        )
        if objectives is not None
        else ""
    )
    child_code = textwrap.dedent(
        """
        from __future__ import annotations

        import base64
        import json
        import os
        import sys
        from pathlib import Path

        from shared.models.schemas import BenchmarkDefinition
        from shared.simulation.schemas import SimulatorBackendType
        from shared.workers.loader import load_component_from_script
        from worker_heavy.utils.rendering import prerender_24_views

        script_path = Path(sys.argv[1])
        working_dir = script_path.parent
        output_dir = Path(sys.argv[2])
        render_paths_file = Path(sys.argv[3])
        backend_value = sys.argv[4]
        smoke_test_mode = sys.argv[5] == "1"
        session_id = sys.argv[6] or None
        particle_budget = int(sys.argv[7]) if sys.argv[7] else None
        script_content_b64 = sys.argv[8] if len(sys.argv) > 8 else ""
        objectives_b64 = sys.argv[9] if len(sys.argv) > 9 else ""
        publish_bundle_index = (
            sys.argv[10] == "1" if len(sys.argv) > 10 else False
        )

        script_content = (
            base64.b64decode(script_content_b64).decode("utf-8")
            if script_content_b64
            else None
        )
        objectives = (
            BenchmarkDefinition.model_validate_json(
                base64.b64decode(objectives_b64).decode("utf-8")
            )
            if objectives_b64
            else None
        )

        component = load_component_from_script(
            script_path=script_path,
            session_root=working_dir,
            script_content=script_content,
        )

        revision = os.environ.get("REPO_REVISION")

        backend_type = (
            SimulatorBackendType(backend_value) if backend_value else None
        )
        render_paths = prerender_24_views(
            component,
            output_dir=str(output_dir),
            workspace_root=working_dir,
            objectives=objectives,
            backend_type=backend_type,
            session_id=session_id,
            smoke_test_mode=smoke_test_mode,
            particle_budget=particle_budget,
            revision=revision,
            publish_bundle_index=publish_bundle_index,
        )
        render_paths_file.write_text(
            json.dumps(render_paths, indent=2),
            encoding="utf-8",
        )
        """
    ).strip()

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                child_code,
                str(script_source_path),
                str(output_dir),
                str(render_paths_file),
                backend_value,
                "1" if smoke_test_mode else "0",
                session_id or "",
                str(particle_budget) if particle_budget is not None else "",
                script_content_b64,
                objectives_b64,
                "1" if publish_bundle_index else "0",
            ],
            cwd=working_dir,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            stdout = completed.stdout.strip()
            message = stderr or stdout or "isolated preview render failed"
            raise RuntimeError(message)

        return json.loads(render_paths_file.read_text(encoding="utf-8"))
    finally:
        with contextlib.suppress(FileNotFoundError):
            render_paths_file.unlink()


def _benchmark_refusal_error(reason: BenchmarkRefusalReason, message: str) -> str:
    return f"{reason.value}: {message}"


def _boxes_intersect(
    a_min: tuple[float, float, float],
    a_max: tuple[float, float, float],
    b_min: tuple[float, float, float],
    b_max: tuple[float, float, float],
) -> bool:
    return all(a_min[i] <= b_max[i] and b_min[i] <= a_max[i] for i in range(3))


def _validate_bounding_box_order(label: str, box: Any) -> str | None:
    for axis, min_value, max_value in zip(("x", "y", "z"), box.min_mm, box.max_mm):
        if min_value > max_value:
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.INVALID_OBJECTIVES,
                f"{label} has inverted bounds on axis {axis}: "
                f"min {min_value} > max {max_value}",
            )
    return None


def _validate_non_negative_range(
    label: str, values: tuple[float, ...] | None
) -> str | None:
    if values is None:
        return None

    if any(value < 0 for value in values):
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.INVALID_OBJECTIVES,
            f"{label} must be non-negative; got {list(values)}",
        )

    if len(values) == 2 and values[0] > values[1]:
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.INVALID_OBJECTIVES,
            f"{label} minimum must be <= maximum; got {list(values)}",
        )

    return None


def _validate_box_within(
    inner_label: str,
    inner_box: Any,
    outer_label: str,
    outer_box: Any,
) -> str | None:
    """Fail closed when one box is not fully contained in another."""
    for i, axis in enumerate(("x", "y", "z")):
        if (
            inner_box.min_mm[i] < outer_box.min_mm[i]
            or inner_box.max_mm[i] > outer_box.max_mm[i]
        ):
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
                f"{inner_label} exceeds {outer_label} on axis {axis}",
            )
    return None


def _validate_benchmark_definition_consistency(
    objectives: BenchmarkDefinition,
) -> str | None:
    """Fail closed on invalid objective relationships and jitter ranges."""
    goal = objectives.objectives.goal_zone_mm
    build_zone = objectives.objectives.build_zone_mm
    simulation_bounds = objectives.simulation_bounds_mm

    for label, box in (
        ("goal_zone_mm", goal),
        ("build_zone_mm", build_zone),
        ("simulation_bounds_mm", simulation_bounds),
    ):
        box_error = _validate_bounding_box_order(label, box)
        if box_error is not None:
            return box_error

    for zone_label, zone_box in (
        ("goal_zone_mm", goal),
        ("build_zone_mm", build_zone),
    ):
        zone_spans_mm = tuple(
            float(zone_box.max_mm[index]) - float(zone_box.min_mm[index])
            for index in range(3)
        )
        if max(zone_spans_mm) < MIN_OBJECTIVE_ZONE_SPAN_MM:
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.INVALID_OBJECTIVES,
                f"{zone_label} is smaller than the 3 mm sanity floor; "
                "fail closed instead of auto-scaling",
            )

    for zone in objectives.objectives.forbid_zones:
        zone_error = _validate_bounding_box_order(f"forbid zone '{zone.name}'", zone)
        if zone_error is not None:
            return zone_error

        zone_spans_mm = tuple(
            float(zone.max_mm[index]) - float(zone.min_mm[index]) for index in range(3)
        )
        if max(zone_spans_mm) < MIN_OBJECTIVE_ZONE_SPAN_MM:
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.INVALID_OBJECTIVES,
                f"forbid zone '{zone.name}' is smaller than the 3 mm sanity "
                "floor; fail closed instead of auto-scaling",
            )

        if _boxes_intersect(goal.min_mm, goal.max_mm, zone.min_mm, zone.max_mm):
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.CONTRADICTORY_CONSTRAINTS,
                f"goal_zone_mm overlaps forbid zone '{zone.name}'",
            )

    if not _boxes_intersect(
        goal.min_mm, goal.max_mm, build_zone.min_mm, build_zone.max_mm
    ):
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
            "goal_zone_mm does not overlap build_zone_mm",
        )

    try:
        solvability_policy = load_agents_config().benchmark_solvability
    except Exception as exc:
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
            f"unable to load benchmark solvability policy: {exc}",
        )

    minimum_angle_deg = float(solvability_policy.minimum_payload_to_goal_angle_deg)
    spawn_position_mm = tuple(
        float(value) for value in objectives.payload.start_position_mm
    )
    goal_bottom_center_mm = (
        (goal.min_mm[0] + goal.max_mm[0]) / 2.0,
        (goal.min_mm[1] + goal.max_mm[1]) / 2.0,
        goal.min_mm[2],
    )
    horizontal_distance_mm = math.hypot(
        goal_bottom_center_mm[0] - spawn_position_mm[0],
        goal_bottom_center_mm[1] - spawn_position_mm[1],
    )
    observed_angle_deg = math.degrees(
        math.atan2(
            spawn_position_mm[2] - goal_bottom_center_mm[2],
            horizontal_distance_mm,
        )
    )
    if observed_angle_deg + 1e-9 < minimum_angle_deg:
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
            "payload start position is too shallow relative to the goal bottom "
            f"center: observed {observed_angle_deg:.2f}deg < required "
            f"{minimum_angle_deg:.2f}deg",
        )

    jitter = objectives.payload.runtime_jitter_mm
    start = objectives.payload.start_position_mm
    jitter_error = _validate_non_negative_range("payload.runtime_jitter_mm", jitter)
    if jitter_error is not None:
        return jitter_error

    radius_max = 0.0
    radius_range = objectives.payload.static_randomization.radius_mm
    radius_error = _validate_non_negative_range(
        "payload.static_randomization.radius_mm", radius_range
    )
    if radius_error is not None:
        return radius_error
    if radius_range:
        radius_max = max(radius_range)

    moved_min = (
        start[0] - jitter[0] - radius_max,
        start[1] - jitter[1] - radius_max,
        start[2] - jitter[2] - radius_max,
    )
    moved_max = (
        start[0] + jitter[0] + radius_max,
        start[1] + jitter[1] + radius_max,
        start[2] + jitter[2] + radius_max,
    )

    if not _boxes_intersect(moved_min, moved_max, build_zone.min_mm, build_zone.max_mm):
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
            "payload runtime envelope does not overlap build_zone_mm",
        )
    for i, axis in enumerate(("x", "y", "z")):
        if moved_min[i] < build_zone.min_mm[i] or moved_max[i] > build_zone.max_mm[i]:
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
                f"payload runtime envelope exceeds build_zone_mm on axis {axis}",
            )

    for zone in objectives.objectives.forbid_zones:
        if _boxes_intersect(moved_min, moved_max, zone.min_mm, zone.max_mm):
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.CONTRADICTORY_CONSTRAINTS,
                "payload runtime envelope intersects forbid zone "
                f"'{zone.name}' across jitter/randomization",
            )

    return None


def validate_benchmark_submission_simulation_bounds(
    objectives: BenchmarkDefinition,
) -> str | None:
    """Fail closed when the benchmark build zone exceeds the declared bounds."""
    return _validate_box_within(
        "build_zone_mm",
        objectives.objectives.build_zone_mm,
        "simulation_bounds_mm",
        objectives.simulation_bounds_mm,
    )


def _metadata_is_fixed(metadata: Any) -> bool:
    """Resolve fixed/static intent from PartMetadata/CompoundMetadata-like values."""
    if metadata is None:
        return False
    value = getattr(metadata, "is_fixed", None)
    if value is not None:
        return bool(value)
    if isinstance(metadata, dict):
        if "is_fixed" not in metadata:
            raise ValueError("deprecated functionality removed: fixed metadata key")
        return bool(metadata["is_fixed"])
    return False


def _prefix_part_violation(label: str, violation: str) -> str:
    prefix = f"{label}: "
    return violation if violation.startswith(prefix) else f"{prefix}{violation}"


def _validate_parent_fixed_contract(
    component: Compound, objectives: BenchmarkDefinition | None
) -> str | None:
    """Reject the misleading parent-only fixed pattern for benchmark fixtures."""
    if not _metadata_is_fixed(getattr(component, "metadata", None)):
        return None

    moved_label = None
    if objectives and objectives.payload:
        moved_label = objectives.payload.label

    unfixed_children: list[str] = []
    for child in getattr(component, "children", []) or []:
        label = getattr(child, "label", "") or "<unlabeled>"
        if label.startswith("zone_") or label == moved_label:
            continue
        if not _metadata_is_fixed(getattr(child, "metadata", None)):
            unfixed_children.append(label)

    if not unfixed_children:
        return None

    joined = ", ".join(unfixed_children[:5])
    if len(unfixed_children) > 5:
        joined = f"{joined}, ..."
    return (
        "CompoundMetadata(is_fixed=True) on the parent assembly does not make child "
        "parts static. Mark each static benchmark fixture with "
        "PartMetadata(..., is_fixed=True). Offending children: "
        f"{joined}"
    )


def _validate_top_level_location_contract(component: Compound) -> str | None:
    """Reject top-level translated geometry that will collapse to origin in MJCF."""
    offenders: list[str] = []
    for child in getattr(component, "children", []) or []:
        label = getattr(child, "label", "") or "<unlabeled>"
        if label.startswith("zone_"):
            continue

        position = getattr(getattr(child, "location", None), "position", None)
        if position is None:
            continue
        if any(abs(coord) > 1e-6 for coord in (position.X, position.Y, position.Z)):
            continue

        bbox = child.bounding_box()
        center = (
            (bbox.min.X + bbox.max.X) / 2,
            (bbox.min.Y + bbox.max.Y) / 2,
            (bbox.min.Z + bbox.max.Z) / 2,
        )
        half_sizes = (
            bbox.size.X / 2,
            bbox.size.Y / 2,
            bbox.size.Z / 2,
        )

        # A part that was created in place at the origin can legitimately have a
        # non-zero bounding-box center when it is aligned to a face or edge.
        # We only flag parts whose geometry is displaced beyond what the part's
        # own dimensions explain, which is the pattern produced by `.translate(...)`.
        if all(abs(center[i]) <= half_sizes[i] + 1e-6 for i in range(3)):
            continue
        offenders.append(label)

    if not offenders:
        return None

    joined = ", ".join(offenders[:5])
    if len(offenders) > 5:
        joined = f"{joined}, ..."
    return (
        "Top-level parts appear translated in geometry while their location "
        "remains at the origin. Use `.move(Location(...))` or "
        "`.moved(Location(...))` for part placement, and do not use "
        "`.translate(...)` for benchmark assembly placement because the "
        "simulation exporter recenters meshes before applying `child.location`. "
        f"Offending parts: {joined}"
    )


def _validate_payload_start_clearance(
    component: Compound, objectives: BenchmarkDefinition | None
) -> str | None:
    """Reject benchmark fixtures that overlap the runtime-spawned payload."""
    if objectives is None or getattr(objectives, "payload", None) is None:
        return None

    try:
        payload_geometry = build_payload_start_geometry(objectives.payload)
    except Exception as exc:
        return f"Unable to materialize payload startup geometry: {exc}"

    for index, solid in enumerate(component.solids()):
        label = getattr(solid, "label", None) or f"solid_{index}"
        try:
            intersection = payload_geometry.intersect(solid)
        except Exception as exc:
            return (
                f"Unable to evaluate payload startup clearance against {label}: {exc}"
            )
        if _shape_volume(intersection) > 1e-6:
            return (
                "payload start pose intersects benchmark geometry "
                f"(offending solid: {label})"
            )

    return None


def _validate_unique_top_level_labels(component: Compound) -> str | None:
    """Reject repeated or reserved top-level labels before MJCF generation."""
    children = getattr(component, "children", None) or [component]
    label_counts: dict[str, int] = {}
    label_order: list[str] = []
    reserved_prefixes = ("zone_", PAYLOAD_SCENE_PREFIX)
    reserved_exact_labels = {"environment"}

    for child in children:
        label = getattr(child, "label", None)
        if label is None:
            msg = (
                "Top-level part labels must be non-empty strings. Offending label: "
                "<missing>"
            )
            logger.error("top_level_label_missing", label="<missing>")
            return msg
        normalized = str(label).strip()
        if not normalized:
            msg = (
                "Top-level part labels must be non-empty strings. Offending label: "
                "<blank>"
            )
            logger.error("top_level_label_blank", label=str(label))
            return msg
        if normalized in reserved_exact_labels:
            return (
                "Top-level part labels may not be `environment` because that "
                "name is reserved for the benchmark scene/root environment. "
                f"Offending label: {normalized}"
            )
        if any(normalized.startswith(prefix) for prefix in reserved_prefixes):
            if normalized.startswith("zone_"):
                reserved_namespace = "`zone_`"
            else:
                reserved_namespace = f"`{PAYLOAD_SCENE_PREFIX}`"
            return (
                "Top-level part labels may not start with "
                f"{reserved_namespace} because that namespace is reserved for "
                "simulator-generated scene bodies. "
                f"Offending label: {normalized}"
            )
        if normalized not in label_counts:
            label_order.append(normalized)
            label_counts[normalized] = 0
        label_counts[normalized] += 1

    offenders = [label for label in label_order if label_counts[label] > 1]
    if not offenders:
        return None

    details = ", ".join(f"{label} x{label_counts[label]}" for label in offenders[:5])
    if len(offenders) > 5:
        details = f"{details}, ..."
    return (
        "Duplicate top-level part labels are not allowed because MJCF mesh and "
        "body names are derived from labels. Offending labels: "
        f"{details}"
    )


def load_simulation_result(path: Path) -> SimulationResult | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SimulationResult.model_validate(data)
    except Exception as e:
        logger.warning(
            "failed_to_load_simulation_result",
            path=str(path),
            error=str(e),
            session_id=None,
        )
        return None


def _benchmark_payload_out_of_bounds_summary(
    metrics: SimulationMetrics,
    *,
    benchmark_mode: bool,
) -> str | None:
    if not benchmark_mode:
        return None

    for event in metrics.events:
        if event.get("type") != "benchmark_payload_out_of_bounds_after_window":
            continue

        data = event.get("data") if isinstance(event, dict) else None
        if not isinstance(data, dict):
            return "Benchmark payload left simulation bounds after the observation window; recorded as evidence."

        payload_label = str(
            data.get("payload_label") or data.get("body") or "benchmark payload"
        ).strip()
        observation_window_s = data.get("observation_window_s")
        if observation_window_s is not None:
            try:
                window_text = f"{float(observation_window_s):.1f}s"
            except (TypeError, ValueError):
                window_text = f"{observation_window_s!s}s"
            return (
                f"Benchmark payload {payload_label} left simulation bounds after "
                f"{window_text}; recorded as evidence."
            )

        return (
            f"Benchmark payload {payload_label} left simulation bounds; "
            "recorded as evidence."
        )

    return None


def save_simulation_result(result: SimulationResult, path: Path):
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")


def to_mjcf(
    component: Compound,
    renders_dir: Path | None = None,
    smoke_test_mode: bool | None = None,
) -> str:
    """Convert a build123d Compound to a MuJoCo XML (MJCF) string."""
    from worker_heavy.config import settings

    if smoke_test_mode is None:
        smoke_test_mode = settings.smoke_test_mode

    if not renders_dir:
        renders_dir = Path(os.getenv("RENDERS_DIR", "./renders"))
    renders_dir.mkdir(parents=True, exist_ok=True)

    builder = get_simulation_builder(
        output_dir=renders_dir, backend_type=SimulatorBackendType.MUJOCO
    )
    scene_path = builder.build_from_assembly(component, smoke_test_mode=smoke_test_mode)
    return scene_path.read_text()


def calculate_assembly_totals(
    component: Compound,
    assembly_definition: AssemblyDefinition | None = None,
    manufacturing_config: ManufacturingConfig | None = None,
    session_id: str | None = None,
    quantity: int = 1,
) -> tuple[float, float]:
    """
    Calculate total cost and weight of the assembly.
    """
    config = manufacturing_config or load_config()
    total_cost = 0.0
    total_weight = 0.0

    # 1. Manufactured parts
    children = getattr(component, "children", [])
    if not children:
        children = [component]

    for child in children:
        metadata = getattr(child, "metadata", None)
        if not metadata:
            continue

        if _metadata_is_fixed(metadata):
            continue

        method = getattr(metadata, "manufacturing_method", None)
        from shared.workers.workbench_models import ManufacturingMethod

        try:
            if isinstance(method, str):
                method = ManufacturingMethod(method)

            if not method:
                continue

            res = validate_and_price(
                child,
                method,
                config,
                session_id=session_id,
                quantity=quantity,
            )
            total_cost += res.unit_cost
            total_weight += res.weight_g
        except Exception as e:
            logger.error(
                "failed_to_price_manufactured_part",
                part=getattr(child, "label", "unknown"),
                error=str(e),
                session_id=session_id,
            )
            raise

    return total_cost, total_weight


def simulate_subprocess(
    script_path: Path | str,
    session_root: Path | str,
    script_content: str | None = None,
    output_dir: Path | None = None,
    smoke_test_mode: bool | None = None,
    backend: Any | None = None,
    session_id: str | None = None,
    episode_id: str | None = None,
    stream_render_frames: bool = False,
    skip_preview_rendering: bool = False,
    particle_budget: int | None = None,
) -> SimulationResult:
    """Serializable entry point for ProcessPoolExecutor."""
    # Ensure events are written to the session's event log
    if session_root:
        os.environ["EVENTS_FILE"] = str(Path(session_root) / "events.jsonl")
        Path(session_root, "_env_probe.json").write_text(
            json.dumps(
                {
                    "stack_profile": os.getenv("PROBLEMOLOGIST_STACK_PROFILE"),
                    "s3_endpoint": os.getenv("S3_ENDPOINT"),
                    "s3_endpoint_url": os.getenv("S3_ENDPOINT_URL"),
                    "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
                    "aws_secret_access_key_set": bool(
                        os.getenv("AWS_SECRET_ACCESS_KEY")
                    ),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    logger.info(
        "simulate_subprocess_env",
        stack_profile=os.getenv("PROBLEMOLOGIST_STACK_PROFILE"),
        s3_endpoint=os.getenv("S3_ENDPOINT"),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key_set=bool(os.getenv("AWS_SECRET_ACCESS_KEY")),
    )

    from shared.workers.loader import load_component_from_script
    from worker_heavy.config import settings

    if smoke_test_mode is None:
        smoke_test_mode = settings.smoke_test_mode

    component = load_component_from_script(
        script_path=Path(script_path),
        session_root=Path(session_root),
        script_content=script_content,
    )
    return simulate(
        component=component,
        output_dir=output_dir,
        smoke_test_mode=smoke_test_mode,
        backend=backend,
        session_id=session_id,
        episode_id=episode_id,
        stream_render_frames=stream_render_frames,
        skip_preview_rendering=skip_preview_rendering,
        particle_budget=particle_budget,
        script_path=script_path,
        script_content=script_content,
    )


def validate_subprocess(
    script_path: Path | str,
    session_root: Path | str,
    script_content: str | None = None,
    output_dir: Path | None = None,
    smoke_test_mode: bool | None = None,
    session_id: str | None = None,
    particle_budget: int | None = None,
) -> tuple[bool, str | None]:
    """Serializable entry point for ProcessPoolExecutor validation runs."""
    if session_root:
        os.environ["EVENTS_FILE"] = str(Path(session_root) / "events.jsonl")

    from shared.workers.loader import load_component_from_script
    from worker_heavy.config import settings

    if smoke_test_mode is None:
        smoke_test_mode = settings.smoke_test_mode

    component = load_component_from_script(
        script_path=Path(script_path),
        session_root=Path(session_root),
        script_content=script_content,
    )
    is_valid, message = validate(
        component,
        output_dir=output_dir,
        session_id=session_id,
        smoke_test_mode=smoke_test_mode,
        particle_budget=particle_budget,
    )

    return is_valid, message


def simulate(
    component: Compound,
    output_dir: Path | None = None,
    particle_budget: int | None = None,
    smoke_test_mode: bool | None = None,
    backend: SimulatorBackendType | None = None,
    session_id: str | None = None,
    episode_id: str | None = None,
    stream_render_frames: bool = False,
    skip_preview_rendering: bool = False,
    script_path: str | Path | None = None,
    script_content: str | None = None,
) -> SimulationResult:
    """Provide a physics-backed stability and objective check."""
    from worker_heavy.config import settings
    from worker_heavy.simulation.frame_stream import SimulationFrameStreamPublisher
    from worker_heavy.simulation.loop import SimulationLoop

    if smoke_test_mode is None:
        smoke_test_mode = settings.smoke_test_mode

    logger.info(
        "simulate_start",
        particle_budget=particle_budget,
        smoke_test_mode=smoke_test_mode,
        backend=backend,
        session_id=session_id,
        episode_id=episode_id,
        stream_render_frames=stream_render_frames,
    )
    label_contract_error = _validate_unique_top_level_labels(component)
    if label_contract_error:
        return SimulationResult(
            success=False,
            summary=label_contract_error,
            failure=SimulationFailure(
                reason=FailureReason.VALIDATION_FAILED,
                detail=label_contract_error,
            ),
            confidence=SimulationConfidence.HIGH,
        )

    working_dir = output_dir or Path(os.getenv("RENDERS_DIR", "./renders")).parent
    logger.info(
        "DEBUG_simulate",
        working_dir=str(working_dir),
        exists=working_dir.exists(),
        files=list(working_dir.iterdir()) if working_dir.exists() else [],
    )
    current_role = current_role_agent_name(working_dir)
    benchmark_mode = role_family_for_agent(current_role) == "benchmark"
    renders_dir = (
        working_dir
        / "renders"
        / select_scratch_preview_render_subdir(
            working_dir,
            agent_role=current_role.value,
        )
    )
    renders_dir.mkdir(parents=True, exist_ok=True)

    objectives = None
    assembly_definition = None
    payload_trajectory_definition: PayloadTrajectoryDefinition | None = None
    objectives_path = working_dir / "benchmark_definition.yaml"
    if objectives_path.exists():
        content = objectives_path.read_text(encoding="utf-8")
        if "[TEMPLATE]" not in content:
            try:
                objectives = _load_valid_benchmark_definition(
                    content, session_id=session_id
                )
                fixed_contract_error = _validate_parent_fixed_contract(
                    component, objectives
                )
                if fixed_contract_error:
                    return SimulationResult(
                        success=False,
                        summary=fixed_contract_error,
                        failure=SimulationFailure(
                            reason=FailureReason.VALIDATION_FAILED,
                            detail=fixed_contract_error,
                        ),
                        confidence=SimulationConfidence.HIGH,
                    )
                location_contract_error = _validate_top_level_location_contract(
                    component
                )
                if location_contract_error:
                    return SimulationResult(
                        success=False,
                        summary=location_contract_error,
                        failure=SimulationFailure(
                            reason=FailureReason.VALIDATION_FAILED,
                            detail=location_contract_error,
                        ),
                        confidence=SimulationConfidence.HIGH,
                    )
                logger.info(
                    "DEBUG_objectives_loaded",
                    physics=objectives.physics.model_dump()
                    if objectives.physics
                    else None,
                )
                requested_quantity = resolve_requested_quantity(
                    benchmark_definition=objectives,
                )
            except Exception as e:
                import traceback

                print(f"FAILED TO LOAD OBJECTIVES: {e}")
                traceback.print_exc()
                logger.error(
                    "failed_to_load_objectives", error=str(e), session_id=session_id
                )
                return SimulationResult(
                    success=False,
                    summary=f"benchmark_definition.yaml invalid: {e}",
                    failure=SimulationFailure(
                        reason=FailureReason.VALIDATION_FAILED,
                        detail=str(e),
                    ),
                    confidence=SimulationConfidence.HIGH,
                )

    try:
        payload_trajectory_definition = load_payload_trajectory_definition(working_dir)
    except Exception as exc:
        logger.error(
            "failed_to_load_payload_trajectory_definition",
            error=str(exc),
            session_id=session_id,
        )
        return SimulationResult(
            success=False,
            summary=f"payload_trajectory_definition.yaml invalid: {exc}",
            failure=SimulationFailure(
                reason=FailureReason.VALIDATION_FAILED,
                detail=str(exc),
            ),
            confidence=SimulationConfidence.HIGH,
        )

    cost_est_path = _find_workspace_assembly_definition(
        working_dir, prefer_benchmark=True
    )
    if cost_est_path is not None:
        try:
            data = yaml.safe_load(cost_est_path.read_text(encoding="utf-8"))
            assembly_definition = AssemblyDefinition(**data)
        except Exception as e:
            logger.error(
                "failed_to_load_assembly_definition",
                error=str(e),
                session_id=session_id,
            )

    backend_type = backend
    if backend_type is None:
        backend_type = get_default_simulator_backend()
        if objectives and _benchmark_requires_genesis(objectives):
            backend_type = SimulatorBackendType.GENESIS

    builder = get_simulation_builder(output_dir=working_dir, backend_type=backend_type)
    # FIXME(mvp-release): remove the payload_parts pass-through after the MVP
    # contract is simplified and builders no longer need this temporary seam.
    payload_parts = assembly_definition.payload_parts if assembly_definition else []
    manufactured_part_labels = (
        {part.part_name for part in assembly_definition.manufactured_parts}
        if assembly_definition
        else set()
    )

    scene_path = builder.build_from_assembly(
        component,
        objectives=objectives,
        payload_parts=payload_parts,
        smoke_test_mode=smoke_test_mode,
    )

    loop = SimulationLoop(
        str(scene_path),
        component=component,
        backend_type=backend_type,
        objectives=objectives,
        payload_trajectory_definition=payload_trajectory_definition,
        smoke_test_mode=smoke_test_mode,
        require_goal_completion=not benchmark_mode,
        benchmark_payload_observation_window_s=(
            load_agents_config().benchmark_payload_observation.window_s
            if benchmark_mode
            else None
        ),
        session_id=session_id,
        particle_budget=particle_budget,
        manufactured_part_labels=manufactured_part_labels,
    )

    dynamic_controllers = {}
    control_inputs = {}

    frame_stream_publisher = None
    try:
        if stream_render_frames and episode_id:
            frame_stream_publisher = SimulationFrameStreamPublisher(
                controller_url=settings.controller_url,
                episode_id=episode_id,
                session_id=session_id,
                enabled=True,
            )
        elif stream_render_frames:
            logger.warning(
                "simulation_frame_stream_disabled",
                reason="missing_episode_id",
                session_id=session_id,
            )

        simulation_bundle_id = f"{session_id or 'simulation'}-{uuid.uuid4().hex[:12]}"
        video_bundle_root = renders_dir / "simulation_video" / simulation_bundle_id
        video_path = video_bundle_root / "simulation.mp4"
        final_video_path: Path | None = video_path
        render_object_store_keys: dict[str, str] = {}
        sim_duration = 0.5 if smoke_test_mode else 30.0
        metrics = loop.step(
            control_inputs=control_inputs,
            duration=sim_duration,
            dynamic_controllers=dynamic_controllers,
            video_path=video_path,
            frame_stream_publisher=frame_stream_publisher,
        )
        render_provenance = loop.render_provenance
        if loop.render_object_store_key:
            render_object_store_keys[str(video_path.relative_to(working_dir))] = (
                loop.render_object_store_key
            )
        elif video_path.exists():
            _register_simulation_video_object_store_key(
                video_path=video_path,
                working_dir=working_dir,
                render_object_store_keys=render_object_store_keys,
                session_id=session_id,
            )

        # WP2: T017: GPU OOM Retry Logic
        if metrics.fail_reason and "out of memory" in metrics.fail_reason.lower():
            from shared.observability.events import emit_event
            from shared.observability.schemas import GpuOomRetryEvent

            logger.error("gpu_oom_detected_retrying_smoke_mode", session_id=session_id)

            # Emit event for observability
            emit_event(
                GpuOomRetryEvent(
                    original_particles=loop.particle_budget,
                    reduced_particles=5000,
                )
            )

            if video_path.exists():
                with contextlib.suppress(Exception):
                    video_path.unlink()
            final_video_path = None
            render_object_store_keys = {}

            from worker_heavy.simulation.loop import SimulationLoop

            # Re-create loop with reduced budget to force backend scene rebuild
            loop = SimulationLoop(
                str(scene_path),
                component=component,
                backend_type=backend_type,
                objectives=objectives,
                payload_trajectory_definition=payload_trajectory_definition,
                smoke_test_mode=True,
                session_id=session_id,
                particle_budget=5000,
            )
            metrics = loop.step(
                control_inputs=control_inputs,
                duration=sim_duration,
                dynamic_controllers=dynamic_controllers,
                video_path=None,  # Skip video during emergency retry path
                frame_stream_publisher=frame_stream_publisher,
            )
            render_provenance = loop.render_provenance
            if loop.render_object_store_key:
                render_object_store_keys[str(video_path.relative_to(working_dir))] = (
                    loop.render_object_store_key
                )
            elif video_path.exists():
                _register_simulation_video_object_store_key(
                    video_path=video_path,
                    working_dir=working_dir,
                    render_object_store_keys=render_object_store_keys,
                    session_id=session_id,
                )

        # Release the physics backend before starting the VTK preview pass.
        # MuJoCo/Genesis and the build123d renderer both touch GL/X state, and
        # keeping both alive inside the long-lived child process can crash the
        # renderer on the next GLX make-current call.
        close_all_session_backends()
        gc.collect()

        if metrics.fail_reason:
            status_msg = metrics.fail_reason
        elif benchmark_mode:
            status_msg = "Benchmark simulation stable."
        elif metrics.success:
            status_msg = "Goal achieved."
        else:
            status_msg = "Simulation stable."
        runtime_revision = (
            os.environ.get("REPO_REVISION")
            or repo_revision(Path.cwd())
            or repo_revision(Path(__file__).resolve().parents[2])
        )

        render_paths: list[str] = []
        if not skip_preview_rendering:
            try:
                isolated_script_path = working_dir / "script.py"
                if isolated_script_path.exists():
                    render_paths = _prerender_24_views_isolated(
                        working_dir=working_dir,
                        output_dir=renders_dir,
                        backend_type=backend_type,
                        session_id=session_id,
                        smoke_test_mode=smoke_test_mode,
                        particle_budget=particle_budget,
                        revision=runtime_revision,
                        script_path=script_path,
                        script_content=script_content,
                        objectives=objectives,
                        publish_bundle_index=False,
                    )
                else:
                    render_paths = prerender_24_views(
                        component,
                        output_dir=str(renders_dir),
                        workspace_root=working_dir,
                        backend_type=backend_type,
                        session_id=session_id,
                        scene_path=str(scene_path),
                        smoke_test_mode=smoke_test_mode,
                        revision=runtime_revision,
                        publish_bundle_index=False,
                    )
            except Exception as exc:
                logger.warning(
                    "validation_preview_render_failed",
                    error=str(exc),
                    session_id=session_id,
                )
                return SimulationResult(
                    success=False,
                    summary=f"Validation preview render failed: {exc}",
                    failure=SimulationFailure(
                        reason=FailureReason.VALIDATION_FAILED,
                        detail=str(exc),
                    ),
                    confidence=SimulationConfidence.HIGH,
                )
        if final_video_path and final_video_path.exists():
            render_paths.append(str(final_video_path))
            object_pose_path = final_video_path.parent / "objects.parquet"
            if object_pose_path.exists():
                render_paths.append(str(object_pose_path))
        render_paths = _workspace_relative_render_paths(render_paths, working_dir)

        video_render_paths = [
            path for path in render_paths if Path(path).suffix.lower() == ".mp4"
        ]
        if video_render_paths:
            video_bundle_path = str(Path(video_render_paths[0]).parent).replace(
                "\\", "/"
            )
            video_manifest_path = (
                working_dir / video_bundle_path / "render_manifest.json"
            )
            existing_manifest = None
            if video_manifest_path.exists():
                with contextlib.suppress(Exception):
                    existing_manifest = RenderManifest.model_validate_json(
                        video_manifest_path.read_text(encoding="utf-8")
                    )

            manifest = normalize_render_manifest(
                render_paths=video_render_paths,
                workspace_root=working_dir,
                existing_manifest=existing_manifest,
                episode_id=session_id,
                worker_session_id=session_id,
                revision=runtime_revision,
                environment_version=None,
                bundle_path=video_bundle_path,
            )
            video_manifest_path.write_text(
                manifest.model_dump_json(indent=2),
                encoding="utf-8",
            )
            append_render_bundle_index(
                working_dir,
                build_render_bundle_index_entry(
                    manifest,
                    manifest_path=str(
                        video_manifest_path.relative_to(working_dir)
                    ).replace("\\", "/"),
                    primary_media_paths=list(video_render_paths),
                ),
            )

        mjcf_content = scene_path.read_text() if scene_path.exists() else None

        pricing_config = load_config()
        custom_config_path = working_dir / "manufacturing_config.yaml"
        if custom_config_path.exists():
            pricing_config = load_merged_config(custom_config_path)

        try:
            cost, weight = calculate_assembly_totals(
                component,
                assembly_definition=assembly_definition,
                manufacturing_config=pricing_config,
                quantity=requested_quantity if objectives is not None else 1,
            )
        except ValueError as exc:
            logger.warning(
                "simulation_validation_failed",
                error=str(exc),
                session_id=session_id,
            )
            return SimulationResult(
                success=False,
                summary=str(exc),
                failure=SimulationFailure(
                    reason=FailureReason.VALIDATION_FAILED, detail=str(exc)
                ),
                confidence=SimulationConfidence.HIGH,
            )

        result = SimulationResult(
            success=metrics.success,
            summary=status_msg,
            failure=metrics.failure,
            payload_trajectory_monitor=metrics.payload_trajectory_monitor,
            render_provenance=render_provenance,
            render_paths=render_paths,
            render_object_store_keys=render_object_store_keys,
            mjcf_content=mjcf_content,
            total_cost=cost,
            total_weight_g=weight,
            confidence=metrics.confidence,
        )

        payload_position_summary = None
        if objectives and final_video_path and final_video_path.exists():
            payload_position_summary = summarize_payload_position_history(
                final_video_path.parent / "objects.parquet",
                payload_label=objectives.payload.label,
            )
        if payload_position_summary:
            result.summary = f"{result.summary}\n{payload_position_summary}"

        benchmark_payload_evidence_summary = _benchmark_payload_out_of_bounds_summary(
            metrics, benchmark_mode=benchmark_mode
        )
        if benchmark_payload_evidence_summary:
            result.summary = f"{result.summary}\n{benchmark_payload_evidence_summary}"

        try:
            save_simulation_result(result, working_dir / "simulation_result.json")
        except Exception as e:
            logger.error(
                "failed_to_save_simulation_result",
                error=str(e),
                session_id=session_id,
            )

        return result
    except Exception as e:
        logger.error("simulation_error", error=str(e), session_id=session_id)
        return SimulationResult(
            success=False,
            summary=f"Simulation error: {e!s}",
            failure=SimulationFailure(
                reason=FailureReason.PHYSICS_INSTABILITY, detail=str(e)
            ),
        )
    finally:
        if frame_stream_publisher is not None:
            with contextlib.suppress(Exception):
                frame_stream_publisher.close()


def validate(
    component: Compound,
    build_zone: dict | None = None,
    output_dir: Path | None = None,
    session_id: str | None = None,
    smoke_test_mode: bool | None = None,
    particle_budget: int | None = None,
) -> tuple[bool, str | None]:
    """Verify geometric validity."""
    from worker_heavy.config import settings

    if smoke_test_mode is None:
        smoke_test_mode = settings.smoke_test_mode
    working_root = Path(output_dir) if output_dir is not None else Path.cwd()

    logger.info(
        "validate_start",
        session_id=session_id,
        smoke_test_mode=smoke_test_mode,
        particle_budget=particle_budget,
    )
    try:
        current_role = current_role_agent_name(working_root)
    except Exception:
        current_role = None
    engineering_role = role_family_for_agent(current_role) == "engineering"
    benchmark_definition_model: BenchmarkDefinition | None = None
    label_contract_error = _validate_unique_top_level_labels(component)
    if label_contract_error:
        return False, label_contract_error

    solids = component.solids()
    if len(solids) > 1:
        for i in range(len(solids)):
            for j in range(i + 1, len(solids)):
                label_i = getattr(solids[i], "label", None) or f"unlabeled_solid_{i}"
                label_j = getattr(solids[j], "label", None) or f"unlabeled_solid_{j}"
                intersection = solids[i].intersect(solids[j])
                intersection_volume = _shape_volume(intersection)
                if intersection_volume > 0.1:
                    msg = (
                        f"Geometric intersection detected between {label_i} and "
                        f"{label_j} (volume: {intersection_volume:.2f})"
                    )
                    return (False, msg)

    bbox = component.bounding_box()

    # Load build_zone from benchmark_definition.yaml if not provided
    effective_build_zone = build_zone
    if effective_build_zone is None:
        obj_path = working_root / "benchmark_definition.yaml"
        if obj_path.exists():
            try:
                content = obj_path.read_text(encoding="utf-8")
                lines = content.splitlines()
                # Check if it is a template (placeholder) file
                if lines and "[TEMPLATE]" in lines[0]:
                    effective_build_zone = None
                else:
                    obj_model = _load_valid_benchmark_definition(
                        content, session_id=session_id
                    )
                    objective_error = _validate_benchmark_definition_consistency(
                        obj_model
                    )
                    if objective_error:
                        return (
                            False,
                            f"Invalid benchmark_definition.yaml: {objective_error}",
                        )
                    benchmark_definition_model = obj_model
                    fixed_contract_error = _validate_parent_fixed_contract(
                        component, obj_model
                    )
                    if fixed_contract_error:
                        return (False, fixed_contract_error)
                    location_contract_error = _validate_top_level_location_contract(
                        component
                    )
                    if location_contract_error:
                        return (False, location_contract_error)
                    payload_clearance_error = _validate_payload_start_clearance(
                        component, obj_model
                    )
                    if payload_clearance_error:
                        return False, payload_clearance_error
                    effective_build_zone = (
                        obj_model.objectives.build_zone_mm.model_dump()
                    )
            except Exception:
                pass

    build_zone_mm_for_compare = None
    if effective_build_zone is not None:
        try:
            build_zone_min_mm, build_zone_max_mm = (
                _objective_zone_bounds_mm_for_compare(effective_build_zone)
            )
            build_zone_mm_for_compare = {
                "min_mm": build_zone_min_mm,
                "max_mm": build_zone_max_mm,
            }
        except ValueError as exc:
            return False, f"Invalid build_zone_mm: {exc}"

    if engineering_role:
        payload_path = working_root / "payload_trajectory_definition.yaml"
        if not payload_path.exists():
            return False, "payload_trajectory_definition.yaml is missing"

        try:
            from worker_heavy.utils.file_validation import (
                validate_payload_trajectory_definition_yaml,
            )

            assembly_definition_model = None
            benchmark_assembly_definition_model = None

            assembly_path = _find_workspace_assembly_definition(
                working_root, prefer_benchmark=False
            )
            if assembly_path is not None and assembly_path.exists():
                assembly_definition_model = AssemblyDefinition.model_validate(
                    yaml.safe_load(assembly_path.read_text(encoding="utf-8"))
                )

            benchmark_assembly_path = (
                working_root / "benchmark_assembly_definition.yaml"
            )
            if benchmark_assembly_path.exists():
                benchmark_assembly_definition_model = AssemblyDefinition.model_validate(
                    yaml.safe_load(benchmark_assembly_path.read_text(encoding="utf-8"))
                )

            is_valid, payload_result = validate_payload_trajectory_definition_yaml(
                payload_path.read_text(encoding="utf-8"),
                benchmark_definition=benchmark_definition_model,
                coarse_payload_trajectory=(
                    assembly_definition_model.coarse_payload_trajectory
                    if assembly_definition_model is not None
                    else None
                ),
                assembly_definition=assembly_definition_model,
                benchmark_assembly_definition=benchmark_assembly_definition_model,
                workspace_root=working_root,
                session_id=session_id,
            )
        except Exception as exc:
            return False, f"payload_trajectory_definition.yaml invalid: {exc}"

        if not is_valid:
            return False, "; ".join(payload_result)

    if build_zone_mm_for_compare:
        b_min = build_zone_mm_for_compare.get(
            "min_mm", build_zone_mm_for_compare.get("min", [-1000, -1000, -1000])
        )
        b_max = build_zone_mm_for_compare.get(
            "max_mm", build_zone_mm_for_compare.get("max", [1000, 1000, 1000])
        )
        if (
            b_min[0] > bbox.min.X
            or b_min[1] > bbox.min.Y
            or b_min[2] > bbox.min.Z
            or b_max[0] < bbox.max.X
            or b_max[1] < bbox.max.Y
            or b_max[2] < bbox.max.Z
        ):
            offenders: list[str] = []
            children = getattr(component, "children", []) or [component]
            for child in children:
                child_bbox = child.bounding_box()
                if (
                    b_min[0] > child_bbox.min.X
                    or b_min[1] > child_bbox.min.Y
                    or b_min[2] > child_bbox.min.Z
                    or b_max[0] < child_bbox.max.X
                    or b_max[1] < child_bbox.max.Y
                    or b_max[2] < child_bbox.max.Z
                ):
                    label = getattr(child, "label", None) or "<unlabeled>"
                    offenders.append(f"{label}: {child_bbox}")
            offender_text = ""
            if offenders:
                offender_text = f"; offending parts: {', '.join(offenders[:5])}"
            return (
                False,
                "Build zone violation: "
                f"bbox {bbox} outside build_zone {build_zone_mm_for_compare}"
                f"{offender_text}",
            )
    else:
        if bbox.size.X > 1000.0 or bbox.size.Y > 1000.0 or bbox.size.Z > 1000.0:
            return (
                False,
                f"Boundary constraint violation: size {bbox.size} exceeds 1000.0",
            )

    # Validation is intentionally geometry-only. Preview evidence belongs to the
    # explicit preview path, not the default validate() contract.
    return True, None
