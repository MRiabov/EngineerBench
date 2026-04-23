from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from sqlalchemy import select

from controller.agent.benchmark_handover_validation import (
    BenchmarkPlanReviewerEvidence,
    build_benchmark_plan_reviewer_evidence,
)
from controller.clients.worker import WorkerClient
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Asset, Episode
from shared.enums import AgentName, EpisodeStatus, EpisodeType, TerminalReason
from shared.git_utils import repo_revision
from shared.models.schemas import AssemblyDefinition, EpisodeMetadata
from shared.models.simulation import SimulationResult
from shared.script_contracts import (
    BENCHMARK_SCRIPT_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    plan_path_for_reviewer_stage,
)
from shared.workers.schema import (
    PlanReviewManifest,
    RenderManifest,
    ReviewManifest,
    ValidationResultRecord,
)
from worker_heavy.utils.file_validation import (
    validate_benchmark_assembly_payload_contract,
    validate_benchmark_definition_yaml,
    validate_planner_handoff_cross_contract,
)
from worker_heavy.workbenches.config import load_required_merged_config

PlanReviewerStage = Literal[
    AgentName.BENCHMARK_PLAN_REVIEWER,
    AgentName.ENGINEER_PLAN_REVIEWER,
]

MIN_RUNTIME_JITTER_SUCCESS_RATE = 0.7


class ApprovedBenchmarkBundle(BaseModel):
    benchmark_episode_id: str
    benchmark_worker_session_id: str
    review_manifest: ReviewManifest


def _goal_reached(summary: str) -> bool:
    text = (summary or "").lower()
    return "goal achieved" in text or "green zone" in text or "goal zone" in text


def _is_static_preview_render(path: str) -> bool:
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg"}


def _normalize_render_path(path: str) -> str:
    normalized = str(Path(path))
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


async def _list_render_media_paths(worker_client: WorkerClient) -> list[str]:
    """Recursively discover render image paths under the session `/renders` tree."""
    try:
        pending_dirs = ["/renders"]
        visited_dirs: set[str] = set()
        media_paths: list[str] = []

        while pending_dirs:
            current_dir = pending_dirs.pop()
            if current_dir in visited_dirs:
                continue
            visited_dirs.add(current_dir)

            entries = await worker_client.list_files(current_dir)
            for entry in entries:
                entry_path = getattr(entry, "path", "") or ""
                if not entry_path:
                    continue
                if getattr(entry, "is_dir", False):
                    pending_dirs.append(entry_path.rstrip("/"))
                    continue
                if _is_static_preview_render(entry_path):
                    media_paths.append(entry_path.lstrip("/"))

        return sorted(dict.fromkeys(media_paths))
    except Exception:
        return []


async def _list_episode_render_asset_paths(
    episode_id: str | uuid.UUID | None,
) -> list[str]:
    """Discover render image paths already surfaced as episode assets."""
    if episode_id is None:
        return []

    try:
        episode_uuid = uuid.UUID(str(episode_id).strip())
    except Exception:
        return []

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        result = await db.execute(
            select(Asset.s3_path).where(Asset.episode_id == episode_uuid)
        )

        raw_paths = result.scalars().all()

    media_paths: set[str] = set()
    for raw_path in raw_paths:
        normalized = Path(str(raw_path)).as_posix().lstrip("/")
        if _is_static_preview_render(normalized):
            media_paths.add(normalized)
    return sorted(media_paths)


async def _validate_render_manifest_bundle(
    worker_client: WorkerClient,
    *,
    render_paths: list[str],
) -> str | None:
    expected_render_paths = {
        _normalize_render_path(render_path)
        for render_path in render_paths
        if _is_static_preview_render(render_path)
    }
    if not expected_render_paths:
        return None

    bundle_roots = {Path(path.lstrip("/")).parent for path in expected_render_paths}

    current_revision = _current_git_revision()
    if current_revision is None:
        return "current repository git revision could not be determined."

    for candidate_root in sorted(bundle_roots):
        manifest_path = candidate_root / "render_manifest.json"
        manifest_raw = await worker_client.read_file_optional(
            str(manifest_path), bypass_agent_permissions=True
        )
        if manifest_raw is None:
            continue

        try:
            render_manifest = RenderManifest.model_validate_json(manifest_raw)
        except Exception as exc:
            return f"{manifest_path} invalid: {exc}"

        is_current_episode_bundle = (
            candidate_root.as_posix() == "renders/current-episode"
        )
        if render_manifest.revision:
            if render_manifest.revision.strip().lower() != current_revision:
                return (
                    f"{manifest_path} revision does not match the latest repository "
                    "git revision."
                )
        elif not is_current_episode_bundle:
            return f"{manifest_path} revision is missing."

        actual_render_paths = {
            _normalize_render_path(path)
            for path in render_manifest.artifacts.keys()
            if _is_static_preview_render(path)
        }
        if actual_render_paths == expected_render_paths:
            preview_paths = {
                _normalize_render_path(path)
                for path in render_manifest.preview_evidence_paths
                if _is_static_preview_render(path)
            }
            if preview_paths == expected_render_paths:
                return None
            return (
                f"{manifest_path} is out of sync with the latest render bundle: "
                "preview evidence paths do not match the artifact set."
            )

        missing = sorted(expected_render_paths - actual_render_paths)
        unexpected = sorted(actual_render_paths - expected_render_paths)
        details: list[str] = []
        if missing:
            details.append(f"missing entries: {missing}")
        if unexpected:
            details.append(f"unexpected entries: {unexpected}")
        return (
            f"{manifest_path} is out of sync with the latest render bundle: "
            + "; ".join(details)
        )

    return "bundle-local render_manifest.json missing for latest render bundle"


def _is_binary_review_artifact(path: str) -> bool:
    """Return True for review-handoff media files that must not be read as text."""
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"}


def _current_git_revision() -> str | None:
    return repo_revision(Path(__file__).resolve().parents[2])


def _planner_role_for_reviewer_stage(reviewer_stage: AgentName) -> AgentName:
    if reviewer_stage == AgentName.BENCHMARK_REVIEWER:
        return AgentName.BENCHMARK_PLANNER
    return AgentName.ENGINEER_PLANNER


def _normalize_reviewer_stage(stage: AgentName | str) -> AgentName:
    if isinstance(stage, AgentName):
        return stage
    return AgentName(str(stage))


def _planner_submission_helper_name_for_stage(stage: PlanReviewerStage) -> str:
    if stage == AgentName.BENCHMARK_PLAN_REVIEWER:
        return "submit_benchmark_plan"
    return "submit_engineering_plan"


def _review_submission_helper_name_for_stage(reviewer_stage: AgentName) -> str:
    if reviewer_stage == AgentName.BENCHMARK_REVIEWER:
        return "submit_benchmark_for_review"
    return "submit_solution_for_review"


async def _load_review_manifest(
    worker_client: WorkerClient,
    *,
    manifest_path: str,
    submission_helper_name: str,
    require_git_revision: bool = True,
) -> tuple[ReviewManifest | None, str | None]:
    manifest_raw = await worker_client.read_file_optional(
        manifest_path,
        bypass_agent_permissions=True,
    )
    if manifest_raw is None:
        return (
            None,
            f"{manifest_path} missing; call {submission_helper_name}(compound) first.",
        )

    try:
        manifest = ReviewManifest.model_validate_json(manifest_raw)
    except Exception as exc:
        return None, f"{manifest_path} invalid: {exc}"

    if manifest.status != "ready_for_review":
        return None, "review manifest status is not ready_for_review."

    if not manifest.revision:
        return None, "review manifest revision is missing."
    if require_git_revision:
        current_revision = _current_git_revision()
        if current_revision is None:
            return None, "current repository git revision could not be determined."
        if manifest.revision.strip().lower() != current_revision:
            return (
                None,
                "review manifest revision does not match the latest repository git "
                f"revision; re-run validate, simulate, and {submission_helper_name}(compound).",
            )

    required_paths: list[str] = [manifest.script_path]
    if manifest.mjcf_path:
        required_paths.append(manifest.mjcf_path)
    if manifest.cad_path:
        required_paths.append(manifest.cad_path)
    if manifest.objectives_path:
        required_paths.append(manifest.objectives_path)
    if manifest.assembly_definition_path:
        required_paths.append(manifest.assembly_definition_path)
    required_paths.extend(manifest.renders)
    required_paths.extend(manifest.preview_evidence_paths)

    for path in required_paths:
        if _is_binary_review_artifact(path):
            if not await worker_client.exists(path):
                return None, f"review manifest evidence missing: {path}"
            continue

        content = await worker_client.read_file_optional(path)
        if content is None:
            return None, f"review manifest evidence missing: {path}"

    render_manifest_error = await _validate_render_manifest_bundle(
        worker_client,
        render_paths=manifest.renders,
    )
    if render_manifest_error is not None:
        return None, render_manifest_error

    return manifest, None


async def collect_plan_reviewer_handover_evidence(
    worker_client: WorkerClient,
    *,
    manifest_path: str,
    expected_stage: PlanReviewerStage,
    episode_id: str | uuid.UUID | None = None,
    require_git_revision: bool = True,
) -> tuple[BenchmarkPlanReviewerEvidence | None, str | None]:
    """Collect latest-revision evidence for the benchmark plan reviewer."""
    plan_manifest_raw = await worker_client.read_file_optional(
        manifest_path,
        bypass_agent_permissions=True,
    )
    if plan_manifest_raw is None:
        submission_helper_name = _planner_submission_helper_name_for_stage(
            expected_stage
        )
        return (
            None,
            f"{manifest_path} missing; call {submission_helper_name}() first.",
        )

    try:
        plan_manifest = PlanReviewManifest.model_validate_json(plan_manifest_raw)
    except Exception as exc:
        return None, f"{manifest_path} invalid: {exc}"

    if plan_manifest.status != "ready_for_review":
        return None, "plan review manifest status is not ready_for_review."
    if plan_manifest.reviewer_stage != expected_stage:
        return (
            None,
            f"plan review manifest stage mismatch: expected {expected_stage}, "
            f"got {plan_manifest.reviewer_stage}.",
        )
    if not plan_manifest.artifact_hashes:
        return None, "plan review manifest has no artifact_hashes."

    current_revision = _current_git_revision()
    if require_git_revision and current_revision is None:
        return None, "current repository git revision could not be determined."

    validation_error = await validate_plan_reviewer_handover(
        worker_client,
        manifest_path=manifest_path,
        expected_stage=expected_stage,
    )
    if validation_error is not None:
        return None, validation_error

    artifacts: dict[str, str] = {}
    plan_artifact_name = plan_path_for_reviewer_stage(expected_stage).as_posix()
    for rel_path in (
        plan_artifact_name,
        "todo.md",
        "benchmark_definition.yaml",
        "benchmark_assembly_definition.yaml",
    ):
        content = await worker_client.read_file_optional(rel_path)
        if content is None:
            return None, f"review manifest evidence missing: {rel_path}"
        artifacts[rel_path] = content

    benchmark_definition = None
    benchmark_definition_text = artifacts.get("benchmark_definition.yaml")
    if benchmark_definition_text:
        try:
            is_valid, benchmark_result = validate_benchmark_definition_yaml(
                benchmark_definition_text,
                session_id=worker_client.session_id,
            )
            if not is_valid:
                return None, "; ".join(benchmark_result)
            benchmark_definition = benchmark_result
        except Exception as exc:
            return None, f"benchmark_definition.yaml invalid: {exc}"

    render_paths: list[str] = []
    render_timeout_seconds = 10.0
    render_poll_interval_seconds = 0.5
    render_deadline = asyncio.get_running_loop().time() + render_timeout_seconds
    while True:
        episode_render_paths = set(await _list_episode_render_asset_paths(episode_id))
        workspace_render_paths = set(await _list_render_media_paths(worker_client))
        current_episode_render_paths = {
            path
            for path in episode_render_paths | workspace_render_paths
            if Path(path).as_posix().startswith("renders/current-episode/")
        }
        render_paths = sorted(
            current_episode_render_paths
            or (episode_render_paths | workspace_render_paths)
        )
        if render_paths:
            break
        if asyncio.get_running_loop().time() >= render_deadline:
            break
        await asyncio.sleep(render_poll_interval_seconds)

    if render_paths:
        render_manifest_error = await _validate_render_manifest_bundle(
            worker_client,
            render_paths=render_paths,
        )
        if (
            render_manifest_error is not None
            and expected_stage != AgentName.BENCHMARK_PLAN_REVIEWER
        ):
            return None, render_manifest_error

    evidence = build_benchmark_plan_reviewer_evidence(
        artifacts=artifacts,
        benchmark_definition=benchmark_definition,
        session_id=worker_client.session_id,
        render_paths=render_paths,
        review_manifest_path=manifest_path,
        review_manifest_revision=current_revision,
        review_manifest_script_sha256=hashlib.sha256(
            plan_manifest_raw.encode("utf-8")
        ).hexdigest(),
        latest_revision_verified=True,
    )
    return evidence, None


async def validate_reviewer_handover(
    worker_client: WorkerClient,
    *,
    manifest_path: str,
    expected_stage: AgentName | str,
    require_git_revision: bool = True,
    require_verification_result: bool | None = None,
) -> str | None:
    """
    Validate that reviewer handoff artifacts are present and correspond to the
    latest script revision.
    """
    normalized_expected_stage = _normalize_reviewer_stage(expected_stage)
    review_manifest, manifest_error = await _load_review_manifest(
        worker_client,
        manifest_path=manifest_path,
        submission_helper_name=_review_submission_helper_name_for_stage(
            normalized_expected_stage
        ),
        require_git_revision=require_git_revision,
    )
    if manifest_error is not None:
        return manifest_error
    assert review_manifest is not None

    script_content = await worker_client.read_file(review_manifest.script_path)
    script_sha = hashlib.sha256(script_content.encode("utf-8")).hexdigest()
    if script_sha != review_manifest.script_sha256:
        return (
            "review manifest does not match latest script revision; "
            f"re-run validate, simulate, and "
            f"{_review_submission_helper_name_for_stage(normalized_expected_stage)}(compound)."
        )

    try:
        val_raw = await worker_client.read_file_optional("validation_results.json")
        if val_raw is None:
            return "validation_results.json missing."
        val_record = ValidationResultRecord.model_validate_json(val_raw)
    except Exception as e:
        return f"validation_results.json invalid: {e}"
    if not val_record.success or not review_manifest.validation_success:
        return "validation gate failed for latest revision."
    if val_record.script_sha256 != review_manifest.script_sha256:
        return (
            "validation results do not match review manifest script revision; "
            f"re-run validate, simulate, and "
            f"{_review_submission_helper_name_for_stage(expected_stage)}(compound)."
        )

    if require_verification_result is None:
        require_verification_result = (
            normalized_expected_stage == AgentName.ENGINEER_EXECUTION_REVIEWER
        )

    if require_verification_result:
        verification_result = val_record.verification_result
        if verification_result is None:
            return (
                "validation_results.json is missing runtime verification summary; "
                "run /benchmark/verify before requesting review approval."
            )
        if (
            len(verification_result.individual_results)
            != verification_result.num_scenes
        ):
            return (
                "runtime verification summary is invalid: individual_results count "
                "does not match num_scenes."
            )
        computed_success_count = sum(
            1 for result in verification_result.individual_results if result.success
        )
        if computed_success_count != verification_result.success_count:
            return (
                "runtime verification summary is invalid: success_count does not "
                "match individual_results."
            )
        if verification_result.num_scenes > 0:
            computed_success_rate = (
                computed_success_count / verification_result.num_scenes
            )
            if abs(computed_success_rate - verification_result.success_rate) > 1e-9:
                return (
                    "runtime verification summary is invalid: success_rate does not "
                    "match success_count / num_scenes."
                )
        if not verification_result.batched_execution:
            return (
                "runtime verification summary is invalid: batched_execution must "
                "be true."
            )
        if verification_result.scene_build_count != 1:
            return (
                "runtime verification summary is invalid: scene_build_count must "
                "be 1 for a batched verification result."
            )
        if verification_result.backend_run_count != 1:
            return (
                "runtime verification summary is invalid: backend_run_count must "
                "be 1 for a batched verification result."
            )
        if verification_result.success_rate < MIN_RUNTIME_JITTER_SUCCESS_RATE:
            return (
                "runtime verification is not robust enough for approval: "
                f"success_rate={verification_result.success_rate:.2f} "
                f"below threshold={MIN_RUNTIME_JITTER_SUCCESS_RATE:.2f}."
            )
        if verification_result.num_scenes <= 0:
            return "runtime verification summary is invalid: num_scenes must be > 0."

    try:
        sim_raw = await worker_client.read_file_optional("simulation_result.json")
        if sim_raw is None:
            return "simulation_result.json missing."
        sim_result = SimulationResult.model_validate_json(sim_raw)
    except Exception as e:
        return f"simulation_result.json invalid: {e}"

    if not sim_result.success or not review_manifest.simulation_success:
        return "simulation gate failed for latest revision."
    if expected_stage == AgentName.BENCHMARK_REVIEWER:
        if review_manifest.motion_evidence_verified is not True:
            return (
                "review manifest indicates benchmark motion evidence was not verified."
            )
        benchmark_cross_contract_error = (
            await validate_planner_artifacts_cross_contract(
                worker_client,
                expected_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
            )
        )
        if benchmark_cross_contract_error is not None:
            return benchmark_cross_contract_error
    else:
        if not _goal_reached(sim_result.summary):
            return "simulation did not reach objective (green/goal zone)."
        if not review_manifest.goal_reached:
            return "review manifest indicates goal not reached."

        if not _goal_reached(review_manifest.simulation_summary):
            return (
                "review manifest simulation summary does not confirm goal completion."
            )

    return None


async def validate_approved_benchmark_bundle(
    worker_client: WorkerClient,
    *,
    benchmark_episode_id: str,
) -> tuple[ApprovedBenchmarkBundle | None, str | None]:
    """Validate an approved benchmark bundle and return its manifest payload."""
    normalized_episode_id = str(benchmark_episode_id or "").strip()
    if not normalized_episode_id:
        return None, "benchmark_id is missing."

    try:
        benchmark_uuid = uuid.UUID(normalized_episode_id)
    except Exception as exc:
        return None, f"benchmark_id is invalid: {exc}"

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        episode = await db.get(Episode, benchmark_uuid)
        if episode is None:
            return None, f"benchmark episode {normalized_episode_id} not found."

        metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
        if metadata.episode_type and metadata.episode_type != EpisodeType.BENCHMARK:
            return (
                None,
                f"episode {normalized_episode_id} is not a benchmark episode.",
            )
        if episode.status != EpisodeStatus.COMPLETED:
            return (
                None,
                f"benchmark episode {normalized_episode_id} is not approved; "
                f"status={episode.status}.",
            )
        if metadata.detailed_status != EpisodeStatus.COMPLETED.value:
            return (
                None,
                "benchmark episode detailed_status is not COMPLETED.",
            )
        if metadata.terminal_reason != TerminalReason.APPROVED:
            return (
                None,
                "benchmark episode terminal_reason is not APPROVED.",
            )

        benchmark_worker_session_id = (
            metadata.worker_session_id or ""
        ).strip() or normalized_episode_id

    manifest, manifest_error = await _load_review_manifest(
        worker_client,
        manifest_path=".manifests/benchmark_review_manifest.json",
        submission_helper_name="submit_benchmark_for_review",
        require_git_revision=True,
    )
    if manifest_error is not None:
        return None, f"approved benchmark bundle invalid: {manifest_error}"
    assert manifest is not None
    if manifest.reviewer_stage != AgentName.BENCHMARK_REVIEWER:
        return (
            None,
            "approved benchmark bundle invalid: benchmark review manifest stage "
            f"mismatch: expected benchmark_reviewer, got {manifest.reviewer_stage}.",
        )
    if manifest.session_id.strip().lower() != benchmark_worker_session_id.lower():
        return (
            None,
            "approved benchmark bundle invalid: review manifest session does not "
            "match the approved benchmark session.",
        )
    if (
        manifest.episode_id
        and manifest.episode_id.strip().lower() != normalized_episode_id.lower()
    ):
        return (
            None,
            "approved benchmark bundle invalid: review manifest episode does not "
            "match the approved benchmark episode.",
        )
    if (
        manifest.benchmark_worker_session_id
        and manifest.benchmark_worker_session_id.strip().lower()
        != benchmark_worker_session_id.lower()
    ):
        return (
            None,
            "approved benchmark bundle invalid: review manifest benchmark session "
            "does not match the approved benchmark session.",
        )

    return (
        ApprovedBenchmarkBundle(
            benchmark_episode_id=normalized_episode_id,
            benchmark_worker_session_id=benchmark_worker_session_id,
            review_manifest=manifest,
        ),
        None,
    )


async def validate_plan_reviewer_handover(
    worker_client: WorkerClient,
    *,
    manifest_path: str = ".manifests/engineering_plan_review_manifest.json",
    expected_stage: PlanReviewerStage | str = AgentName.ENGINEER_PLAN_REVIEWER,
) -> str | None:
    """Validate planner-to-plan-reviewer handoff using stage-specific manifest."""
    normalized_expected_stage = _normalize_reviewer_stage(expected_stage)
    try:
        manifest_raw = await worker_client.read_file_optional(
            manifest_path,
            bypass_agent_permissions=True,
        )
        if manifest_raw is None:
            return (
                f"{manifest_path} missing; call "
                f"{_planner_submission_helper_name_for_stage(normalized_expected_stage)}() first."
            )
        manifest = PlanReviewManifest.model_validate_json(manifest_raw)
    except Exception as e:
        return f"{manifest_path} invalid: {e}"

    if manifest.status != "ready_for_review":
        return "plan review manifest status is not ready_for_review."
    if manifest.reviewer_stage != normalized_expected_stage:
        return (
            f"plan review manifest stage mismatch: expected {normalized_expected_stage}, "
            f"got {manifest.reviewer_stage}."
        )

    if not manifest.artifact_hashes:
        return "plan review manifest has no artifact_hashes."

    for rel_path, expected_hash in manifest.artifact_hashes.items():
        content = await worker_client.read_file_optional(rel_path)
        if content is None:
            if rel_path in {"todo.md", "manufacturing_config.yaml"}:
                continue
            return f"planner artifact missing: {rel_path}"
        actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            return (
                f"planner artifact hash mismatch for {rel_path}; "
                f"re-run {_planner_submission_helper_name_for_stage(normalized_expected_stage)}() "
                "for latest planner revision."
            )

    return await validate_planner_artifacts_cross_contract(
        worker_client,
        expected_stage=normalized_expected_stage,
    )


async def validate_planner_artifacts_cross_contract(
    worker_client: WorkerClient,
    *,
    expected_stage: PlanReviewerStage = AgentName.ENGINEER_PLAN_REVIEWER,
) -> str | None:
    """Validate benchmark + assembly planner artifacts without requiring a manifest."""
    benchmark_raw = await worker_client.read_file_optional(
        "benchmark_definition.yaml",
        bypass_agent_permissions=True,
    )
    if benchmark_raw is None:
        return f"benchmark_definition.yaml missing for {expected_stage} handoff."

    assembly_definition_path = (
        "benchmark_assembly_definition.yaml"
        if expected_stage == AgentName.BENCHMARK_PLAN_REVIEWER
        else "assembly_definition.yaml"
    )
    assembly_raw = await worker_client.read_file_optional(
        assembly_definition_path,
        bypass_agent_permissions=True,
    )
    if assembly_raw is None:
        return f"{assembly_definition_path} missing for {expected_stage} handoff."

    try:
        is_valid, benchmark_result = validate_benchmark_definition_yaml(
            benchmark_raw,
            session_id=worker_client.session_id,
        )
        if not is_valid:
            return "planner handoff cross-validation parse failure: " + "; ".join(
                benchmark_result
            )
        benchmark_definition = benchmark_result
        assembly_definition = AssemblyDefinition.model_validate(
            yaml.safe_load(assembly_raw) or {}
        )
    except Exception as e:
        return f"planner handoff cross-validation parse failure: {e}"

    try:
        manufacturing_raw = await worker_client.read_file_optional(
            "manufacturing_config.yaml",
            bypass_agent_permissions=True,
        )
        if manufacturing_raw is not None:
            manufacturing_config = load_required_merged_config(
                override_data=(yaml.safe_load(manufacturing_raw) or {})
            )
        else:
            manufacturing_config = load_required_merged_config()
    except Exception as e:
        return f"planner handoff pricing-config parse failure: {e}"

    plan_artifact_name = plan_path_for_reviewer_stage(expected_stage).as_posix()
    plan_text = await worker_client.read_file_optional(
        plan_artifact_name,
        bypass_agent_permissions=True,
    )
    files_content_map: dict[str, str] | None = None
    if expected_stage == AgentName.ENGINEER_PLAN_REVIEWER:
        files_content_map = {}
        benchmark_script = await worker_client.read_file_optional(
            BENCHMARK_SCRIPT_PATH,
            bypass_agent_permissions=True,
        )
        if benchmark_script is not None:
            files_content_map[BENCHMARK_SCRIPT_PATH] = benchmark_script
        solution_plan_evidence_script = await worker_client.read_file_optional(
            SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
            bypass_agent_permissions=True,
        )
        if solution_plan_evidence_script is not None:
            files_content_map[SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH] = (
                solution_plan_evidence_script
            )
    cross_contract_errors = validate_planner_handoff_cross_contract(
        benchmark_definition=benchmark_definition,
        assembly_definition=assembly_definition,
        manufacturing_config=manufacturing_config,
        artifact_name="benchmark_assembly_definition.yaml",
        planner_node_type=expected_stage,
        files_content_map=files_content_map,
        plan_text=plan_text,
        session_id=worker_client.session_id,
    )
    if cross_contract_errors:
        return "; ".join(cross_contract_errors)

    if expected_stage == AgentName.BENCHMARK_PLAN_REVIEWER:
        plan_text = None
        todo_text = None
        plan_refusal_text = await worker_client.read_file_optional("plan_refusal.md")
        plan_text = await worker_client.read_file_optional(plan_artifact_name)
        todo_text = await worker_client.read_file_optional("todo.md")
        motion_errors = validate_benchmark_assembly_payload_contract(
            benchmark_definition=benchmark_definition,
            assembly_definition=assembly_definition,
            plan_text=plan_text,
            todo_text=todo_text,
            plan_refusal_text=plan_refusal_text,
        )
        if motion_errors:
            return "; ".join(motion_errors)

    return None
