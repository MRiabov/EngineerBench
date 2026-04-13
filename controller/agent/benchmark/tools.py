import hashlib
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path

import structlog
import yaml
from sqlalchemy import select

from controller.agent.tools import (
    _invoke_cots_search_subagent,
    filter_tools_for_agent,
    get_common_tools,
    run_validate_and_price_script,
)
from controller.middleware.remote_fs import RemoteFilesystemMiddleware
from controller.observability.middleware_helper import broadcast_file_update
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Asset
from controller.utils import resolve_episode_id
from shared.enums import AgentName
from shared.git_utils import repo_revision
from shared.models.schemas import PlannerSubmissionResult
from shared.script_contracts import (
    plan_path_for_agent,
)
from shared.workers.schema import PlanReviewManifest, PreviewRenderingType

logger = structlog.get_logger(__name__)

BENCHMARK_ESTIMATE_HEADROOM_MULTIPLIER = 1.5


def _derived_episode_id(session_id: str) -> str:
    try:
        return str(uuid.UUID(session_id))
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))


def _workspace_environment_version(content: str) -> str | None:
    try:
        data = yaml.safe_load(content) or {}
    except Exception:
        return None
    version = data.get("version")
    if version is None:
        return None
    version_text = str(version).strip()
    return version_text or None


def _canonicalize_benchmark_constraints(
    benchmark_definition_content: str,
) -> tuple[str, list[str]]:
    """Fill benchmark runtime caps from planner-authored solution estimates."""
    errors: list[str] = []
    try:
        raw_data = yaml.safe_load(benchmark_definition_content) or {}
    except Exception as exc:
        return benchmark_definition_content, [
            f"benchmark_definition.yaml YAML parse error: {exc}"
        ]

    constraints = raw_data.get("constraints")
    if not isinstance(constraints, dict):
        return benchmark_definition_content, [
            "benchmark_definition.yaml: constraints must be an object"
        ]

    estimated_cost = constraints.get("estimated_solution_cost_usd")
    estimated_weight = constraints.get("estimated_solution_weight_g")
    if not isinstance(estimated_cost, (int, float)):
        errors.append(
            "benchmark_definition.yaml: constraints.estimated_solution_cost_usd must be a number"
        )
    if not isinstance(estimated_weight, (int, float)):
        errors.append(
            "benchmark_definition.yaml: constraints.estimated_solution_weight_g must be a number"
        )
    if errors:
        return benchmark_definition_content, errors

    if float(estimated_cost) <= 0:
        errors.append(
            "benchmark_definition.yaml: constraints.estimated_solution_cost_usd must be > 0"
        )
    if float(estimated_weight) <= 0:
        errors.append(
            "benchmark_definition.yaml: constraints.estimated_solution_weight_g must be > 0"
        )
    if errors:
        return benchmark_definition_content, errors

    constraints["estimated_solution_cost_usd"] = float(estimated_cost)
    constraints["estimated_solution_weight_g"] = float(estimated_weight)
    constraints["max_unit_cost"] = (
        float(estimated_cost) * BENCHMARK_ESTIMATE_HEADROOM_MULTIPLIER
    )
    constraints["max_weight_g"] = (
        float(estimated_weight) * BENCHMARK_ESTIMATE_HEADROOM_MULTIPLIER
    )

    raw_data["constraints"] = constraints
    return yaml.dump(raw_data, sort_keys=False), []


def get_benchmark_planner_tools(
    fs: RemoteFilesystemMiddleware, session_id: str
) -> list[Callable]:
    """Planner-only filesystem toolset to keep planning loops focused."""

    def _normalized_tokens(value: str) -> tuple[str, ...]:
        return tuple(token for token in re.split(r"[^a-z0-9]+", value.lower()) if token)

    def _contiguous_phrases(tokens: tuple[str, ...]) -> set[tuple[str, ...]]:
        phrases: set[tuple[str, ...]] = set()
        for start in range(len(tokens)):
            for end in range(start + 1, len(tokens) + 1):
                phrases.add(tokens[start:end])
        return phrases

    def _phrase_matches(phrase_windows: set[tuple[str, ...]], candidate: str) -> bool:
        candidate_tokens = _normalized_tokens(candidate)
        return bool(candidate_tokens) and candidate_tokens in phrase_windows

    async def _benchmark_owned_cots_query_reason(query: str) -> str | None:
        raw = await fs.read_file_optional("benchmark_definition.yaml")
        if raw is None:
            return None

        try:
            data = yaml.safe_load(raw) or {}
        except Exception:
            return None

        query_tokens = _normalized_tokens(query)
        if not query_tokens:
            return None
        query_phrases = _contiguous_phrases(query_tokens)

        benchmark_terms: set[str] = set()
        benchmark_parts = data.get("benchmark_parts")
        if isinstance(benchmark_parts, list):
            for part in benchmark_parts:
                if not isinstance(part, dict):
                    continue
                for field_name in ("part_id", "label"):
                    field_value = part.get(field_name)
                    if isinstance(field_value, str) and field_value.strip():
                        benchmark_terms.add(field_value)

        matches = sorted(
            term for term in benchmark_terms if _phrase_matches(query_phrases, term)
        )
        if not matches:
            return None

        return (
            "Benchmark-owned fixtures are read-only task context and are excluded "
            "from COTS pricing/manufacturability. "
            f"Do not use invoke_cots_search_subagent for query {query!r}. "
            f"Matched benchmark-owned term(s): {', '.join(matches)}. "
            "Use one heuristic estimate for the likely engineer-side solution instead."
        )

    async def list_files(path: str = "/"):
        return await fs.list_files(path)

    async def read_file(path: str):
        return await fs.read_file(path)

    async def write_file(path: str, content: str, overwrite: bool = False):
        return await fs.write_file(path, content, overwrite=overwrite)

    async def edit_file(path: str, old_string: str, new_string: str):
        from controller.middleware.remote_fs import EditOp

        return await fs.edit_file(
            path, [EditOp(old_string=old_string, new_string=new_string)]
        )

    async def grep(pattern: str, path: str | None = None, glob: str | None = None):
        return await fs.grep(pattern, path, glob)

    async def render_cad(
        script_path: str = "benchmark_plan_evidence_script.py",
        orbit_pitch: float | list[float] = 45,
        orbit_yaw: float | list[float] = 45,
        rgb: bool | None = None,
        depth: bool | None = None,
        segmentation: bool | None = None,
        payload_path: bool = False,
        drafting: bool = False,
        rendering_type: PreviewRenderingType | str | None = None,
        smoke_test_mode: bool | None = None,
    ):
        return await fs.client.render_cad(
            script_path,
            orbit_pitch=orbit_pitch,
            orbit_yaw=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            drafting=drafting,
            rendering_type=rendering_type,
            smoke_test_mode=smoke_test_mode,
            agent_role=AgentName.BENCHMARK_PLANNER,
        )

    async def preview(
        script_path: str = "benchmark_plan_evidence_script.py",
        orbit_pitch: float | list[float] = 45,
        orbit_yaw: float | list[float] = 45,
        rgb: bool | None = None,
        depth: bool | None = None,
        segmentation: bool | None = None,
        payload_path: bool = False,
        drafting: bool = False,
        rendering_type: PreviewRenderingType | str | None = None,
        smoke_test_mode: bool | None = None,
        ):
            return await render_cad(
                script_path=script_path,
                orbit_pitch=orbit_pitch,
                orbit_yaw=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            drafting=drafting,
            rendering_type=rendering_type,
            smoke_test_mode=smoke_test_mode,
        )

    async def invoke_cots_search_subagent(
        query: str,
        max_weight_g: float | None = None,
        max_cost: float | None = None,
        category: str | None = None,
        limit: int = 5,
    ) -> str:
        """
        Invoke the dedicated COTS search subagent for likely engineer-side parts only.

        Benchmark-owned fixtures must not be priced through catalog search.
        """
        blocked_reason = await _benchmark_owned_cots_query_reason(query)
        if blocked_reason:
            raise ValueError(blocked_reason)
        return await _invoke_cots_search_subagent(
            query=query,
            max_weight_g=max_weight_g,
            max_cost=max_cost,
            category=category,
            limit=limit,
            session_id=session_id,
        )

    async def submit_benchmark_plan() -> dict:
        """
        Validate benchmark planner artifacts and explicitly submit planner handoff.

        Returns:
            {"ok": bool, "status": "submitted"|"rejected", "errors": [...], "node_type": "..."}
        """
        from worker_heavy.utils.dfm import load_planner_manufacturing_config_from_text
        from worker_heavy.utils.file_validation import validate_node_output

        required_files = [
            plan_path_for_agent(AgentName.BENCHMARK_PLANNER).as_posix(),
            "todo.md",
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
        ]
        artifacts: dict[str, str] = {}
        missing_files: list[str] = []

        async def _read_required_text(rel_path: str) -> str | None:
            content = await fs.client.read_file_optional(
                rel_path, bypass_agent_permissions=True
            )
            if isinstance(content, str) and content.strip():
                return content

            try:
                episode_uuid = resolve_episode_id(fs.episode_id)
            except Exception:
                return None

            session_factory = get_sessionmaker()
            async with session_factory() as db:
                result = await db.execute(
                    select(Asset.content).where(
                        Asset.episode_id == episode_uuid,
                        Asset.s3_path == rel_path,
                    )
                )
                persisted_content = result.scalar_one_or_none()

            if isinstance(persisted_content, str) and persisted_content.strip():
                return persisted_content
            return None

        for rel_path in required_files:
            content = await _read_required_text(rel_path)
            if content is None:
                missing_files.append(rel_path)
                continue
            artifacts[rel_path] = content

        if missing_files:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[f"Missing required file: {p}" for p in missing_files],
                node_type=AgentName.BENCHMARK_PLANNER,
            )
            return result.model_dump(mode="json")

        manufacturing_config_text = await _read_required_text(
            "manufacturing_config.yaml"
        )
        if manufacturing_config_text is None:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[
                    "manufacturing_config.yaml missing; planner handoff requires a "
                    "workspace pricing source"
                ],
                node_type=AgentName.BENCHMARK_PLANNER,
            )
            return result.model_dump(mode="json")

        try:
            manufacturing_config = load_planner_manufacturing_config_from_text(
                manufacturing_config_text
            )
        except Exception as exc:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[
                    f"manufacturing_config.yaml invalid for planner handoff: {exc}"
                ],
                node_type=AgentName.BENCHMARK_PLANNER,
            )
            return result.model_dump(mode="json")

        canonical_benchmark_definition, canonicalization_errors = (
            _canonicalize_benchmark_constraints(artifacts["benchmark_definition.yaml"])
        )
        if canonicalization_errors:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=canonicalization_errors,
                node_type=AgentName.BENCHMARK_PLANNER,
            )
            return result.model_dump(mode="json")

        artifacts["benchmark_definition.yaml"] = canonical_benchmark_definition
        await fs.write_file(
            "benchmark_definition.yaml",
            canonical_benchmark_definition,
            overwrite=True,
        )
        artifacts["manufacturing_config.yaml"] = manufacturing_config_text

        pricing_result = await run_validate_and_price_script(fs)
        if not pricing_result["ok"]:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[
                    "validate_costing_and_price failed: "
                    + (
                        str(pricing_result["stderr"]).strip()
                        or str(pricing_result["stdout"]).strip()
                        or "pricing script returned a non-zero exit status"
                    )
                ],
                node_type=AgentName.BENCHMARK_PLANNER,
            )
            return result.model_dump(mode="json")

        benchmark_assembly_definition_text = await fs.read_file_optional(
            "benchmark_assembly_definition.yaml"
        )
        if benchmark_assembly_definition_text is None:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=["Missing required file: benchmark_assembly_definition.yaml"],
                node_type=AgentName.BENCHMARK_PLANNER,
            )
            return result.model_dump(mode="json")

        artifacts["benchmark_assembly_definition.yaml"] = (
            benchmark_assembly_definition_text
        )

        is_valid, errors = validate_node_output(
            AgentName.BENCHMARK_PLANNER,
            artifacts,
            manufacturing_config=manufacturing_config,
        )
        if is_valid:
            artifact_hashes = {
                rel_path: hashlib.sha256(content.encode("utf-8")).hexdigest()
                for rel_path, content in artifacts.items()
            }
            manifest = PlanReviewManifest(
                status="ready_for_review",
                reviewer_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
                session_id=fs.client.session_id,
                planner_node_type=AgentName.BENCHMARK_PLANNER,
                episode_id=fs.episode_id,
                worker_session_id=fs.client.session_id,
                benchmark_revision=repo_revision(Path(__file__).resolve().parents[2]),
                environment_version=_workspace_environment_version(
                    artifacts["benchmark_assembly_definition.yaml"]
                ),
                artifact_hashes=artifact_hashes,
            )
            success = await fs.client.write_file(
                ".manifests/benchmark_plan_review_manifest.json",
                json.dumps(manifest.model_dump(mode="json"), indent=2),
                overwrite=True,
                bypass_agent_permissions=True,
            )
            if success:
                await broadcast_file_update(
                    fs.episode_id,
                    ".manifests/benchmark_plan_review_manifest.json",
                    json.dumps(manifest.model_dump(mode="json"), indent=2),
                )

            success = await fs.client.write_file(
                "benchmark_plan_review_manifest.json",
                json.dumps(manifest.model_dump(mode="json"), indent=2),
                overwrite=True,
                bypass_agent_permissions=True,
            )
            if success:
                await broadcast_file_update(
                    fs.episode_id,
                    "benchmark_plan_review_manifest.json",
                    json.dumps(manifest.model_dump(mode="json"), indent=2),
                )
        result = PlannerSubmissionResult(
            ok=is_valid,
            status="submitted" if is_valid else "rejected",
            errors=errors,
            node_type=AgentName.BENCHMARK_PLANNER,
        )
        return result.model_dump(mode="json")

    return filter_tools_for_agent(
        fs,
        [
            list_files,
            read_file,
            write_file,
            edit_file,
            grep,
            invoke_cots_search_subagent,
            render_cad,
            submit_benchmark_plan,
        ],
    )


def get_benchmark_tools(
    fs: RemoteFilesystemMiddleware, session_id: str
) -> list[Callable]:
    # Benchmark ReAct tools intentionally exclude validate/simulate:
    # these are Python utils imported and called from script context.
    return get_common_tools(fs, session_id)
