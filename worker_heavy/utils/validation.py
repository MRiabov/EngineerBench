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
from typing import Any, Literal

import structlog
import yaml
from build123d import Compound

from shared.agents.config import load_agents_config
from shared.current_role import current_role_agent_name
from shared.enums import (
    AgentName,
    BenchmarkRefusalReason,
    ElectronicComponentType,
    FailureReason,
    MotorControlMode,
    SimulationConfidence,
)
from shared.git_utils import repo_revision
from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    CotsPartEstimate,
    ElectronicsSection,
    FluidDefinition,
    FluidProperties,
    FluidVolume,
    PayloadTrajectoryDefinition,
)
from shared.models.simulation import (
    SimulationFailure,
    SimulationMetrics,
    SimulationResult,
    StressFieldData,
    StressSummary,
)
from shared.observability.events import emit_event
from shared.observability.schemas import WireRoutingEvent
from shared.observability.storage import S3Client, S3Config
from shared.rendering import (
    append_render_bundle_index,
    build_render_bundle_index_entry,
    normalize_render_manifest,
    render_stress_heatmap_artifact,
    select_scratch_preview_render_subdir,
)
from shared.script_contracts import (
    role_family_for_agent,
)
from shared.simulation.scene_builder import (
    MOVED_OBJECT_SCENE_PREFIX,
    build_moved_object_start_geometry,
)
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.wire_utils import calculate_path_length, check_wire_clearance
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
    _metadata_cots_id,
    calculate_benchmark_drilling_cost,
    resolve_requested_quantity,
    validate_and_price,
    validate_and_price_assembly,
)

logger = structlog.get_logger(__name__)


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


def _drafting_preview_role(script_path: str | Path | None) -> AgentName | None:
    del script_path
    try:
        agent_role = current_role_agent_name(Path.cwd())
    except Exception:
        return None
    if agent_role in {
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_REVIEWER,
        AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
        AgentName.ELECTRONICS_REVIEWER,
    }:
        return agent_role
    if agent_role in {
        AgentName.BENCHMARK_PLANNER,
        AgentName.ENGINEER_PLANNER,
        AgentName.ELECTRONICS_PLANNER,
        AgentName.BENCHMARK_PLAN_REVIEWER,
        AgentName.ENGINEER_PLAN_REVIEWER,
    }:
        return None
    return None


def _validate_drafting_preview_gate(
    *,
    working_root: Path,
    script_path: str | Path | None,
    session_id: str | None,
) -> str | None:
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
    """Return True only when the benchmark needs FEM/fluid-capable physics."""
    if objectives is None:
        return False

    physics = getattr(objectives, "physics", None)
    if physics and getattr(physics, "fem_enabled", False):
        return True

    if getattr(objectives, "fluids", None):
        return True

    objective_section = getattr(objectives, "objectives", None)
    if objective_section is None:
        return False

    if getattr(objective_section, "fluid_objectives", None):
        return True
    if getattr(objective_section, "stress_objectives", None):
        return True
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


def _sanitize_stress_summaries(
    summaries: list[StressSummary],
) -> list[StressSummary]:
    """Ensure stress summary payloads are JSON-compliant."""
    safe: list[StressSummary] = []
    for summary in summaries:
        safe.append(
            StressSummary(
                part_label=summary.part_label,
                max_von_mises_pa=_finite_float(summary.max_von_mises_pa),
                mean_von_mises_pa=_finite_float(summary.mean_von_mises_pa),
                safety_factor=_finite_float(summary.safety_factor),
                location_of_max=(
                    _finite_float(summary.location_of_max[0]),
                    _finite_float(summary.location_of_max[1]),
                    _finite_float(summary.location_of_max[2]),
                ),
                utilization_pct=_finite_float(summary.utilization_pct),
            )
        )
    return safe


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
    access_key = os.getenv("S3_ACCESS_KEY", os.getenv("AWS_ACCESS_KEY_ID"))
    secret_key = os.getenv("S3_SECRET_KEY", os.getenv("AWS_SECRET_ACCESS_KEY"))
    if not access_key or not secret_key:
        return None

    return S3Client(
        S3Config(
            endpoint_url=os.getenv("S3_ENDPOINT"),
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
    for axis, min_value, max_value in zip(("x", "y", "z"), box.min, box.max):
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
        if inner_box.min[i] < outer_box.min[i] or inner_box.max[i] > outer_box.max[i]:
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
                f"{inner_label} exceeds {outer_label} on axis {axis}",
            )
    return None


def _validate_benchmark_definition_consistency(
    objectives: BenchmarkDefinition,
) -> str | None:
    """Fail closed on invalid objective relationships and jitter ranges."""
    goal = objectives.objectives.goal_zone
    build_zone = objectives.objectives.build_zone
    simulation_bounds = objectives.simulation_bounds

    for label, box in (
        ("goal_zone", goal),
        ("build_zone", build_zone),
        ("simulation_bounds", simulation_bounds),
    ):
        box_error = _validate_bounding_box_order(label, box)
        if box_error is not None:
            return box_error

    for zone in objectives.objectives.forbid_zones:
        zone_error = _validate_bounding_box_order(f"forbid zone '{zone.name}'", zone)
        if zone_error is not None:
            return zone_error

        if _boxes_intersect(goal.min, goal.max, zone.min, zone.max):
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.CONTRADICTORY_CONSTRAINTS,
                f"goal_zone overlaps forbid zone '{zone.name}'",
            )

    if not _boxes_intersect(goal.min, goal.max, build_zone.min, build_zone.max):
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
            "goal_zone does not overlap build_zone",
        )

    jitter = objectives.payload.runtime_jitter
    start = objectives.payload.start_position
    jitter_error = _validate_non_negative_range("payload.runtime_jitter", jitter)
    if jitter_error is not None:
        return jitter_error

    radius_max = 0.0
    radius_range = objectives.payload.static_randomization.radius
    radius_error = _validate_non_negative_range(
        "payload.static_randomization.radius", radius_range
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

    if not _boxes_intersect(moved_min, moved_max, build_zone.min, build_zone.max):
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
            "payload runtime envelope does not overlap build_zone",
        )
    for i, axis in enumerate(("x", "y", "z")):
        if moved_min[i] < build_zone.min[i] or moved_max[i] > build_zone.max[i]:
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
                f"payload runtime envelope exceeds build_zone on axis {axis}",
            )

    for zone in objectives.objectives.forbid_zones:
        if _boxes_intersect(moved_min, moved_max, zone.min, zone.max):
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
        "build_zone",
        objectives.objectives.build_zone,
        "simulation_bounds",
        objectives.simulation_bounds,
    )


def _metadata_is_fixed(metadata: Any) -> bool:
    """Resolve fixed/static intent from PartMetadata/CompoundMetadata-like values."""
    if metadata is None:
        return False
    value = getattr(metadata, "is_fixed", None)
    if value is not None:
        return bool(value)
    if isinstance(metadata, dict):
        return bool(metadata.get("is_fixed", metadata.get("fixed", False)))
    return False


def _prefix_part_violation(label: str, violation: str) -> str:
    prefix = f"{label}: "
    return violation if violation.startswith(prefix) else f"{prefix}{violation}"


def _resolve_cots_catalog_item(
    part_id: str,
) -> tuple[Any, dict[str, str | None]] | None:
    from shared.cots.runtime import get_catalog_item_with_metadata

    return get_catalog_item_with_metadata(part_id)


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
        "CompoundMetadata(fixed=True) on the parent assembly does not make child "
        "parts static. Mark each static benchmark fixture with "
        "PartMetadata(..., fixed=True). Offending children: "
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


def _validate_moved_object_start_clearance(
    component: Compound, objectives: BenchmarkDefinition | None
) -> str | None:
    """Reject benchmark fixtures that overlap the runtime-spawned payload."""
    if objectives is None or getattr(objectives, "payload", None) is None:
        return None

    try:
        moved_object_geometry = build_moved_object_start_geometry(objectives.payload)
    except Exception as exc:
        return f"Unable to materialize payload startup geometry: {exc}"

    for index, solid in enumerate(component.solids()):
        label = getattr(solid, "label", None) or f"solid_{index}"
        try:
            intersection = moved_object_geometry.intersect(solid)
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
    reserved_prefixes = ("zone_", MOVED_OBJECT_SCENE_PREFIX)
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
                reserved_namespace = f"`{MOVED_OBJECT_SCENE_PREFIX}`"
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


def get_stress_report(
    part_label: str, output_dir: Path | None = None, session_id: str | None = None
) -> StressSummary | None:
    """Returns the worst-case stress summary for a simulated FEM part."""
    # Try to load from disk
    candidates = [Path("simulation_result.json")]
    working_dir = output_dir or Path(os.getenv("RENDERS_DIR", "./renders")).parent
    candidates.append(working_dir / "simulation_result.json")

    res = None
    for p in candidates:
        res = load_simulation_result(p)
        if res:
            break

    if res is None:
        logger.error(
            "get_stress_report_called_before_simulation", session_id=session_id
        )
        return None

    worst_summary = None
    min_sf = float("inf")

    for summary in res.stress_summaries:
        if summary.part_label == part_label and summary.safety_factor < min_sf:
            min_sf = summary.safety_factor
            worst_summary = summary

    if worst_summary:
        return worst_summary

    logger.error(
        "stress_report_part_not_found", part_label=part_label, session_id=session_id
    )
    return None


def preview_stress(
    _component: Compound,
    _view_angles: list[tuple[float, float]] | None = None,
    output_dir: Path | None = None,
    session_id: str | None = None,
) -> list[str]:
    """Renders the component with a von Mises stress heatmap overlay."""
    # Try to load from disk
    candidates = [Path("simulation_result.json")]
    working_dir = output_dir or Path(os.getenv("RENDERS_DIR", "./renders")).parent
    candidates.append(working_dir / "simulation_result.json")

    res = None
    for p in candidates:
        res = load_simulation_result(p)
        if res:
            break

    if res is None:
        logger.error("preview_stress_called_before_simulation", session_id=session_id)
        return []

    logger.info("rendering_stress_heatmaps", count=len(res.stress_fields))
    working_dir = output_dir or Path(os.getenv("RENDERS_DIR", "./renders")).parent
    stress_renders_dir = working_dir / "renders" / "stress"
    stress_renders_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = working_dir / "assets"

    render_paths = []
    for part_label, field_data in res.stress_fields.items():
        # T019: Use attribute access for StressFieldData model (WP2)
        nodes = getattr(field_data, "nodes", None) or field_data["nodes"]
        stress = getattr(field_data, "stress", None) or field_data["stress"]
        out_path = stress_renders_dir / f"stress_{part_label}.png"

        # Use the exported mesh for better VLM visibility if available
        mesh_path = assets_dir / f"{part_label}.obj"
        if not mesh_path.exists():
            mesh_path = None

        rendered = render_stress_heatmap_artifact(
            StressFieldData(nodes=nodes, stress=stress),
            output_name=out_path.name,
            session_id=session_id or "simulation",
            mesh_path=mesh_path,
        )
        out_path.write_bytes(rendered.image_bytes)
        render_paths.append(str(out_path))

    return render_paths


def define_fluid(
    name: str,
    shape_type: Literal["cylinder", "box", "sphere"],
    center: tuple[float, float, float],
    size: tuple[float, float, float] | None = None,
    radius: float | None = None,
    height: float | None = None,
    viscosity: float = 1.0,
    density: float = 1000,
    surface_tension: float = 0.07,
    color: tuple[int, int, int] = (0, 0, 200),
    output_dir: Path | None = None,
    session_id: str | None = None,
) -> FluidDefinition:
    """Defines a fluid type for use in the simulation."""
    props = FluidProperties(
        viscosity_cp=viscosity,
        density_kg_m3=density,
        surface_tension_n_m=surface_tension,
    )
    vol = FluidVolume(
        type=shape_type, center=center, size=size, radius=radius, height=height
    )
    fluid = FluidDefinition(
        fluid_id=name, properties=props, initial_volume=vol, color=color
    )

    working_dir = output_dir or Path(os.getenv("RENDERS_DIR", "./renders")).parent
    obj_path = working_dir / "benchmark_definition.yaml"

    if obj_path.exists():
        objs = _load_valid_benchmark_definition(
            obj_path.read_text(encoding="utf-8"),
            session_id=session_id,
        )
        updated = False
        for i, f in enumerate(objs.fluids):
            if f.fluid_id == name:
                objs.fluids[i] = fluid
                updated = True
                break
        if not updated:
            objs.fluids.append(fluid)
        obj_path.write_text(yaml.dump(objs.model_dump(mode="json")), encoding="utf-8")
    else:
        logger.error(
            "define_fluid_objectives_not_found",
            path=str(obj_path),
            session_id=session_id,
        )

    return fluid


def set_soft_mesh(
    part_id: str, enabled: bool = True, output_dir: Path | None = None
) -> bool:
    """Explicitly enables FEM for the scene and marks intent for a specific part."""
    working_dir = output_dir or Path(os.getenv("RENDERS_DIR", "./renders")).parent
    obj_path = working_dir / "benchmark_definition.yaml"

    if obj_path.exists():
        try:
            objs = _load_valid_benchmark_definition(
                obj_path.read_text(encoding="utf-8")
            )
            objs.physics.fem_enabled = enabled
            if enabled:
                # FEM currently requires Genesis backend
                objs.physics.backend = SimulatorBackendType.GENESIS.value
            obj_path.write_text(
                yaml.dump(objs.model_dump(mode="json")), encoding="utf-8"
            )
            logger.info("set_soft_mesh_enabled", part_id=part_id, fem_enabled=enabled)
            return True
        except Exception as e:
            logger.warning("set_soft_mesh_failed", error=str(e))
            return False
    return False


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
    electronics: ElectronicsSection | None = None,
    cots_parts: list[CotsPartEstimate] | None = None,
    manufacturing_config: ManufacturingConfig | None = None,
    session_id: str | None = None,
    quantity: int = 1,
) -> tuple[float, float]:
    """
    Calculate total cost and weight of the assembly including electronics and COTS.
    """
    config = manufacturing_config or load_config()
    total_cost = 0.0
    total_weight = 0.0
    observed_cots_counts: dict[str, int] = {}

    # 1. Manufactured parts
    children = getattr(component, "children", [])
    if not children:
        children = [component]

    for child in children:
        metadata = getattr(child, "metadata", None)
        if not metadata:
            continue

        cots_id = _metadata_cots_id(metadata)
        if cots_id:
            part_label = getattr(child, "label", "unknown")
            lookup = _resolve_cots_catalog_item(cots_id)
            if lookup is None:
                raise ValueError(f"{part_label}: unresolved COTS part_id '{cots_id}'")

            catalog_item, catalog_metadata = lookup
            catalog_details = catalog_item.metadata or {}
            total_cost += catalog_item.unit_cost
            total_weight += catalog_item.weight_g
            observed_cots_counts[cots_id] = observed_cots_counts.get(cots_id, 0) + 1

            manufacturer = getattr(metadata, "manufacturer", None)
            catalog_manufacturer = catalog_details.get("manufacturer")
            if (
                manufacturer
                and catalog_manufacturer
                and manufacturer != catalog_manufacturer
            ):
                raise ValueError(
                    f"{part_label}: manufacturer '{manufacturer}' does not match catalog manufacturer '{catalog_manufacturer}'"
                )

            for field_name, observed in (
                ("catalog_version", getattr(metadata, "catalog_version", None)),
                ("bd_warehouse_commit", getattr(metadata, "bd_warehouse_commit", None)),
                ("catalog_snapshot_id", getattr(metadata, "catalog_snapshot_id", None)),
                ("generated_at", getattr(metadata, "generated_at", None)),
            ):
                if observed is None:
                    continue
                expected = catalog_metadata.get(field_name)
                if expected is not None and observed != expected:
                    raise ValueError(
                        f"{part_label}: {field_name} '{observed}' does not match catalog value '{expected}'"
                    )
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

    # 2. Electronics and COTS parts
    if electronics:
        for comp in electronics.components:
            if comp.type == ElectronicComponentType.POWER_SUPPLY and comp.cots_part_id:
                from shared.cots.parts.electronics import PowerSupply

                try:
                    psu = PowerSupply(size=comp.cots_part_id)
                    total_cost += getattr(psu, "price", 0.0)
                    total_weight += getattr(psu, "weight_g", 0.0)
                except Exception as e:
                    logger.error(
                        "failed_to_price_psu",
                        cots_id=comp.cots_part_id,
                        error=str(e),
                        session_id=session_id,
                    )
                    raise ValueError(
                        f"Failed to resolve power supply COTS part_id '{comp.cots_part_id}'"
                    ) from e
            elif comp.type == ElectronicComponentType.RELAY and comp.cots_part_id:
                from shared.cots.parts.electronics import ElectronicRelay

                try:
                    relay = ElectronicRelay(size=comp.cots_part_id)
                    total_cost += getattr(relay, "price", 0.0)
                    total_weight += getattr(relay, "weight_g", 0.0)
                except Exception as e:
                    logger.error(
                        "failed_to_price_relay",
                        cots_id=comp.cots_part_id,
                        error=str(e),
                        session_id=session_id,
                    )
                    raise ValueError(
                        f"Failed to resolve relay COTS part_id '{comp.cots_part_id}'"
                    ) from e
            elif comp.type == ElectronicComponentType.SWITCH and comp.cots_part_id:
                from shared.cots.parts.electronics import Switch

                try:
                    sw = Switch(size=comp.cots_part_id)
                    total_cost += getattr(sw, "price", 0.0)
                    total_weight += getattr(sw, "weight_g", 0.0)
                except Exception as e:
                    logger.error(
                        "failed_to_price_switch",
                        cots_id=comp.cots_part_id,
                        error=str(e),
                        session_id=session_id,
                    )
                    raise ValueError(
                        f"Failed to resolve switch COTS part_id '{comp.cots_part_id}'"
                    ) from e
            elif comp.type == ElectronicComponentType.CONNECTOR and comp.cots_part_id:
                from shared.cots.parts.electronics import Connector

                try:
                    conn = Connector(size=comp.cots_part_id)
                    total_cost += getattr(conn, "price", 0.0)
                    total_weight += getattr(conn, "weight_g", 0.0)
                except Exception as e:
                    logger.error(
                        "failed_to_price_connector",
                        cots_id=comp.cots_part_id,
                        error=str(e),
                        session_id=session_id,
                    )
                    raise ValueError(
                        f"Failed to resolve connector COTS part_id '{comp.cots_part_id}'"
                    ) from e
            elif comp.type == ElectronicComponentType.MOTOR and comp.cots_part_id:
                from shared.cots.parts.motors import ServoMotor

                try:
                    motor = ServoMotor(size=comp.cots_part_id)
                    total_cost += getattr(motor, "price", 0.0)
                    total_weight += getattr(motor, "weight_g", 0.0)
                except Exception as e:
                    logger.error(
                        "failed_to_price_motor",
                        cots_id=comp.cots_part_id,
                        error=str(e),
                        session_id=session_id,
                    )
                    raise ValueError(
                        f"Failed to resolve motor COTS part_id '{comp.cots_part_id}'"
                    ) from e

        for wire in electronics.wiring:
            from shared.wire_utils import get_awg_properties

            length_m = wire.length_mm / 1000.0
            props = get_awg_properties(wire.gauge_awg)
            # Estimate weight based on copper density and diameter
            # Area (mm2) = pi * (d/2)^2
            import math

            area_mm2 = math.pi * (props["diameter_mm"] / 2.0) ** 2
            # Weight (g/m) = Area (mm2) * Density (8.96 g/cm3)
            # 1 mm2 * 1 m = 1000 mm3 = 1 cm3
            weight_g_m = area_mm2 * 8.96

            # Use cost from config if available, otherwise fallback to reasonable default
            cost_per_m = 0.5  # default
            if config.wires:
                awg_key = f"awg{wire.gauge_awg}"
                if hasattr(config.wires, awg_key):
                    cost_per_m = getattr(config.wires, awg_key).cost_per_m
                elif isinstance(config.wires, dict) and awg_key in config.wires:
                    cost_per_m = config.wires[awg_key].get("cost_per_m", 0.5)

            total_cost += length_m * cost_per_m
            total_weight += length_m * weight_g_m

    # 3. Generic COTS parts from assembly definition
    if cots_parts:
        declared_cots_counts: dict[str, int] = {}
        for p in cots_parts:
            declared_cots_counts[p.part_id] = (
                declared_cots_counts.get(p.part_id, 0) + p.quantity
            )
            lookup = _resolve_cots_catalog_item(p.part_id)
            if lookup is None:
                raise ValueError(f"Unknown catalog COTS part_id '{p.part_id}'")

            catalog_item, catalog_metadata = lookup
            catalog_details = catalog_item.metadata or {}
            total_cost += catalog_item.unit_cost * p.quantity
            total_weight += catalog_item.weight_g * p.quantity

            manufacturer = catalog_details.get("manufacturer")
            if manufacturer and p.manufacturer != manufacturer:
                raise ValueError(
                    "COTS manufacturer mismatch for part_id "
                    f"'{p.part_id}': planner manufacturer '{p.manufacturer}' "
                    f"does not match catalog manufacturer '{manufacturer}'"
                )

            if (
                p.weight_g is not None
                and abs(p.weight_g - catalog_item.weight_g) > 1e-6
            ):
                raise ValueError(
                    "COTS weight mismatch for part_id "
                    f"'{p.part_id}': planner weight {p.weight_g}g does not match "
                    f"catalog weight {catalog_item.weight_g}g"
                )

        missing_declared_cots_parts = [
            f"'{part_id}' x{quantity}"
            for part_id, quantity in declared_cots_counts.items()
            if observed_cots_counts.get(part_id, 0) < quantity
        ]
        if missing_declared_cots_parts:
            raise ValueError(
                "Declared COTS part(s) were not instantiated in authored geometry: "
                + ", ".join(missing_declared_cots_parts)
            )
        provenance_pairs = (
            (
                "catalog_version",
                p.catalog_version,
                catalog_metadata.get("catalog_version"),
            ),
            (
                "bd_warehouse_commit",
                p.bd_warehouse_commit,
                catalog_metadata.get("bd_warehouse_commit"),
            ),
            (
                "catalog_snapshot_id",
                p.catalog_snapshot_id,
                catalog_metadata.get("catalog_snapshot_id"),
            ),
            ("generated_at", p.generated_at, catalog_metadata.get("generated_at")),
        )
        for field_name, observed, expected in provenance_pairs:
            if observed is not None and expected is not None and observed != expected:
                raise ValueError(
                    f"COTS provenance mismatch for part_id '{p.part_id}': "
                    f"{field_name} '{observed}' does not match catalog '{expected}'"
                )

    if assembly_definition is not None:
        total_cost += calculate_benchmark_drilling_cost(assembly_definition, config)

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
    particle_budget: int | None = None,
) -> SimulationResult:
    """Serializable entry point for ProcessPoolExecutor."""
    # Ensure events are written to the session's event log
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
    return simulate(
        component=component,
        output_dir=output_dir,
        smoke_test_mode=smoke_test_mode,
        backend=backend,
        session_id=session_id,
        episode_id=episode_id,
        stream_render_frames=stream_render_frames,
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
        script_path=script_path,
        script_content=script_content,
    )
    fem_valid, fem_message = validate_fem_manufacturability(
        component,
        Path(session_root),
        session_id=session_id,
    )
    if is_valid and not fem_valid:
        is_valid = False
        message = (
            f"{message}; {fem_message}" if message and fem_message else fem_message
        )

    return is_valid, message


def simulate(
    component: Compound,
    output_dir: Path | None = None,
    fem_enabled: bool | None = None,
    particle_budget: int | None = None,
    smoke_test_mode: bool | None = None,
    backend: SimulatorBackendType | None = None,
    session_id: str | None = None,
    episode_id: str | None = None,
    stream_render_frames: bool = False,
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
        fem_enabled=fem_enabled,
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
                fem_valid, fem_message = validate_fem_manufacturability(
                    component,
                    working_dir,
                    session_id=session_id,
                )
                if not fem_valid:
                    return SimulationResult(
                        success=False,
                        summary=fem_message or "Material validation failed",
                        failure=SimulationFailure(
                            reason=FailureReason.VALIDATION_FAILED,
                            detail=fem_message or "Material validation failed",
                        ),
                        confidence=SimulationConfidence.HIGH,
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
    moving_parts = assembly_definition.moving_parts if assembly_definition else []
    electronics = assembly_definition.electronics if assembly_definition else None
    manufactured_part_labels = (
        {part.part_name for part in assembly_definition.manufactured_parts}
        if assembly_definition
        else set()
    )

    # T021: Proactive electronics validation before starting expensive physics backend (INT-120)
    if electronics:
        from .electronics import build_circuit_from_section, validate_circuit

        try:
            circuit = build_circuit_from_section(electronics)
            cv_res = validate_circuit(
                circuit, psu_config=electronics.power_supply, section=electronics
            )
            if not cv_res.valid:
                error_msg = "; ".join(cv_res.errors)
                logger.error(
                    "electronics_validation_failed_gate",
                    errors=error_msg,
                    session_id=session_id,
                )
                return SimulationResult(
                    success=False,
                    summary=error_msg,
                    failure=SimulationFailure(
                        reason=FailureReason.VALIDATION_FAILED,
                        detail=error_msg,
                    ),
                    confidence=SimulationConfidence.HIGH,
                )
        except Exception as e:
            logger.error(
                "electronics_pre_validation_skipped",
                error=str(e),
                session_id=session_id,
            )

    scene_path = builder.build_from_assembly(
        component,
        objectives=objectives,
        moving_parts=moving_parts,
        electronics=electronics,
        smoke_test_mode=smoke_test_mode,
    )

    # Fast preflight: if a fluid spawn volume intersects an electronics part's bounding
    # box, classify as electronics fluid damage immediately.
    if objectives and objectives.fluids and electronics:
        try:
            children = getattr(component, "children", []) or [component]
            by_label = {
                getattr(child, "label", ""): child
                for child in children
                if getattr(child, "label", None)
            }

            def _point_in_bbox(point, bb) -> bool:
                return (
                    bb.min.X <= point[0] <= bb.max.X
                    and bb.min.Y <= point[1] <= bb.max.Y
                    and bb.min.Z <= point[2] <= bb.max.Z
                )

            for fluid in objectives.fluids:
                center = fluid.initial_volume.center
                for ecomp in electronics.components:
                    part_ref = ecomp.assembly_part_ref or ecomp.component_id
                    part = by_label.get(part_ref)
                    if not part:
                        continue
                    bb = part.bounding_box()
                    if _point_in_bbox(center, bb):
                        return SimulationResult(
                            success=False,
                            summary="Electronics fluid damage detected.",
                            failure=SimulationFailure(
                                reason=FailureReason.ELECTRONICS_FLUID_DAMAGE,
                                detail=part_ref,
                            ),
                            confidence=SimulationConfidence.HIGH,
                        )
        except Exception as e:
            logger.error(
                "fluid_electronics_preflight_skipped",
                error=str(e),
                session_id=session_id,
            )

    loop = SimulationLoop(
        str(scene_path),
        component=component,
        backend_type=backend_type,
        electronics=electronics,
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
    if assembly_definition and assembly_definition.moving_parts:
        try:
            from worker_heavy.utils.controllers import sinusoidal

            for part in assembly_definition.moving_parts:
                if part.control:
                    if part.control.mode == MotorControlMode.SINUSOIDAL:
                        dynamic_controllers[part.part_name] = lambda t, p=part.control: (
                            sinusoidal(t, p.speed, p.frequency or 1.0)
                        )
                    elif part.control.mode == MotorControlMode.CONSTANT:
                        control_inputs[part.part_name] = part.control.speed
                    elif part.control.mode == MotorControlMode.ON_OFF:
                        # T019: Handle ON_OFF mode using frequency toggle
                        freq = part.control.frequency or 1.0
                        period = 1.0 / freq
                        dynamic_controllers[part.part_name] = (
                            lambda t, p=part.control, per=period: (
                                p.speed if (t % per) < (per / 2) else 0.0
                            )
                        )
        except Exception as e:
            logger.warning("failed_to_load_controllers", error=str(e))

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
                electronics=electronics,
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
                electronics=electronics,
                cots_parts=(
                    assembly_definition.cots_parts if assembly_definition else None
                ),
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
            stress_summaries=_sanitize_stress_summaries(metrics.stress_summaries),
            stress_fields=metrics.stress_fields,
            fluid_metrics=getattr(metrics, "fluid_metrics", []),
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

        # T023: Generate stress heatmaps and append to render_paths
        if metrics.stress_fields:
            # Save first so preview_stress can load it
            try:
                save_simulation_result(result, working_dir / "simulation_result.json")
            except Exception as e:
                logger.error(
                    "failed_to_save_simulation_result_pre_preview",
                    error=str(e),
                    session_id=session_id,
                )

            stress_renders = preview_stress(component, output_dir=working_dir)
            stress_renders = _workspace_relative_render_paths(
                stress_renders, working_dir
            )
            result.render_paths.extend(stress_renders)

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
    script_path: str | Path | None = None,
    script_content: str | None = None,
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
    label_contract_error = _validate_unique_top_level_labels(component)
    if label_contract_error:
        return False, label_contract_error

    solids = component.solids()
    if len(solids) > 1:
        for i in range(len(solids)):
            for j in range(i + 1, len(solids)):
                label_i = getattr(solids[i], "label", None) or f"unlabeled_solid_{i}"
                label_j = (
                    getattr(solids[j], "label", None) or f"unlabeled_solid_{j}"
                )  # human note: I've changed it to `unlabeled_solid_{i} so that there is no confusion from agent that they forgot to label it. Anyway, if it fails anywhere, just update it.
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
                    moved_object_clearance_error = (
                        _validate_moved_object_start_clearance(component, obj_model)
                    )
                    if moved_object_clearance_error:
                        return False, moved_object_clearance_error
                    effective_build_zone = obj_model.objectives.build_zone.model_dump()
            except Exception:
                pass

    if effective_build_zone:
        b_min = effective_build_zone.get("min", [-1000, -1000, -1000])
        b_max = effective_build_zone.get("max", [1000, 1000, 1000])
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
                f"bbox {bbox} outside build_zone {effective_build_zone}"
                f"{offender_text}",
            )
    else:
        if bbox.size.X > 1000.0 or bbox.size.Y > 1000.0 or bbox.size.Z > 1000.0:
            return (
                False,
                f"Boundary constraint violation: size {bbox.size} exceeds 1000.0",
            )

    # Check wire clearance if assembly definition is available
    if output_dir:
        asm_path = _find_workspace_assembly_definition(
            output_dir, prefer_benchmark=True
        )
        if asm_path is not None:
            try:
                data = yaml.safe_load(asm_path.read_text(encoding="utf-8"))
                if data and "electronics" in data and "wiring" in data["electronics"]:
                    wires_data = data["electronics"]["wiring"]

                    wire_errors = []
                    total_length = 0.0
                    wire_count = 0

                    for w in wires_data:
                        wire_id = w.get("wire_id", "unknown")
                        waypoints = w.get("waypoints")
                        routed_in_3d = w.get("routed_in_3d", False)

                        if not waypoints or len(waypoints) < 2:
                            continue

                        # Convert to list of tuples if needed
                        pts = []
                        for p in waypoints:
                            if isinstance(p, (list, tuple)) and len(p) >= 3:
                                pts.append((float(p[0]), float(p[1]), float(p[2])))

                        if len(pts) >= 2:
                            wire_count += 1
                            # Calculate length for observability
                            total_length += calculate_path_length(
                                pts, use_spline=routed_in_3d
                            )

                            if routed_in_3d:
                                if not check_wire_clearance(
                                    pts,
                                    component,
                                    clearance_mm=2.0,
                                    session_id=session_id,
                                ):
                                    wire_errors.append(
                                        f"Wire clearance violation: {wire_id}"
                                    )

                    # Emit observability event for validation result
                    if wire_count > 0:
                        emit_event(
                            WireRoutingEvent(
                                wire_count=wire_count,
                                total_length_mm=total_length,
                                clearance_passed=(len(wire_errors) == 0),
                                errors=wire_errors,
                            )
                        )

                    if wire_errors:
                        return (False, "; ".join(wire_errors))

            except Exception as e:
                logger.warning(
                    "wire_clearance_check_failed_during_validate",
                    error=str(e),
                    session_id=session_id,
                )

    drafting_gate_error = _validate_drafting_preview_gate(
        working_root=working_root,
        script_path=script_path,
        session_id=session_id,
    )
    if drafting_gate_error:
        return False, drafting_gate_error

    # Validation is intentionally geometry-only. Preview evidence belongs to the
    # explicit preview path, not the default validate() contract.
    return True, None


def validate_fem_manufacturability(
    component: Compound, session_root: Path, session_id: str | None = None
) -> tuple[bool, str | None]:
    """Check if FEM material validation is required and if it passes."""
    obj_path = session_root / "benchmark_definition.yaml"
    if not obj_path.exists():
        return True, None

    try:
        content = obj_path.read_text(encoding="utf-8")
        if "[TEMPLATE]" in content:
            return True, None

        objs = _load_valid_benchmark_definition(content, session_id=session_id)
        if objs.physics and objs.physics.fem_enabled:
            config = load_config()
            custom_config_path = session_root / "manufacturing_config.yaml"
            if custom_config_path.exists():
                config = load_merged_config(custom_config_path)

            from shared.workers.workbench_models import ManufacturingMethod

            assembly_definition_path = _find_workspace_assembly_definition(
                session_root, prefer_benchmark=True
            )
            manufactured_labels: set[str] = set()
            assembly: AssemblyDefinition | None = None
            if assembly_definition_path is not None:
                assembly_data = yaml.safe_load(
                    assembly_definition_path.read_text(encoding="utf-8")
                )
                assembly = AssemblyDefinition(**assembly_data)
                manufactured_labels = {
                    part.part_name for part in assembly.manufactured_parts
                }
            requested_quantity = resolve_requested_quantity(
                benchmark_definition=objs,
            )
            val_report = validate_and_price_assembly(
                component,
                config,
                assembly_definition=assembly,
                part_labels=manufactured_labels or None,
                fem_required=True,
                session_id=session_id,
                quantity=requested_quantity,
                default_method=ManufacturingMethod.CNC,
            )
            if not val_report.is_manufacturable:
                msg = "Material validation failed: " + "; ".join(
                    map(str, val_report.violations)
                )
                return False, msg
    except Exception as e:
        logger.warning(
            "fem_manufacturability_check_failed", error=str(e), session_id=session_id
        )
        return False, f"FEM manufacturability check failed: {e!s}"

    return True, None
