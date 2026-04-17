import asyncio
import base64
import math
import os
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
import structlog
from build123d import Align, Box, Compound, Location, Part
from pydantic import BaseModel

from shared.current_role import current_role_agent_name
from shared.enums import AgentName
from shared.models.schemas import BenchmarkDefinition, CompoundMetadata, PartMetadata
from shared.rendering import (
    bundle_workspace_base64,
    export_preview_scene_bundle,
    materialize_preview_response,
    render_preview,
    select_single_preview_render_subdir,
)
from shared.script_contracts import (
    authored_script_path_for_agent,
    role_family_for_agent,
)
from shared.simulation.schemas import get_default_simulator_backend
from shared.workers.schema import (
    BenchmarkToolResponse,
    PlanRefusal,
    PreviewDesignRequest,
    PreviewDesignResponse,
    PreviewRenderingType,
)

logger = structlog.get_logger(__name__)
SCRIPT_IMPORT_MODE_ENV = "PROBLEMOLOGIST_SCRIPT_IMPORT_MODE"
SCRIPT_IMPORT_DEFERRED_MESSAGE = "Deferred during control-plane script import."
CONTROLLER_URL_ENV = "CONTROLLER_URL"
AGENT_NAME_ENV = "AGENT_NAME"

# --- Proxy Logic ---


def _call_heavy_worker(endpoint: str, payload: dict | BaseModel) -> dict:
    heavy_url = os.getenv("WORKER_HEAVY_URL", "http://worker-heavy:8002")
    worker_light_url = _worker_light_base_url()
    session_id = os.getenv("SESSION_ID", "default")
    json_payload = payload.model_dump() if isinstance(payload, BaseModel) else payload
    agent_role = str(json_payload.get("agent_role") or _script_agent_role())
    stage = str(json_payload.get("reviewer_stage") or agent_role)

    if worker_light_url and "bundle_base64" not in json_payload:
        try:
            with httpx.Client(timeout=60.0) as client:
                bundle_resp = client.post(
                    f"{worker_light_url}/fs/bundle",
                    headers={"X-Session-ID": session_id},
                )
                bundle_resp.raise_for_status()
                json_payload["bundle_base64"] = base64.b64encode(
                    bundle_resp.content
                ).decode("utf-8")
        except Exception as e:
            logger.warning(
                "session_bundle_collection_failed",
                error=str(e),
                session_id=session_id,
            )

    normalized_endpoint = endpoint.lstrip("/")
    if normalized_endpoint.startswith(("benchmark/", "engineering/")):
        url = f"{heavy_url.rstrip('/')}/{normalized_endpoint}"
    else:
        role_family = role_family_for_agent(agent_role) or "benchmark"
        url = f"{heavy_url.rstrip('/')}/{role_family}/{normalized_endpoint}"
    headers = {
        "X-Session-ID": session_id,
        "X-Agent-Role": agent_role,
        "X-Stage": stage,
    }
    if json_payload.get("reviewer_stage") is not None:
        headers["X-Reviewer-Stage"] = str(json_payload["reviewer_stage"])

    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(url, json=json_payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Heavy worker call failed: {e}")
        return {"success": False, "message": str(e)}


def _call_worker_light(endpoint: str, payload: dict | BaseModel) -> dict:
    light_url = _worker_light_base_url()
    session_id = os.getenv("SESSION_ID", "default")
    json_payload = payload.model_dump() if isinstance(payload, BaseModel) else payload
    agent_role = str(json_payload.get("agent_role") or _script_agent_role())
    stage = str(json_payload.get("reviewer_stage") or agent_role)

    if not light_url:
        error_message = "worker-light URL is not configured"
        logger.error(
            "worker_light_call_failed",
            error=error_message,
            session_id=session_id,
        )
        return {"success": False, "message": error_message}

    headers = {
        "X-Session-ID": session_id,
        "X-Agent-Role": agent_role,
        "X-Stage": stage,
    }
    if json_payload.get("reviewer_stage") is not None:
        headers["X-Reviewer-Stage"] = str(json_payload["reviewer_stage"])

    url = f"{light_url.rstrip('/')}/{endpoint.lstrip('/')}"
    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(url, json=json_payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Worker-light call failed: {e}")
        return {"success": False, "message": str(e)}


def _controller_base_url() -> str | None:
    url = os.getenv(CONTROLLER_URL_ENV)
    if not url:
        return None
    return url.rstrip("/")


def _worker_light_base_url() -> str | None:
    url = os.getenv("WORKER_LIGHT_URL")
    if not url:
        return None
    return url.rstrip("/")


def _script_agent_role() -> str:
    return current_role_agent_name(_workspace_root()).value


def _script_agent_family() -> str:
    family = role_family_for_agent(_script_agent_role())
    if family is None:
        raise ValueError(
            f"Unsupported current role for submission helpers: {_script_agent_role()}"
        )
    return family


def _workspace_script_path() -> str:
    current_role = _script_agent_role()
    script_path = authored_script_path_for_agent(current_role)
    if script_path.as_posix() == "script.py":
        raise ValueError(
            f"Unsupported current role for script-path resolution: {current_role}"
        )
    return script_path.as_posix()


def _workspace_endpoint_prefix() -> str:
    return _script_agent_family()


def _workspace_bundle_base64() -> str:
    return bundle_workspace_base64(_workspace_root())


def _workspace_root() -> Path:
    sessions_dir = os.getenv("WORKER_SESSIONS_DIR")
    session_id = os.getenv("SESSION_ID")
    if sessions_dir and session_id:
        return Path(sessions_dir) / session_id
    return Path.cwd()


def _preview_output_dir() -> Path:
    return (
        _workspace_root()
        / "renders"
        / select_single_preview_render_subdir(
            _workspace_root(), agent_role=_script_agent_role()
        )
    )


def _workspace_benchmark_definition_path() -> Path:
    return _workspace_root() / "benchmark_definition.yaml"


def _load_workspace_benchmark_definition() -> BenchmarkDefinition:
    benchmark_definition_path = _workspace_benchmark_definition_path()
    if not benchmark_definition_path.exists():
        raise FileNotFoundError(
            f"benchmark_definition.yaml not found at {benchmark_definition_path}"
        )

    from worker_heavy.utils.file_validation import validate_benchmark_definition_yaml

    is_valid, benchmark_or_errors = validate_benchmark_definition_yaml(
        benchmark_definition_path.read_text(encoding="utf-8"),
        session_id=os.getenv("SESSION_ID"),
    )
    if not is_valid:
        raise ValueError("; ".join(benchmark_or_errors))
    return benchmark_or_errors


def _build_objective_zone(label: str, bounds_min, bounds_max):
    size_x = float(bounds_max[0]) - float(bounds_min[0])
    size_y = float(bounds_max[1]) - float(bounds_min[1])
    size_z = float(bounds_max[2]) - float(bounds_min[2])
    center = (
        (float(bounds_min[0]) + float(bounds_max[0])) / 2.0,
        (float(bounds_min[1]) + float(bounds_max[1])) / 2.0,
        (float(bounds_min[2]) + float(bounds_max[2])) / 2.0,
    )
    zone = Box(
        max(size_x, 0.0),
        max(size_y, 0.0),
        max(size_z, 0.0),
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ).move(Location(center))
    zone.label = label
    zone.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return zone


def objectives_geometry() -> Compound:
    """Materialize benchmark objective overlay geometry for the current workspace."""

    benchmark_definition = _load_workspace_benchmark_definition()
    objectives = benchmark_definition.objectives
    children = []

    goal_zone = objectives.goal_zone_mm
    if goal_zone is not None:
        children.append(
            _build_objective_zone("zone_goal", goal_zone.min_mm, goal_zone.max_mm)
        )

    for index, forbid_zone in enumerate(objectives.forbid_zones or []):
        zone_name = str(forbid_zone.name).strip() or f"forbid_{index}"
        children.append(
            _build_objective_zone(
                f"zone_forbid_{index}_{zone_name}",
                forbid_zone.min_mm,
                forbid_zone.max_mm,
            )
        )

    build_zone = objectives.build_zone_mm
    if build_zone is not None:
        children.append(
            _build_objective_zone("zone_build", build_zone.min_mm, build_zone.max_mm)
        )

    overlay = Compound(children=children) if children else Compound()
    overlay.label = "benchmark_objectives"
    overlay.metadata = CompoundMetadata()
    return overlay


def _default_reviewer_stage() -> AgentName:
    role_value = _script_agent_role()
    role_to_stage: dict[str, AgentName] = {
        AgentName.BENCHMARK_CODER.value: AgentName.BENCHMARK_REVIEWER,
        AgentName.BENCHMARK_REVIEWER.value: AgentName.BENCHMARK_REVIEWER,
        AgentName.ENGINEER_CODER.value: AgentName.ENGINEER_EXECUTION_REVIEWER,
        AgentName.ENGINEER_EXECUTION_REVIEWER.value: AgentName.ENGINEER_EXECUTION_REVIEWER,
        AgentName.BENCHMARK_PLANNER.value: AgentName.BENCHMARK_REVIEWER,
        AgentName.ENGINEER_PLANNER.value: AgentName.ENGINEER_EXECUTION_REVIEWER,
        AgentName.ENGINEER_PLAN_REVIEWER.value: AgentName.ENGINEER_EXECUTION_REVIEWER,
        AgentName.BENCHMARK_PLAN_REVIEWER.value: AgentName.BENCHMARK_REVIEWER,
    }
    if role_value not in role_to_stage:
        raise ValueError(
            f"Unsupported current role for submit_for_review: {role_value}"
        )
    return role_to_stage[role_value]


def _call_controller_script_tool(action: str, payload: dict[str, Any]) -> dict | None:
    controller_url = _controller_base_url()
    if not controller_url:
        return None
    session_id = os.getenv("SESSION_ID", "default")
    agent_role = str(payload.get("agent_role") or _script_agent_role())
    stage = str(payload.get("reviewer_stage") or agent_role)
    url = f"{controller_url}/api/script-tools/{action.lstrip('/')}"
    headers = {
        "X-Session-ID": session_id,
        "X-Agent-Role": agent_role,
        "X-Stage": stage,
    }
    if payload.get("reviewer_stage") is not None:
        headers["X-Reviewer-Stage"] = str(payload["reviewer_stage"])
    try:
        with httpx.Client(timeout=1000.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(
            "controller_script_tool_failed",
            action=action,
            error=str(e),
            session_id=session_id,
        )
        raise


def _call_controller_preview_tool(
    payload: PreviewDesignRequest,
) -> PreviewDesignResponse | None:
    controller_url = _controller_base_url()
    if not controller_url:
        return None
    session_id = os.getenv("SESSION_ID", "default")
    agent_role = _script_agent_role()
    url = f"{controller_url}/api/script-tools/preview"
    headers = {
        "X-Session-ID": session_id,
        "X-Agent-Role": agent_role,
        "X-Stage": agent_role,
    }
    try:
        with httpx.Client(timeout=1000.0) as client:
            resp = client.post(
                url, json=payload.model_dump(mode="json"), headers=headers
            )
            resp.raise_for_status()
            return PreviewDesignResponse.model_validate(resp.json())
    except httpx.RequestError as exc:
        logger.warning(
            "controller_preview_tool_unavailable",
            error=str(exc),
            session_id=session_id,
        )
        return None
    except Exception as exc:
        logger.error(
            "controller_preview_tool_failed",
            error=str(exc),
            session_id=session_id,
        )
        raise


def _call_worker_light_preview(
    payload: PreviewDesignRequest, *, session_id: str | None
) -> PreviewDesignResponse | None:
    worker_light_url = _worker_light_base_url()
    if not worker_light_url:
        return None

    agent_role = _script_agent_role()
    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                f"{worker_light_url}/benchmark/render_cad",
                json=payload.model_dump(mode="json"),
                headers={
                    "X-Session-ID": session_id or "default",
                    "X-Agent-Role": agent_role,
                    "X-Stage": agent_role,
                },
            )
            resp.raise_for_status()
            return PreviewDesignResponse.model_validate(resp.json())
    except httpx.RequestError as exc:
        logger.warning(
            "worker_light_preview_unavailable",
            error=str(exc),
            session_id=session_id,
        )
        return None
    except Exception as exc:
        logger.error(
            "worker_light_preview_failed",
            error=str(exc),
            session_id=session_id,
        )
        raise


# --- Agent Utils ---


def _is_script_import_mode() -> bool:
    return os.getenv(SCRIPT_IMPORT_MODE_ENV) == "1"


def _normalize_signature_value(value: Any, *, depth: int = 0) -> Any:
    """Normalize build123d objects into a tolerance-aware signature."""
    if depth > 6:
        return repr(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, float):
        return round(value, 3) if math.isfinite(value) else repr(value)
    if all(hasattr(value, attr) for attr in ("X", "Y", "Z")):
        return {
            "x": round(float(value.X), 3),
            "y": round(float(value.Y), 3),
            "z": round(float(value.Z), 3),
        }
    if all(hasattr(value, attr) for attr in ("x", "y", "z")):
        return {
            "x": round(float(value.x), 3),
            "y": round(float(value.y), 3),
            "z": round(float(value.z), 3),
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_signature_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_signature_value(item, depth=depth + 1)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if hasattr(value, "__dict__"):
        data: dict[str, Any] = {"__type__": type(value).__name__}
        for key, item in vars(value).items():
            if key.startswith("_") or key in {"wrapped", "topo_parent", "joints"}:
                continue
            if callable(item):
                continue
            data[key] = _normalize_signature_value(item, depth=depth + 1)
        return data
    return repr(value)


def _component_semantic_signature(component: Any) -> dict[str, Any]:
    """Build a semantic signature for a build123d component."""
    signature: dict[str, Any] = {
        "type": type(component).__name__,
        "label": _normalize_signature_value(getattr(component, "label", None)),
    }

    public_fields = {
        key: _normalize_signature_value(value)
        for key, value in vars(component).items()
        if not key.startswith("_")
        and key not in {"wrapped", "topo_parent", "joints"}
        and not callable(value)
    }
    if public_fields:
        signature["fields"] = public_fields

    children = getattr(component, "children", ())
    if isinstance(children, tuple) and children:
        signature["children"] = [
            _component_semantic_signature(child) for child in children
        ]

    metrics: dict[str, Any] = {}
    for metric_name, attr_name in (
        ("solids_count", "solids"),
        ("faces_count", "faces"),
        ("edges_count", "edges"),
        ("wires_count", "wires"),
    ):
        if hasattr(component, attr_name):
            try:
                metrics[metric_name] = len(list(getattr(component, attr_name)()))
            except Exception:
                continue

    if hasattr(component, "bounding_box"):
        try:
            metrics["bbox"] = _normalize_signature_value(component.bounding_box())
        except Exception:
            pass

    if hasattr(component, "volume"):
        try:
            metrics["volume"] = _normalize_signature_value(component.volume)
        except Exception:
            pass

    if metrics:
        signature["metrics"] = metrics

    return signature


def _signature_summary(signature: dict[str, Any]) -> dict[str, Any]:
    metrics = signature.get("metrics", {}) if isinstance(signature, dict) else {}
    return {
        "type": signature.get("type") if isinstance(signature, dict) else None,
        "label": signature.get("label") if isinstance(signature, dict) else None,
        "children": len(signature.get("children", []))
        if isinstance(signature, dict)
        else None,
        "solids": metrics.get("solids_count"),
        "faces": metrics.get("faces_count"),
        "edges": metrics.get("edges_count"),
        "wires": metrics.get("wires_count"),
        "volume": metrics.get("volume"),
    }


def _load_script_component(script_path: str | Path | None = None) -> Any:
    from shared.workers.loader import load_component_from_script

    script_path = script_path or _workspace_script_path()
    return load_component_from_script(
        script_path=script_path,
        session_root=_workspace_root(),
    )


def _ensure_component_matches_workspace_script(
    component: Any, *, script_path: str | Path | None = None
) -> tuple[bool, str | None]:
    script_path = script_path or _workspace_script_path()
    try:
        script_component = _load_script_component(script_path)
    except Exception as exc:
        return (
            False,
            f"Unable to load persisted script {script_path!s} for validation: {exc}",
        )

    live_signature = _component_semantic_signature(component)
    script_signature = _component_semantic_signature(script_component)
    if live_signature != script_signature:
        return (
            False,
            "Workspace component does not match persisted script semantic "
            "signature. Persist the authored build script before validating. "
            f"live={_signature_summary(live_signature)} "
            f"script={_signature_summary(script_signature)}",
        )
    return True, None


def _validate_submission_script_path(
    compound: Compound, *, script_path: str | Path | None = None
) -> tuple[bool, str | None, str]:
    resolved_script_path = script_path or _workspace_script_path()
    matches, mismatch_message = _ensure_component_matches_workspace_script(
        compound, script_path=resolved_script_path
    )
    if not matches:
        return False, mismatch_message, resolved_script_path
    return True, None, resolved_script_path


def _simulate_submission(
    compound: Compound, *, family: str | None = None, **kwargs
) -> BenchmarkToolResponse:
    if _is_script_import_mode():
        return BenchmarkToolResponse(
            success=True,
            message=SCRIPT_IMPORT_DEFERRED_MESSAGE,
        )
    resolved_family = family or _script_agent_family()
    script_path = kwargs.get("script_path") or _workspace_script_path()
    matches, mismatch_message = _ensure_component_matches_workspace_script(
        compound, script_path=script_path
    )
    if not matches:
        return BenchmarkToolResponse(success=False, message=mismatch_message or "")
    if os.getenv("IS_HEAVY_WORKER"):
        from worker_heavy.utils.validation import simulate as real_simulate

        if "output_dir" in kwargs and kwargs["output_dir"] is not None:
            kwargs = {**kwargs, "output_dir": Path(kwargs["output_dir"])}
        kwargs = {**kwargs, "script_path": script_path}
        return real_simulate(compound, **kwargs)

    bundle_base64 = kwargs.get("bundle_base64") or _workspace_bundle_base64()
    controller_payload = {
        "script_path": str(script_path),
        "agent_role": _script_agent_role(),
        "backend": kwargs.get("backend", get_default_simulator_backend()),
        "smoke_test_mode": kwargs.get("smoke_test_mode"),
        "bundle_base64": bundle_base64,
    }
    controller_res = _call_controller_script_tool(
        "simulate",
        controller_payload,
    )
    if controller_res is not None:
        return BenchmarkToolResponse.model_validate(controller_res)

    payload = {**kwargs, "script_path": script_path, "bundle_base64": bundle_base64}
    res = _call_heavy_worker(f"/{resolved_family}/simulate", payload)
    return BenchmarkToolResponse.model_validate(res)


def simulate_benchmark_script_content(
    *,
    script_content: str,
    script_path: str = "script.py",
    backend: Any | None = None,
    smoke_test_mode: bool | None = None,
    skip_preview_rendering: bool = False,
    particle_budget: int | None = None,
    session_id: str | None = None,
    episode_id: str | None = None,
    stream_render_frames: bool = False,
    bundle_base64: str | None = None,
) -> BenchmarkToolResponse:
    """Run worker-heavy benchmark simulation from inline script content."""
    backend_value = getattr(backend, "value", backend) if backend is not None else None
    payload: dict[str, Any] = {
        "script_path": script_path,
        "script_content": script_content,
        "backend": backend_value or get_default_simulator_backend().value,
        "smoke_test_mode": smoke_test_mode,
        "skip_preview_rendering": skip_preview_rendering,
        "particle_budget": particle_budget,
        "session_id": session_id,
        "episode_id": episode_id,
        "stream_render_frames": stream_render_frames,
        "agent_role": _script_agent_role(),
    }
    if bundle_base64 is not None:
        payload["bundle_base64"] = bundle_base64
    res = _call_heavy_worker("/benchmark/simulate", payload)
    return BenchmarkToolResponse.model_validate(res)


def _validate_submission(
    compound: Compound, *, script_path: str | Path | None = None, **kwargs
) -> tuple[bool, str | None]:
    if _is_script_import_mode():
        return True, SCRIPT_IMPORT_DEFERRED_MESSAGE
    matches, mismatch_message, resolved_script_path = _validate_submission_script_path(
        compound, script_path=script_path
    )
    if not matches:
        return False, mismatch_message
    local_kwargs: dict[str, Any] = {}
    for key in (
        "build_zone",
        "output_dir",
        "session_id",
        "smoke_test_mode",
        "particle_budget",
        "script_content",
    ):
        if key in kwargs and kwargs[key] is not None:
            local_kwargs[key] = kwargs[key]

    if "output_dir" not in local_kwargs:
        local_kwargs["output_dir"] = _workspace_root()
    else:
        local_kwargs["output_dir"] = Path(local_kwargs["output_dir"])

    from worker_heavy.utils.file_validation import validate_benchmark_definition_yaml
    from worker_heavy.utils.validation import validate as real_validate

    benchmark_definition_path = (
        Path(local_kwargs["output_dir"]) / "benchmark_definition.yaml"
    )
    if benchmark_definition_path.exists():
        benchmark_valid, benchmark_result = validate_benchmark_definition_yaml(
            benchmark_definition_path.read_text(encoding="utf-8"),
            session_id=local_kwargs.get("session_id"),
        )
        if not benchmark_valid:
            return False, "; ".join(benchmark_result)

    success, message = real_validate(compound, **local_kwargs)
    if success and not message:
        message = "Validation successful"
    return success, message


def _submit_for_review_submission(
    compound: Compound, *, family: str | None = None
) -> bool:
    if _is_script_import_mode():
        return True
    resolved_family = family or _script_agent_family()
    script_path = _workspace_script_path()
    matches, mismatch_message = _ensure_component_matches_workspace_script(
        compound, script_path=script_path
    )
    if not matches:
        logger.info(
            "submit_for_review_deferred_script_mismatch",
            message=mismatch_message,
        )
        return False
    reviewer_stage = _default_reviewer_stage()
    episode_id = os.getenv("EPISODE_ID") or None
    if not Path("validation_results.json").exists():
        logger.info(
            "submit_for_review_deferred_missing_validation",
            extra={"path": "validation_results.json"},
        )
        return False
    if not Path("simulation_result.json").exists():
        logger.info(
            "submit_for_review_deferred_missing_simulation",
            extra={"path": "simulation_result.json"},
        )
        return False
    if os.getenv("IS_HEAVY_WORKER"):
        from worker_heavy.utils.handover import submit_for_review as real_submit

        return real_submit(
            compound,
            reviewer_stage=reviewer_stage,
            episode_id=episode_id,
            script_path=script_path,
        )

    bundle_base64 = _workspace_bundle_base64()
    controller_payload = {
        "script_path": script_path,
        "agent_role": _script_agent_role(),
        "reviewer_stage": reviewer_stage,
        "episode_id": episode_id,
        "bundle_base64": bundle_base64,
    }
    controller_res = _call_controller_script_tool(
        "submit",
        controller_payload,
    )
    if controller_res is not None:
        parsed = BenchmarkToolResponse.model_validate(controller_res)
        return parsed.success

    payload = {
        "script_path": script_path,
        "reviewer_stage": reviewer_stage,
        "episode_id": episode_id,
        "bundle_base64": bundle_base64,
    }
    res = _call_heavy_worker(f"/{resolved_family}/submit", payload)
    return BenchmarkToolResponse.model_validate(res).success


def validate_benchmark(compound: Compound, **kwargs) -> tuple[bool, str | None]:
    if _script_agent_family() != "benchmark":
        return False, "Current role is not benchmark-side"
    return _validate_submission(compound, **kwargs)


def validate_engineering(compound: Compound, **kwargs) -> tuple[bool, str | None]:
    if _script_agent_family() != "engineering":
        return False, "Current role is not engineering-side"
    return _validate_submission(compound, **kwargs)


def simulate_benchmark(compound: Compound, **kwargs) -> BenchmarkToolResponse:
    if _script_agent_family() != "benchmark":
        return BenchmarkToolResponse(
            success=False,
            message="Current role is not benchmark-side",
        )
    return _simulate_submission(compound, family="benchmark", **kwargs)


def simulate_engineering(compound: Compound, **kwargs) -> BenchmarkToolResponse:
    if _script_agent_family() != "engineering":
        return BenchmarkToolResponse(
            success=False,
            message="Current role is not engineering-side",
        )
    return _simulate_submission(compound, family="engineering", **kwargs)


def submit_benchmark_for_review(compound: Compound) -> bool:
    if _script_agent_family() != "benchmark":
        return False
    return _submit_for_review_submission(compound, family="benchmark")


def submit_solution_for_review(compound: Compound) -> bool:
    if _script_agent_family() != "engineering":
        return False
    return _submit_for_review_submission(compound, family="engineering")


def validate_and_price(
    part: Any, method: Any = None, config: Any = None
) -> BenchmarkToolResponse:
    """Proxy for DFM analysis."""
    if os.getenv("IS_HEAVY_WORKER"):
        from worker_heavy.utils.dfm import validate_and_price as real_val

        return real_val(part, method, config)

    from shared.workers.workbench_models import ManufacturingMethod

    if isinstance(method, ManufacturingMethod):
        method_str = method.value
    else:
        method_str = str(method)

    payload = {
        "script_path": "script.py",
        "method": method_str,
        "quantity": 1,  # Default
    }
    res = _call_heavy_worker("/benchmark/analyze", payload)
    return BenchmarkToolResponse.model_validate(res)


class _PreviewResponseProxy:
    def __init__(self, factory):
        self._factory = factory
        self._resolved: PreviewDesignResponse | None = None

    async def _resolve_async(self) -> PreviewDesignResponse:
        if self._resolved is None:
            self._resolved = await self._factory()
        return self._resolved

    def _resolve_sync(self) -> PreviewDesignResponse:
        if self._resolved is not None:
            return self._resolved
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._resolved = asyncio.run(self._factory())
            return self._resolved
        raise RuntimeError(
            "render_cad() must be awaited when called from an async context"
        )

    def __await__(self):
        return self._resolve_async().__await__()

    def __getattr__(self, item):
        return getattr(self._resolve_sync(), item)

    def __bool__(self):
        return bool(self._resolve_sync())

    def __repr__(self):
        if self._resolved is not None:
            return repr(self._resolved)
        return "<_PreviewResponseProxy unresolved>"


async def _preview_async(
    component: Part | Compound,
    orbit_pitch: float | list[float] = 45,
    orbit_yaw: float | list[float] = 45,
    rgb: bool | None = None,
    depth: bool | None = None,
    segmentation: bool | None = None,
    payload_path: bool = False,
    rendering_type: PreviewRenderingType | str | None = None,
) -> PreviewDesignResponse:
    """Render an on-demand preview for a live build123d component."""
    requested_rendering_type = (
        PreviewRenderingType(str(rendering_type))
        if rendering_type is not None
        else PreviewRenderingType.RGB
    )
    if _is_script_import_mode():
        return PreviewDesignResponse(
            success=True,
            status_text=SCRIPT_IMPORT_DEFERRED_MESSAGE,
            message=SCRIPT_IMPORT_DEFERRED_MESSAGE,
            rendering_type=requested_rendering_type,
        )
    try:
        agent_role = _script_agent_role()
        preview_scene_bundle = export_preview_scene_bundle(
            component,
            objectives=None,
            workspace_root=_workspace_root(),
        )
        preview_request = PreviewDesignRequest(
            script_path="preview_scene.json",
            bundle_base64=preview_scene_bundle,
            agent_role=agent_role,
            orbit_pitch_deg=orbit_pitch,
            orbit_yaw_deg=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            rendering_type=(
                PreviewRenderingType(str(rendering_type))
                if rendering_type is not None
                else None
            ),
        )
        fallback_bundle_base64 = preview_scene_bundle
        fallback_script_path = "preview_scene.json"
    except Exception as exc:
        return PreviewDesignResponse(
            success=False,
            status_text="Preview generation failed",
            message=str(exc),
            rendering_type=requested_rendering_type,
        )
    response = _call_worker_light_preview(
        preview_request, session_id=os.getenv("SESSION_ID")
    )
    if response is None:
        response = _call_controller_preview_tool(preview_request)
    if response is None:
        response = render_preview(
            bundle_base64=fallback_bundle_base64,
            script_path=fallback_script_path,
            orbit_pitch=orbit_pitch,
            orbit_yaw=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            rendering_type=(
                PreviewRenderingType(str(rendering_type))
                if rendering_type is not None
                else None
            ),
            session_id=os.getenv("SESSION_ID"),
            agent_role=agent_role,
        )
    if not response.success:
        return response

    workspace_root = _workspace_root()
    preview_output_dir = _preview_output_dir()
    for candidate in (response.artifact_path, response.image_path):
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate_path.parent == Path():
            continue
        if candidate_path.is_absolute():
            preview_output_dir = candidate_path.parent
        else:
            preview_output_dir = workspace_root / candidate_path.parent
        break

    materialized_path = materialize_preview_response(
        response,
        preview_output_dir,
    )
    if materialized_path is not None:
        local_path = str(materialized_path.relative_to(workspace_root))
        response.image_path = local_path
        response.artifact_path = local_path
    elif response.artifact_path is None and response.image_path is not None:
        response.artifact_path = response.image_path
    if response.manifest_path is None:
        response.manifest_path = str(
            preview_output_dir.relative_to(workspace_root) / "render_manifest.json"
        )
    if response.orbit_pitch_deg is None:
        if isinstance(orbit_pitch, float):
            response.orbit_pitch_deg = orbit_pitch
        elif isinstance(orbit_pitch, list) and len(orbit_pitch) == 1:
            response.orbit_pitch_deg = orbit_pitch[0]
    if response.orbit_yaw_deg is None:
        if isinstance(orbit_yaw, float):
            response.orbit_yaw_deg = orbit_yaw
        elif isinstance(orbit_yaw, list) and len(orbit_yaw) == 1:
            response.orbit_yaw_deg = orbit_yaw[0]
    if response.status_text is None:
        response.status_text = response.message or "Preview generated successfully"
    if response.message:
        print(response.message)
    return response


def render_cad(
    component: Part | Compound,
    orbit_pitch: float | list[float] = 45,
    orbit_yaw: float | list[float] = 45,
    rgb: bool | None = None,
    depth: bool | None = None,
    segmentation: bool | None = None,
    payload_path: bool = False,
    rendering_type: PreviewRenderingType | str | None = None,
) -> _PreviewResponseProxy:
    return _PreviewResponseProxy(
        lambda: _preview_async(
            component,
            orbit_pitch=orbit_pitch,
            orbit_yaw=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            rendering_type=rendering_type,
        )
    )


def list_render_bundles(*args: Any, **kwargs: Any) -> Any:
    """Proxy to the worker-light render bundle history helper."""
    from worker_light.utils.render_query import (
        list_render_bundles as _list_render_bundles,
    )

    return _list_render_bundles(*args, **kwargs)


def query_render_bundle(*args: Any, **kwargs: Any) -> Any:
    """Proxy to the worker-light compact bundle query helper."""
    from worker_light.utils.render_query import (
        query_render_bundle as _query_render_bundle,
    )

    return _query_render_bundle(*args, **kwargs)


def pick_preview_pixel(*args: Any, **kwargs: Any) -> Any:
    """Proxy to the worker-light point-pick helper."""
    from worker_light.utils.render_query import (
        pick_preview_pixel as _pick_preview_pixel,
    )

    return _pick_preview_pixel(*args, **kwargs)


def pick_preview_pixels(*args: Any, **kwargs: Any) -> Any:
    """Proxy to the worker-light batch point-pick helper."""
    from worker_light.utils.render_query import (
        pick_preview_pixels as _pick_preview_pixels,
    )

    return _pick_preview_pixels(*args, **kwargs)


def refuse_plan(reason: str) -> bool:
    """Refuse the current plan."""
    if os.getenv("IS_HEAVY_WORKER"):
        from worker_heavy.utils.handover import refuse_plan as real_refuse

        return real_refuse(reason)

    refusal_data = PlanRefusal(
        reason=reason,
        timestamp=os.getenv("TIMESTAMP"),
        session_id=os.getenv("SESSION_ID", "default"),
    )
    with Path("refusal.json").open("w") as f:
        f.write(refusal_data.model_dump_json(indent=2))
    return True
