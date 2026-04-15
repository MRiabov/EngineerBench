from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, model_validator

from controller.agent.benchmark_handover_validation import (
    extract_benchmark_refusal_reason,
    extract_custom_objectives_from_state,
    validate_benchmark_planner_handoff_artifacts,
)
from controller.agent.config import settings as agent_settings
from controller.agent.handover_constants import (
    BENCHMARK_CODER_HANDOVER_CHECK,
    BENCHMARK_PLAN_REVIEW_MANIFEST,
    BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK,
    BENCHMARK_PLANNER_HANDOFF_ARTIFACTS,
    BENCHMARK_REVIEWER_HANDOVER_CHECK,
    ENGINEER_BENCHMARK_CONTEXT_ARTIFACTS,
    ENGINEER_BENCHMARK_HANDOVER_CHECK,
    ENGINEER_BENCHMARK_SOURCE_ARTIFACTS,
    ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK,
    ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK,
    ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK,
    ENGINEER_PLANNER_HANDOFF_ARTIFACTS,
    ENGINEERING_EXECUTION_HANDOFF_MANIFEST,
    ENGINEERING_EXECUTION_REVIEWER_HANDOFF_ARTIFACTS,
    ENGINEERING_PLAN_REVIEW_MANIFEST,
    SCHEMA_BACKED_HANDOFF_PATHS,
)
from controller.agent.render_validation import validate_render_images_non_black
from controller.agent.review_handover import (
    collect_plan_reviewer_handover_evidence,
    validate_approved_benchmark_bundle,
    validate_plan_reviewer_handover,
    validate_planner_artifacts_cross_contract,
    validate_reviewer_handover,
)
from controller.clients.worker import WorkerClient
from controller.config.settings import settings as controller_settings
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Episode
from shared.agent_templates import load_seed_starter_template_files
from shared.current_role import current_role_manifest_json, parse_current_role_manifest
from shared.enums import AgentName, EntryFailureDisposition, EntryValidationSource
from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    EpisodeMetadata,
)
from shared.models.simulation import SimulationResult
from shared.script_contracts import (
    BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
    BENCHMARK_SCRIPT_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    SOLUTION_SCRIPT_PATH,
    authored_script_path_for_agent,
    authored_script_path_for_reviewer_stage,
    plan_path_for_agent,
)
from shared.simulation.schemas import CustomObjectives
from shared.utils.agent import (
    simulate_benchmark,
    simulate_engineering,
    validate_benchmark,
    validate_engineering,
)
from shared.workers.loader import load_component_from_script
from shared.workers.markdown_validator import validate_todo_md
from shared.workers.schema import (
    PlanReviewManifest,
    RenderManifest,
    ReviewManifest,
    ValidationResultRecord,
)
from worker_heavy.utils.dfm import load_planner_manufacturing_config_from_text
from worker_heavy.utils.file_validation import (
    validate_assembly_definition_yaml,
    validate_benchmark_assembly_motion_contract,
    validate_benchmark_definition_yaml,
    validate_payload_trajectory_definition_yaml,
    validate_plan_md_structure,
    validate_plan_refusal,
    validate_planner_evidence_script_layout_contract,
    validate_planner_handoff_cross_contract,
)

REASON_OK = "ok"
REASON_STATE_INVALID = "state_invalid"
REASON_MISSING_ARTIFACT = "missing_artifact"
REASON_HANDOVER_INVALID = "handover_invalid"
REASON_REVIEWER_ENTRY_BLOCKED = "reviewer_entry_blocked"
REASON_POLICY_INVALID = "policy_invalid"
REASON_NO_PREVIOUS_NODE = "no_previous_node"
REASON_CUSTOM_CHECK_FAILED = "custom_check_failed"


class ValidationGraph(StrEnum):
    ENGINEER = "engineer"
    BENCHMARK = "benchmark"


class ValidationScope(StrEnum):
    CURRENT_NODE = "current-node"
    CURRENT_AND_PREVIOUS_NODES = "current-and-previous-nodes"
    CURRENT_AND_PREVIOUS_NODES_WITH_HEAVY_SIMULATION = (
        "current-and-previous-nodes-with-heavy-simulation"
    )


@dataclass(frozen=True)
class _SeedValidationGateSpec:
    role: AgentName
    gate_name: str
    artifact_path: str | None
    runner: str


class _LocalSeedWorkspaceClient:
    def __init__(self, root: Path, session_id: str):
        self.root = root
        self.session_id = session_id

    @staticmethod
    def _normalize(path: str | Path) -> Path:
        candidate = str(path or "").strip()
        if candidate in {"", "/", "."}:
            return Path(".")
        normalized = candidate.lstrip("/")
        if normalized.startswith("../") or "/../" in normalized or normalized == "..":
            raise ValueError(f"Path escapes workspace root: {path}")
        return Path(normalized)

    def _resolve(self, path: str | Path) -> Path:
        rel_path = self._normalize(path)
        return self.root / rel_path

    async def exists(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> bool:  # noqa: ARG002
        resolved = self._resolve(path)
        if resolved.exists():
            return True
        rel_prefix = resolved.relative_to(self.root).as_posix().rstrip("/")
        if not rel_prefix:
            return True
        rel_prefix = f"{rel_prefix}/"
        for child in self.root.rglob("*"):
            if child.relative_to(self.root).as_posix().startswith(rel_prefix):
                return True
        return False

    async def read_file(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> str:  # noqa: ARG002
        content = self._resolve(path).read_text(encoding="utf-8")
        return content

    async def read_file_optional(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> str | None:  # noqa: ARG002
        resolved = self._resolve(path)
        if not resolved.exists():
            return None
        try:
            return resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None

    async def read_file_binary(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> bytes:  # noqa: ARG002
        return self._resolve(path).read_bytes()

    async def read_files_binary(
        self,
        paths: list[str],
        *,
        bypass_agent_permissions: bool = False,
    ) -> dict[str, bytes]:  # noqa: ARG002
        blobs: dict[str, bytes] = {}
        for path in paths:
            resolved = self._resolve(path)
            if resolved.exists():
                blobs[path] = resolved.read_bytes()
        return blobs

    async def list_files(
        self, path: str = "/", *, bypass_agent_permissions: bool = False
    ) -> list[SimpleNamespace]:  # noqa: ARG002
        resolved = self._resolve(path)
        if not resolved.exists():
            return []

        directory = resolved if resolved.is_dir() else resolved.parent
        entries: list[SimpleNamespace] = []
        for child in sorted(directory.iterdir()):
            rel_path = child.relative_to(self.root).as_posix()
            entries.append(
                SimpleNamespace(path=rel_path, name=child.name, is_dir=child.is_dir())
            )
        return entries

    async def aclose(self) -> None:
        return None


def _seed_validation_role_manifest(agent_name: AgentName) -> str:
    return current_role_manifest_json(agent_name)


def _seed_validation_workspace_role(target_node: AgentName) -> AgentName:
    if target_node in {
        AgentName.BENCHMARK_PLANNER,
        AgentName.BENCHMARK_PLAN_REVIEWER,
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_REVIEWER,
    }:
        return AgentName.BENCHMARK_CODER
    if target_node in {
        AgentName.ENGINEER_PLANNER,
        AgentName.ENGINEER_PLAN_REVIEWER,
        AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }:
        return AgentName.ENGINEER_CODER
    return target_node


# Static and deterministic by contract. If a node has no previous node, reroute
# is impossible and callers must fail closed.
ENGINEER_PREVIOUS_NODE_MAP: Mapping[AgentName, AgentName | None] = {
    AgentName.ENGINEER_PLANNER: None,
    AgentName.ENGINEER_PLAN_REVIEWER: AgentName.ENGINEER_PLANNER,
    AgentName.ENGINEER_CODER: AgentName.ENGINEER_PLAN_REVIEWER,
    # Execution review failures should route back to coder so latest-revision
    # handover artifacts can be regenerated before another reviewer entry.
    AgentName.ENGINEER_EXECUTION_REVIEWER: AgentName.ENGINEER_CODER,
}

BENCHMARK_PREVIOUS_NODE_MAP: Mapping[AgentName, AgentName | None] = {
    AgentName.BENCHMARK_PLANNER: None,
    AgentName.BENCHMARK_PLAN_REVIEWER: AgentName.BENCHMARK_PLANNER,
    AgentName.BENCHMARK_CODER: AgentName.BENCHMARK_PLAN_REVIEWER,
    AgentName.BENCHMARK_REVIEWER: AgentName.BENCHMARK_CODER,
}

PREVIOUS_NODE_MAPS: Mapping[ValidationGraph, Mapping[AgentName, AgentName | None]] = {
    ValidationGraph.ENGINEER: ENGINEER_PREVIOUS_NODE_MAP,
    ValidationGraph.BENCHMARK: BENCHMARK_PREVIOUS_NODE_MAP,
}

_TRANSIENT_BUSY_BASE_DELAY_SECONDS = 1.0
_TRANSIENT_BUSY_MAX_WAIT_SECONDS = 180.0


class NodeEntryValidationError(BaseModel):
    code: str
    message: str
    source: EntryValidationSource
    artifact_path: str | None = None


class NodeEntryValidationResult(BaseModel):
    ok: bool
    target_node: AgentName
    disposition: EntryFailureDisposition
    errors: list[NodeEntryValidationError] = Field(default_factory=list)
    reroute_target: AgentName | None = None
    reason_code: str = REASON_OK

    @model_validator(mode="after")
    def validate_contract(self) -> NodeEntryValidationResult:
        if self.ok:
            if self.disposition != EntryFailureDisposition.ALLOW:
                msg = "ok=true requires disposition=allow"
                raise ValueError(msg)
            if self.errors:
                raise ValueError("ok=true requires errors=[]")
            if self.reroute_target is not None:
                raise ValueError("ok=true requires reroute_target=None")
        else:
            if not self.errors:
                raise ValueError("ok=false requires at least one error")
            if (
                self.disposition == EntryFailureDisposition.REROUTE_PREVIOUS
                and self.reroute_target is None
            ):
                raise ValueError("disposition=reroute_previous requires reroute_target")
        return self


class NodeEntryContract(BaseModel):
    node: AgentName
    required_state_fields: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    custom_check: str | None = None
    integration_failure_policy: EntryFailureDisposition = (
        EntryFailureDisposition.FAIL_FAST
    )


_ENGINEER_DRAFTING_TARGETS = {
    AgentName.ENGINEER_PLANNER,
    AgentName.ENGINEER_PLAN_REVIEWER,
    AgentName.ENGINEER_CODER,
    AgentName.ENGINEER_EXECUTION_REVIEWER,
}

_RENDER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_RENDER_EVIDENCE_EXTENSIONS = _RENDER_IMAGE_EXTENSIONS | {".mp4"}


def _benchmark_planner_entry_artifacts() -> list[str]:
    """Artifacts the benchmark planner needs before it can start planning."""
    return [
        "todo.md",
        "benchmark_definition.yaml",
        "benchmark_assembly_definition.yaml",
        BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
    ]


def _engineer_planner_entry_artifacts() -> list[str]:
    """Artifacts the engineering planner needs before it can start planning."""
    return [
        "todo.md",
        "benchmark_definition.yaml",
        "assembly_definition.yaml",
        "benchmark_assembly_definition.yaml",
        "benchmark_script.py",
        SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    ]


async def _validate_payload_trajectory_clearance_on_worker(
    worker_client: WorkerClient,
) -> list[NodeEntryValidationError]:
    command = r"""
python3 - <<'PY'
import json
from pathlib import Path

import yaml

from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
)
from worker_heavy.utils.file_validation import (
    validate_payload_trajectory_definition_yaml,
)

root = Path.cwd()
benchmark = BenchmarkDefinition.model_validate(
    yaml.safe_load((root / "benchmark_definition.yaml").read_text(encoding="utf-8"))
)
assembly = AssemblyDefinition.model_validate(
    yaml.safe_load((root / "assembly_definition.yaml").read_text(encoding="utf-8"))
)
benchmark_assembly_path = root / "benchmark_assembly_definition.yaml"
benchmark_assembly = (
    AssemblyDefinition.model_validate(
        yaml.safe_load(
            benchmark_assembly_path.read_text(encoding="utf-8")
        )
    )
    if benchmark_assembly_path.exists()
    else None
)
payload_text = (root / "payload_trajectory_definition.yaml").read_text(
    encoding="utf-8"
)
ok, result = validate_payload_trajectory_definition_yaml(
    payload_text,
    benchmark_definition=benchmark,
    assembly_definition=assembly,
    benchmark_assembly_definition=benchmark_assembly,
    workspace_root=root,
    validate_clearance=True,
)
print(
    json.dumps(
        {
            "ok": ok,
            "errors": result if isinstance(result, list) else [],
        },
        ensure_ascii=False,
    )
)
PY
"""
    response = await worker_client.execute_command(command, timeout=300)
    if response.exit_code != 0:
        return [
            _seeded_schema_error(
                message=(
                    "payload_trajectory_definition.yaml: worker clearance "
                    f"validation failed: {response.stderr or response.stdout}"
                ),
                artifact_path="payload_trajectory_definition.yaml",
            )
        ]

    try:
        stdout_lines = [
            line.strip()
            for line in (response.stdout or "").splitlines()
            if line.strip()
        ]
        payload = json.loads(stdout_lines[-1] if stdout_lines else "{}")
    except Exception as exc:
        return [
            _seeded_schema_error(
                message=(
                    "payload_trajectory_definition.yaml: unable to parse worker "
                    f"clearance output: {exc}"
                ),
                artifact_path="payload_trajectory_definition.yaml",
            )
        ]

    if payload.get("ok"):
        return []

    return [
        _seeded_schema_error(
            message=message,
            artifact_path="payload_trajectory_definition.yaml",
        )
        for message in payload.get("errors", [])
    ]


def build_benchmark_node_contracts() -> dict[AgentName, NodeEntryContract]:
    # Scope boundary: contracts apply only to first-class graph transitions.
    # Tool-invoked helper subagents are explicitly out of scope for this registry.
    return {
        AgentName.BENCHMARK_PLANNER: NodeEntryContract(
            node=AgentName.BENCHMARK_PLANNER,
            required_state_fields=["session", "episode_id"],
            required_artifacts=_benchmark_planner_entry_artifacts(),
        ),
        AgentName.BENCHMARK_PLAN_REVIEWER: NodeEntryContract(
            node=AgentName.BENCHMARK_PLAN_REVIEWER,
            required_state_fields=["session", "episode_id"],
            required_artifacts=BENCHMARK_PLANNER_HANDOFF_ARTIFACTS,
            custom_check=BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK,
        ),
        AgentName.BENCHMARK_CODER: NodeEntryContract(
            node=AgentName.BENCHMARK_CODER,
            required_state_fields=["session", "episode_id"],
            required_artifacts=[
                *BENCHMARK_PLANNER_HANDOFF_ARTIFACTS,
                BENCHMARK_SCRIPT_PATH,
            ],
            custom_check=BENCHMARK_CODER_HANDOVER_CHECK,
        ),
        AgentName.BENCHMARK_REVIEWER: NodeEntryContract(
            node=AgentName.BENCHMARK_REVIEWER,
            required_state_fields=["session", "episode_id"],
            required_artifacts=[BENCHMARK_SCRIPT_PATH],
            custom_check=BENCHMARK_REVIEWER_HANDOVER_CHECK,
        ),
    }


def build_engineer_node_contracts() -> dict[AgentName, NodeEntryContract]:
    # Scope boundary: only first-class orchestration nodes are entry-guarded.
    return {
        AgentName.ENGINEER_PLANNER: NodeEntryContract(
            node=AgentName.ENGINEER_PLANNER,
            required_state_fields=["task", "episode_id"],
            required_artifacts=_engineer_planner_entry_artifacts(),
            custom_check=ENGINEER_BENCHMARK_HANDOVER_CHECK,
        ),
        AgentName.ENGINEER_PLAN_REVIEWER: NodeEntryContract(
            node=AgentName.ENGINEER_PLAN_REVIEWER,
            required_state_fields=["episode_id"],
            required_artifacts=list(ENGINEER_BENCHMARK_CONTEXT_ARTIFACTS),
            custom_check=ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK,
        ),
        AgentName.ENGINEER_CODER: NodeEntryContract(
            node=AgentName.ENGINEER_CODER,
            required_state_fields=["episode_id"],
            required_artifacts=[
                *ENGINEER_PLANNER_HANDOFF_ARTIFACTS,
                *ENGINEER_BENCHMARK_SOURCE_ARTIFACTS,
            ],
            custom_check=ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK,
        ),
        AgentName.ENGINEER_EXECUTION_REVIEWER: NodeEntryContract(
            node=AgentName.ENGINEER_EXECUTION_REVIEWER,
            required_state_fields=["episode_id"],
            required_artifacts=list(ENGINEERING_EXECUTION_REVIEWER_HANDOFF_ARTIFACTS),
            custom_check=ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK,
        ),
    }


async def reviewer_handover_custom_check_from_session_id(
    *,
    session_id: str | None,
    reviewer_label: str,
    manifest_path: str,
    expected_stage: AgentName,
    agent_role: AgentName | None = None,
    worker_client: Any | None = None,
) -> list[NodeEntryValidationError]:
    normalized_session_id = (session_id or "").strip()
    if not normalized_session_id:
        return [
            NodeEntryValidationError(
                code=REASON_REVIEWER_ENTRY_BLOCKED,
                message=(
                    f"{reviewer_label} reviewer handover check failed: "
                    "missing session_id."
                ),
                source=EntryValidationSource.HANDOVER,
            )
        ]

    owns_client = worker_client is None
    client = worker_client or WorkerClient(
        base_url=controller_settings.worker_light_url,
        heavy_url=controller_settings.worker_heavy_url,
        session_id=normalized_session_id,
        agent_role=agent_role or AgentName.ENGINEER_CODER,
    )
    try:
        handover_error = await validate_reviewer_handover(
            client,
            manifest_path=manifest_path,
            expected_stage=expected_stage,
            require_git_revision=True,
        )
    except Exception as exc:
        handover_error = f"reviewer handover validation exception: {exc}"
    finally:
        if owns_client:
            await client.aclose()

    if handover_error is None:
        return []

    return [
        NodeEntryValidationError(
            code=REASON_REVIEWER_ENTRY_BLOCKED,
            message=f"{reviewer_label} reviewer entry blocked: {handover_error}",
            source=EntryValidationSource.HANDOVER,
            artifact_path=manifest_path,
        )
    ]


async def benchmark_coder_handover_custom_check_from_session_id(
    *,
    session_id: str | None,
    custom_objectives: CustomObjectives | None = None,
    worker_client: Any | None = None,
) -> list[NodeEntryValidationError]:
    normalized_session_id = (session_id or "").strip()
    if not normalized_session_id:
        return [
            NodeEntryValidationError(
                code=REASON_HANDOVER_INVALID,
                message="Benchmark coder handover check failed: missing session_id.",
                source=EntryValidationSource.HANDOVER,
            )
        ]

    owns_client = worker_client is None
    client = worker_client or WorkerClient(
        base_url=controller_settings.worker_light_url,
        heavy_url=controller_settings.worker_heavy_url,
        session_id=normalized_session_id,
        agent_role=AgentName.BENCHMARK_CODER,
    )
    try:
        handoff_errors = await validate_benchmark_planner_handoff_artifacts(
            client,
            custom_objectives=custom_objectives,
        )
    except Exception as exc:
        handoff_errors = [f"benchmark planner handoff validation exception: {exc}"]
    finally:
        if owns_client:
            await client.aclose()

    return _benchmark_validation_errors(
        messages=handoff_errors,
        message_prefix="Benchmark coder entry blocked: ",
        artifact_path=None,
    )


async def benchmark_plan_reviewer_handover_custom_check_from_session_id(
    *,
    session_id: str | None,
    episode_id: str | None = None,
    worker_client: Any | None = None,
) -> list[NodeEntryValidationError]:
    normalized_session_id = (session_id or "").strip()
    if not normalized_session_id:
        return [
            NodeEntryValidationError(
                code=REASON_REVIEWER_ENTRY_BLOCKED,
                message=(
                    "Benchmark plan reviewer handover check failed: missing session_id."
                ),
                source=EntryValidationSource.HANDOVER,
                artifact_path=BENCHMARK_PLAN_REVIEW_MANIFEST,
            )
        ]

    owns_client = worker_client is None
    client = worker_client or WorkerClient(
        base_url=controller_settings.worker_light_url,
        heavy_url=controller_settings.worker_heavy_url,
        session_id=normalized_session_id,
        agent_role=AgentName.BENCHMARK_PLAN_REVIEWER,
    )
    evidence = None
    try:
        evidence, _ = await collect_plan_reviewer_handover_evidence(
            client,
            manifest_path=BENCHMARK_PLAN_REVIEW_MANIFEST,
            expected_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
            episode_id=episode_id,
        )
        handover_error = await validate_plan_reviewer_handover(
            client,
            manifest_path=BENCHMARK_PLAN_REVIEW_MANIFEST,
            expected_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
        )
    except Exception as exc:
        handover_error = f"plan reviewer handover validation exception: {exc}"
    finally:
        if owns_client:
            await client.aclose()

    if handover_error is None:
        return []

    if evidence is not None:
        evidence_bits = [
            f"revision={evidence.review_manifest_revision or 'unknown'}",
            f"renders={evidence.render_count}",
        ]
        if evidence.refusal_reason is not None:
            evidence_bits.append(f"refusal_reason={evidence.refusal_reason.value}")
        if evidence.deterministic_errors:
            evidence_bits.append(
                "deterministic_errors=" + " | ".join(evidence.deterministic_errors[:3])
            )
        handover_error = f"{handover_error} | evidence: {'; '.join(evidence_bits)}"

    return _benchmark_validation_errors(
        messages=[handover_error],
        message_prefix="Benchmark plan reviewer entry blocked: ",
        artifact_path=BENCHMARK_PLAN_REVIEW_MANIFEST,
        default_code=REASON_REVIEWER_ENTRY_BLOCKED,
    )


async def benchmark_plan_reviewer_handover_custom_check(
    *,
    contract: NodeEntryContract,  # noqa: ARG001
    state: BaseModel | Mapping[str, Any],
) -> list[NodeEntryValidationError]:
    worker_session_id = _get_state_value(state, "worker_session_id")
    session = _get_state_value(state, "session")
    if isinstance(session, Mapping):
        session_id = session.get("session_id")
    else:
        session_id = getattr(session, "session_id", None)
    workspace_client = _get_state_worker_client(state)
    return await benchmark_plan_reviewer_handover_custom_check_from_session_id(
        session_id=str(worker_session_id or session_id)
        if worker_session_id or session_id
        else None,
        episode_id=str(_get_state_value(state, "episode_id"))
        if _get_state_value(state, "episode_id")
        else None,
        worker_client=workspace_client,
    )


async def benchmark_coder_handover_custom_check(
    *,
    contract: NodeEntryContract,  # noqa: ARG001
    state: BaseModel | Mapping[str, Any],
) -> list[NodeEntryValidationError]:
    worker_session_id = _get_state_value(state, "worker_session_id")
    session = _get_state_value(state, "session")
    if isinstance(session, Mapping):
        session_id = session.get("session_id")
    else:
        session_id = getattr(session, "session_id", None)
    workspace_client = _get_state_worker_client(state)
    return await benchmark_coder_handover_custom_check_from_session_id(
        session_id=str(worker_session_id or session_id)
        if worker_session_id or session_id
        else None,
        custom_objectives=extract_custom_objectives_from_state(state),
        worker_client=workspace_client,
    )


async def engineer_benchmark_handover_custom_check(
    *,
    contract: NodeEntryContract,  # noqa: ARG001
    state: BaseModel | Mapping[str, Any],
) -> list[NodeEntryValidationError]:
    worker_session_id = _get_state_value(
        state, "worker_session_id"
    ) or _get_state_value(state, "session_id")
    episode_id = _get_state_value(state, "episode_id")
    if not worker_session_id:
        return [
            NodeEntryValidationError(
                code=REASON_HANDOVER_INVALID,
                message=(
                    "Engineer benchmark handover check failed: missing session_id."
                ),
                source=EntryValidationSource.HANDOVER,
                artifact_path="benchmark_definition.yaml",
            )
        ]
    if not episode_id:
        return [
            NodeEntryValidationError(
                code=REASON_STATE_INVALID,
                message=(
                    "Engineer benchmark handover check failed: missing episode_id."
                ),
                source=EntryValidationSource.STATE,
            )
        ]

    try:
        episode_uuid = uuid.UUID(str(episode_id).strip())
    except Exception:
        return [
            NodeEntryValidationError(
                code=REASON_STATE_INVALID,
                message=(
                    "Engineer benchmark handover check failed: invalid episode_id."
                ),
                source=EntryValidationSource.STATE,
            )
        ]

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        episode = await db.get(Episode, episode_uuid)
        if episode is None:
            return [
                NodeEntryValidationError(
                    code=REASON_HANDOVER_INVALID,
                    message=(
                        "Engineer benchmark handover check failed: episode not found."
                    ),
                    source=EntryValidationSource.HANDOVER,
                    artifact_path="benchmark_definition.yaml",
                )
            ]
        metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
        benchmark_episode_id = (metadata.benchmark_id or "").strip()

    if not benchmark_episode_id:
        return []

    client = WorkerClient(
        base_url=controller_settings.worker_light_url,
        heavy_url=controller_settings.worker_heavy_url,
        session_id=str(worker_session_id),
        agent_role=AgentName.ENGINEER_PLANNER,
    )
    try:
        bundle, bundle_error = await validate_approved_benchmark_bundle(
            client,
            benchmark_episode_id=benchmark_episode_id,
        )
    except Exception as exc:
        bundle = None
        bundle_error = f"approved benchmark bundle validation exception: {exc}"
    finally:
        await client.aclose()

    if bundle_error is None and bundle is not None:
        return []

    return [
        NodeEntryValidationError(
            code=REASON_HANDOVER_INVALID,
            message=(
                "Engineer benchmark entry blocked: "
                f"{bundle_error or 'approved benchmark bundle invalid.'}"
            ),
            source=EntryValidationSource.HANDOVER,
            artifact_path="benchmark_definition.yaml",
        )
    ]


async def engineer_planner_evidence_layout_custom_check(
    *,
    contract: NodeEntryContract,  # noqa: ARG001
    state: BaseModel | Mapping[str, Any],
) -> list[NodeEntryValidationError]:
    worker_session_id = _get_state_value(state, "worker_session_id")
    session = _get_state_value(state, "session")
    if isinstance(session, Mapping):
        session_id = session.get("session_id")
    else:
        session_id = getattr(session, "session_id", None)
    normalized_session_id = str(worker_session_id or session_id or "").strip()
    if not normalized_session_id:
        return [
            NodeEntryValidationError(
                code=REASON_HANDOVER_INVALID,
                message=(
                    "Engineer planner evidence-layout check failed: missing session_id."
                ),
                source=EntryValidationSource.HANDOVER,
                artifact_path=SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
            )
        ]

    workspace_client = _get_state_worker_client(state)
    owns_client = workspace_client is None
    client = workspace_client or WorkerClient(
        base_url=controller_settings.worker_light_url,
        heavy_url=controller_settings.worker_heavy_url,
        session_id=normalized_session_id,
        agent_role=AgentName.ENGINEER_PLANNER,
    )
    try:
        evidence_script_content = await client.read_file_optional(
            SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH
        )
    except Exception as exc:
        evidence_script_content = None
        read_error = f"solution plan evidence script read failed: {exc}"
    else:
        read_error = None
    finally:
        if owns_client:
            await client.aclose()

    if read_error is not None:
        return [
            NodeEntryValidationError(
                code=REASON_HANDOVER_INVALID,
                message=f"Engineer planner entry blocked: {read_error}",
                source=EntryValidationSource.HANDOVER,
                artifact_path=SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
            )
        ]

    if evidence_script_content is None:
        return []

    layout_errors = validate_planner_evidence_script_layout_contract(
        artifact_name=SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
        content=evidence_script_content,
    )
    return [
        NodeEntryValidationError(
            code=REASON_HANDOVER_INVALID,
            message=error,
            source=EntryValidationSource.HANDOVER,
            artifact_path=SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
        )
        for error in layout_errors
    ]


async def plan_reviewer_handover_custom_check_from_session_id(
    *,
    session_id: str | None,
    worker_client: Any | None = None,
) -> list[NodeEntryValidationError]:
    normalized_session_id = (session_id or "").strip()
    if not normalized_session_id:
        return [
            NodeEntryValidationError(
                code=REASON_REVIEWER_ENTRY_BLOCKED,
                message="Plan reviewer handover check failed: missing session_id.",
                source=EntryValidationSource.HANDOVER,
            )
        ]

    owns_client = worker_client is None
    client = worker_client or WorkerClient(
        base_url=controller_settings.worker_light_url,
        heavy_url=controller_settings.worker_heavy_url,
        session_id=normalized_session_id,
        agent_role=AgentName.ENGINEER_PLAN_REVIEWER,
    )
    try:
        handover_error = await validate_plan_reviewer_handover(
            client,
            manifest_path=ENGINEERING_PLAN_REVIEW_MANIFEST,
        )
    except Exception as exc:
        handover_error = f"plan reviewer handover validation exception: {exc}"
    finally:
        if owns_client:
            await client.aclose()

    if handover_error is None:
        return []

    return [
        NodeEntryValidationError(
            code=REASON_REVIEWER_ENTRY_BLOCKED,
            message=f"Plan reviewer entry blocked: {handover_error}",
            source=EntryValidationSource.HANDOVER,
            artifact_path=ENGINEERING_PLAN_REVIEW_MANIFEST,
        )
    ]


async def _materialize_reviewer_handover(
    client: WorkerClient,
    *,
    reviewer_stage: AgentName = AgentName.ENGINEER_EXECUTION_REVIEWER,
    episode_id: str | None = None,
) -> str | None:
    if reviewer_stage == AgentName.ENGINEER_EXECUTION_REVIEWER:
        try:
            existing_handover_error = await validate_reviewer_handover(
                client,
                manifest_path=ENGINEERING_EXECUTION_HANDOFF_MANIFEST,
                expected_stage=reviewer_stage,
            )
        except Exception:
            existing_handover_error = "unknown reviewer handover validation error"
        else:
            if existing_handover_error is None:
                return None

    async def _run_with_transient_busy_retry(operation_name: str, coro_factory):
        deadline = asyncio.get_running_loop().time() + _TRANSIENT_BUSY_MAX_WAIT_SECONDS
        last_exc: Exception | None = None
        attempt = 0
        while True:
            try:
                return await coro_factory()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response else None
                if status_code != 503:
                    raise
                last_exc = exc
                if asyncio.get_running_loop().time() >= deadline:
                    raise
                while asyncio.get_running_loop().time() < deadline:
                    try:
                        if await client.heavy_ready():
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)
                else:
                    raise
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                if asyncio.get_running_loop().time() >= deadline:
                    raise
                last_exc = exc
                await asyncio.sleep(
                    min(
                        _TRANSIENT_BUSY_BASE_DELAY_SECONDS * float(attempt + 1),
                        5.0,
                    )
                )
            except Exception:
                raise
            attempt += 1

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{operation_name} failed without exception")

    script_path = authored_script_path_for_reviewer_stage(reviewer_stage)
    if not await client.exists(script_path):
        return f"{script_path} missing; cannot materialize review handover."

    try:
        validate_result = await _run_with_transient_busy_retry(
            "validate",
            lambda: client.validate(script_path),
        )
    except Exception as exc:
        return f"validate failed while materializing handover: {exc}"
    if not validate_result.success:
        return (
            "validate failed while materializing handover: "
            f"{validate_result.message or 'unknown validation failure'}"
        )

    try:
        simulate_result = await _run_with_transient_busy_retry(
            "simulate",
            lambda: client.simulate(script_path),
        )
    except Exception as exc:
        return f"simulate failed while materializing handover: {exc}"
    if not simulate_result.success:
        return (
            "simulate failed while materializing handover: "
            f"{simulate_result.message or 'unknown simulation failure'}"
        )

    try:
        verify_result = await _run_with_transient_busy_retry(
            "verify",
            lambda: client.verify(
                script_path,
                num_scenes=1 if controller_settings.is_integration_test else None,
                duration=1.0 if controller_settings.is_integration_test else None,
                smoke_test_mode=controller_settings.is_integration_test,
            ),
        )
    except Exception as exc:
        return f"verify failed while materializing handover: {exc}"
    if not verify_result.success:
        return (
            "verify failed while materializing handover: "
            f"{verify_result.message or 'unknown verification failure'}"
        )

    try:
        submit_result = await _run_with_transient_busy_retry(
            "submit",
            lambda: client.submit(
                script_path,
                reviewer_stage=reviewer_stage,
                episode_id=episode_id,
            ),
        )
    except Exception as exc:
        return f"submit_for_review failed while materializing handover: {exc}"
    if not submit_result.success:
        return (
            "submit_for_review failed while materializing handover: "
            f"{submit_result.message or 'unknown submit failure'}"
        )

    return None


def _plan_type_for_target(target_node: AgentName, plan_content: str) -> str:
    if "benchmark" in target_node.value or "# Learning Objective" in plan_content:
        return "benchmark"
    return "engineering"


def _seeded_schema_error(
    *,
    message: str,
    artifact_path: str | None = None,
    default_code: str = REASON_HANDOVER_INVALID,
) -> NodeEntryValidationError:
    reason = extract_benchmark_refusal_reason(message)
    return NodeEntryValidationError(
        code=reason.value if reason is not None else default_code,
        message=message,
        source=EntryValidationSource.HANDOVER,
        artifact_path=artifact_path,
    )


async def _seeded_starter_template_errors(
    *,
    worker_client: Any,
    target_node: AgentName,
) -> list[NodeEntryValidationError]:
    starter_templates = load_seed_starter_template_files(target_node)
    if not starter_templates:
        return []

    errors: list[NodeEntryValidationError] = []
    for rel_path, expected_content in starter_templates.items():
        try:
            actual_content = await worker_client.read_file_optional(
                rel_path,
                bypass_agent_permissions=True,
            )
        except Exception as exc:
            errors.append(
                _seeded_schema_error(
                    message=f"{rel_path}: starter template read failed: {exc}",
                    artifact_path=rel_path,
                )
            )
            continue

        if actual_content is None:
            errors.append(
                _seeded_schema_error(
                    message=f"{rel_path}: seeded workspace is missing the starter template baseline.",
                    artifact_path=rel_path,
                )
            )
            continue

        if actual_content != expected_content:
            errors.append(
                _seeded_schema_error(
                    message=(
                        f"{rel_path}: seeded workspace must begin from the starter "
                        "template version, not a pre-solved output."
                    ),
                    artifact_path=rel_path,
                )
            )

    return errors


def _benchmark_validation_errors(
    *,
    messages: Sequence[str],
    message_prefix: str,
    artifact_path: str | None = None,
    default_code: str = REASON_HANDOVER_INVALID,
) -> list[NodeEntryValidationError]:
    refusal_errors: list[NodeEntryValidationError] = []
    fallback_errors: list[NodeEntryValidationError] = []
    for message in messages:
        prefixed_message = f"{message_prefix}{message}"
        error = _seeded_schema_error(
            message=prefixed_message,
            artifact_path=artifact_path,
            default_code=default_code,
        )
        if error.code == default_code:
            fallback_errors.append(error)
        else:
            refusal_errors.append(error)
    return refusal_errors + fallback_errors


@contextlib.contextmanager
def _seed_validation_workspace_env(root: Path) -> Any:
    old_values = {
        "WORKER_SESSIONS_DIR": os.environ.get("WORKER_SESSIONS_DIR"),
        "SESSION_ID": os.environ.get("SESSION_ID"),
        "IS_HEAVY_WORKER": os.environ.get("IS_HEAVY_WORKER"),
    }
    os.environ["WORKER_SESSIONS_DIR"] = str(root.parent)
    os.environ["SESSION_ID"] = root.name
    os.environ["IS_HEAVY_WORKER"] = "1"
    try:
        yield
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _materialize_worker_workspace_snapshot(
    worker_client: Any,
    target_root: Path,
) -> None:
    pending_dirs = ["/"]
    visited_dirs: set[str] = set()
    file_paths: list[str] = []

    while pending_dirs:
        current_dir = pending_dirs.pop()
        normalized_dir = str(Path(current_dir)).replace("\\", "/")
        if normalized_dir in visited_dirs:
            continue
        visited_dirs.add(normalized_dir)
        try:
            entries = await worker_client.list_files(
                current_dir,
                bypass_agent_permissions=True,
            )
        except TypeError:
            entries = await worker_client.list_files(current_dir)

        for entry in entries:
            entry_path = str(getattr(entry, "path", "") or "").strip()
            if not entry_path:
                continue
            if getattr(entry, "is_dir", False):
                pending_dirs.append(entry_path)
                continue
            normalized_path = Path(entry_path).as_posix().lstrip("/")
            if normalized_path and normalized_path not in file_paths:
                file_paths.append(normalized_path)

    if not file_paths:
        return

    read_files_binary = getattr(worker_client, "read_files_binary", None)
    blobs: dict[str, bytes] = {}
    if callable(read_files_binary):
        try:
            blobs = await read_files_binary(
                file_paths,
                bypass_agent_permissions=True,
            )
        except TypeError:
            blobs = await read_files_binary(file_paths)

    for rel_path in file_paths:
        target_path = target_root / Path(rel_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if rel_path in blobs:
            target_path.write_bytes(blobs[rel_path])
            continue

        read_file_binary = getattr(worker_client, "read_file_binary", None)
        if callable(read_file_binary):
            try:
                target_path.write_bytes(
                    await read_file_binary(
                        rel_path,
                        bypass_agent_permissions=True,
                    )
                )
                continue
            except TypeError:
                target_path.write_bytes(await read_file_binary(rel_path))
                continue

        content = await worker_client.read_file_optional(
            rel_path,
            bypass_agent_permissions=True,
        )
        if content is None:
            raise FileNotFoundError(
                f"Seed validation snapshot missing file content for {rel_path}"
            )
        target_path.write_text(content, encoding="utf-8")


def _seed_validation_git_init(root: Path) -> None:
    try:
        from shared.git_utils import init_workspace_repo

        init_workspace_repo(root)
    except Exception:
        # The planner submission helpers need a git repo. If the repo cannot be
        # initialized, the planner gate will fail closed when invoked.
        return


async def _run_seed_validation_gate(
    *,
    worker_client: Any,
    gate_role: AgentName,
    gate_name: str,
    artifact_path: str | None,
    gate_runner,
) -> list[NodeEntryValidationError]:
    session_id = str(getattr(worker_client, "session_id", "") or "").strip() or str(
        uuid.uuid4()
    )
    with tempfile.TemporaryDirectory(prefix="seed-validation-") as tmp:
        root = Path(tmp)
        try:
            await _materialize_worker_workspace_snapshot(worker_client, root)
            root.joinpath(".manifests").mkdir(parents=True, exist_ok=True)
            root.joinpath(".manifests/current_role.json").write_text(
                _seed_validation_role_manifest(gate_role),
                encoding="utf-8",
            )
            _seed_validation_git_init(root)
            local_client = _LocalSeedWorkspaceClient(root, session_id=session_id)
            with _seed_validation_workspace_env(root):
                return await gate_runner(root=root, local_client=local_client)
        except Exception as exc:
            return [
                _seeded_schema_error(
                    message=f"{gate_name} replay failed: {exc}",
                    artifact_path=artifact_path,
                )
            ]


async def _run_seed_validation_benchmark_gate(
    *,
    worker_client: Any,
    gate_name: str,
    validation_scope: ValidationScope,
    gate_role: AgentName,
) -> list[NodeEntryValidationError]:
    async def _gate_runner(
        *, root: Path, local_client: _LocalSeedWorkspaceClient
    ) -> list[NodeEntryValidationError]:
        script_path = root / authored_script_path_for_agent(gate_role)
        component = load_component_from_script(
            script_path=script_path, session_root=root
        )
        validation_errors: list[NodeEntryValidationError] = []
        ok, message = validate_benchmark(
            component,
            script_path=script_path,
            output_dir=root,
            session_id=local_client.session_id,
            smoke_test_mode=controller_settings.is_integration_test,
        )
        if not ok:
            validation_errors.append(
                _seeded_schema_error(
                    message=f"{gate_name}: {message or 'validation failed'}",
                    artifact_path=script_path.relative_to(root).as_posix(),
                )
            )
            return validation_errors

        if (
            validation_scope
            == ValidationScope.CURRENT_AND_PREVIOUS_NODES_WITH_HEAVY_SIMULATION
        ):
            simulation_result = simulate_benchmark(
                component,
                script_path=script_path,
                output_dir=root,
                session_id=local_client.session_id,
                smoke_test_mode=controller_settings.is_integration_test,
            )
            if not simulation_result.success:
                validation_errors.append(
                    _seeded_schema_error(
                        message=(
                            f"{gate_name}: "
                            f"{simulation_result.message or 'simulation failed'}"
                        ),
                        artifact_path="simulation_result.json",
                    )
                )
        return validation_errors

    return await _run_seed_validation_gate(
        worker_client=worker_client,
        gate_role=gate_role,
        gate_name=gate_name,
        artifact_path=authored_script_path_for_agent(gate_role).as_posix(),
        gate_runner=_gate_runner,
    )


async def _run_seed_validation_engineering_gate(
    *,
    worker_client: Any,
    gate_name: str,
    validation_scope: ValidationScope,
    gate_role: AgentName,
) -> list[NodeEntryValidationError]:
    async def _gate_runner(
        *, root: Path, local_client: _LocalSeedWorkspaceClient
    ) -> list[NodeEntryValidationError]:
        script_path = root / authored_script_path_for_agent(gate_role)
        component = load_component_from_script(
            script_path=script_path, session_root=root
        )
        validation_errors: list[NodeEntryValidationError] = []
        ok, message = validate_engineering(
            component,
            script_path=script_path,
            output_dir=root,
            session_id=local_client.session_id,
            smoke_test_mode=controller_settings.is_integration_test,
        )
        if not ok:
            validation_errors.append(
                _seeded_schema_error(
                    message=f"{gate_name}: {message or 'validation failed'}",
                    artifact_path=script_path.relative_to(root).as_posix(),
                )
            )
            return validation_errors

        if (
            validation_scope
            == ValidationScope.CURRENT_AND_PREVIOUS_NODES_WITH_HEAVY_SIMULATION
        ):
            simulation_result = simulate_engineering(
                component,
                script_path=script_path,
                output_dir=root,
                session_id=local_client.session_id,
                smoke_test_mode=controller_settings.is_integration_test,
            )
            if not simulation_result.success:
                validation_errors.append(
                    _seeded_schema_error(
                        message=(
                            f"{gate_name}: "
                            f"{simulation_result.message or 'simulation failed'}"
                        ),
                        artifact_path="simulation_result.json",
                    )
                )
        return validation_errors

    return await _run_seed_validation_gate(
        worker_client=worker_client,
        gate_role=gate_role,
        gate_name=gate_name,
        artifact_path=authored_script_path_for_agent(gate_role).as_posix(),
        gate_runner=_gate_runner,
    )


async def _run_seed_validation_submit_plan_gate(
    *,
    worker_client: Any,
    gate_name: str,
    submit_fn,
    gate_role: AgentName,
) -> list[NodeEntryValidationError]:
    async def _gate_runner(
        *, root: Path, local_client: _LocalSeedWorkspaceClient
    ) -> list[NodeEntryValidationError]:
        result = submit_fn(root)
        if result.ok and result.status == "submitted":
            return []
        messages = result.errors or [f"{gate_name} returned status {result.status}"]
        return _benchmark_validation_errors(
            messages=messages,
            message_prefix=f"{gate_name}: ",
            artifact_path=plan_path_for_agent(gate_role).as_posix(),
        )

    return await _run_seed_validation_gate(
        worker_client=worker_client,
        gate_role=gate_role,
        gate_name=gate_name,
        artifact_path=plan_path_for_agent(gate_role).as_posix(),
        gate_runner=_gate_runner,
    )


async def _run_seed_validation_plan_reviewer_gate(
    *,
    worker_client: Any,
    gate_name: str,
    manifest_path: str,
    expected_stage: AgentName,
) -> list[NodeEntryValidationError]:
    async def _gate_runner(
        *, root: Path, local_client: _LocalSeedWorkspaceClient
    ) -> list[NodeEntryValidationError]:
        error = await validate_plan_reviewer_handover(
            local_client,
            manifest_path=manifest_path,
            expected_stage=expected_stage,
        )
        if error is None:
            return []
        return [
            _seeded_schema_error(
                message=f"{gate_name}: {error}",
                artifact_path=manifest_path,
            )
        ]

    return await _run_seed_validation_gate(
        worker_client=worker_client,
        gate_role=expected_stage,
        gate_name=gate_name,
        artifact_path=manifest_path,
        gate_runner=_gate_runner,
    )


async def _run_seed_validation_reviewer_gate(
    *,
    worker_client: Any,
    gate_name: str,
    manifest_path: str,
    expected_stage: AgentName,
    require_verification_result: bool | None = None,
    heavy_simulation: bool = False,
) -> list[NodeEntryValidationError]:
    async def _gate_runner(
        *, root: Path, local_client: _LocalSeedWorkspaceClient
    ) -> list[NodeEntryValidationError]:
        if heavy_simulation:
            script_path = root / authored_script_path_for_reviewer_stage(expected_stage)
            component = load_component_from_script(
                script_path=script_path,
                session_root=root,
            )
            simulation_result = (
                simulate_benchmark(
                    component,
                    script_path=script_path,
                    output_dir=root,
                    session_id=local_client.session_id,
                    smoke_test_mode=controller_settings.is_integration_test,
                )
                if expected_stage == AgentName.BENCHMARK_REVIEWER
                else simulate_engineering(
                    component,
                    script_path=script_path,
                    output_dir=root,
                    session_id=local_client.session_id,
                    smoke_test_mode=controller_settings.is_integration_test,
                )
            )
            if not simulation_result.success:
                return [
                    _seeded_schema_error(
                        message=(
                            f"{gate_name}: "
                            f"{simulation_result.message or 'simulation failed'}"
                        ),
                        artifact_path="simulation_result.json",
                    )
                ]

        error = await validate_reviewer_handover(
            local_client,
            manifest_path=manifest_path,
            expected_stage=expected_stage,
            require_verification_result=require_verification_result,
        )
        if error is None:
            return []
        return [
            _seeded_schema_error(
                message=f"{gate_name}: {error}",
                artifact_path=manifest_path,
            )
        ]

    return await _run_seed_validation_gate(
        worker_client=worker_client,
        gate_role=expected_stage,
        gate_name=gate_name,
        artifact_path=manifest_path,
        gate_runner=_gate_runner,
    )


async def _validate_seeded_workspace_scope_gates(
    *,
    worker_client: Any,
    target_node: AgentName,
    validation_scope: ValidationScope,
) -> list[NodeEntryValidationError]:
    from shared.agent_templates.codex.scripts.submit_plan import (
        submit_benchmark_plan,
        submit_engineering_plan,
    )

    if validation_scope == ValidationScope.CURRENT_NODE:
        return []

    errors: list[NodeEntryValidationError] = []

    if target_node == AgentName.BENCHMARK_PLANNER:
        errors.extend(
            await _run_seed_validation_submit_plan_gate(
                worker_client=worker_client,
                gate_name="benchmark planner submission",
                submit_fn=submit_benchmark_plan,
                gate_role=AgentName.BENCHMARK_PLANNER,
            )
        )
        return errors

    if target_node == AgentName.BENCHMARK_PLAN_REVIEWER:
        errors.extend(
            await _run_seed_validation_submit_plan_gate(
                worker_client=worker_client,
                gate_name="benchmark planner submission",
                submit_fn=submit_benchmark_plan,
                gate_role=AgentName.BENCHMARK_PLANNER,
            )
        )
        errors.extend(
            await _run_seed_validation_plan_reviewer_gate(
                worker_client=worker_client,
                gate_name="benchmark plan reviewer handover",
                manifest_path=".manifests/benchmark_plan_review_manifest.json",
                expected_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
            )
        )
        return errors

    if target_node == AgentName.BENCHMARK_CODER:
        errors.extend(
            await _run_seed_validation_submit_plan_gate(
                worker_client=worker_client,
                gate_name="benchmark planner submission",
                submit_fn=submit_benchmark_plan,
                gate_role=AgentName.BENCHMARK_PLANNER,
            )
        )
        errors.extend(
            await _run_seed_validation_plan_reviewer_gate(
                worker_client=worker_client,
                gate_name="benchmark plan reviewer handover",
                manifest_path=".manifests/benchmark_plan_review_manifest.json",
                expected_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
            )
        )
        return errors

    if target_node == AgentName.BENCHMARK_REVIEWER:
        errors.extend(
            await _run_seed_validation_submit_plan_gate(
                worker_client=worker_client,
                gate_name="benchmark planner submission",
                submit_fn=submit_benchmark_plan,
                gate_role=AgentName.BENCHMARK_PLANNER,
            )
        )
        errors.extend(
            await _run_seed_validation_plan_reviewer_gate(
                worker_client=worker_client,
                gate_name="benchmark plan reviewer handover",
                manifest_path=".manifests/benchmark_plan_review_manifest.json",
                expected_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
            )
        )
        errors.extend(
            await _run_seed_validation_benchmark_gate(
                worker_client=worker_client,
                gate_name="benchmark coder validation",
                validation_scope=validation_scope,
                gate_role=AgentName.BENCHMARK_CODER,
            )
        )
        errors.extend(
            await _run_seed_validation_reviewer_gate(
                worker_client=worker_client,
                gate_name="benchmark reviewer handover",
                manifest_path=".manifests/benchmark_review_manifest.json",
                expected_stage=AgentName.BENCHMARK_REVIEWER,
            )
        )
        return errors

    if target_node == AgentName.ENGINEER_PLANNER:
        errors.extend(
            await _run_seed_validation_benchmark_gate(
                worker_client=worker_client,
                gate_name="benchmark coder validation",
                validation_scope=validation_scope,
                gate_role=AgentName.BENCHMARK_CODER,
            )
        )
        errors.extend(
            await _run_seed_validation_submit_plan_gate(
                worker_client=worker_client,
                gate_name="engineering planner submission",
                submit_fn=submit_engineering_plan,
                gate_role=AgentName.ENGINEER_PLANNER,
            )
        )
        return errors

    if target_node == AgentName.ENGINEER_PLAN_REVIEWER:
        errors.extend(
            await _run_seed_validation_submit_plan_gate(
                worker_client=worker_client,
                gate_name="engineering planner submission",
                submit_fn=submit_engineering_plan,
                gate_role=AgentName.ENGINEER_PLANNER,
            )
        )
        errors.extend(
            await _run_seed_validation_plan_reviewer_gate(
                worker_client=worker_client,
                gate_name="engineering plan reviewer handover",
                manifest_path=".manifests/engineering_plan_review_manifest.json",
                expected_stage=AgentName.ENGINEER_PLAN_REVIEWER,
            )
        )
        return errors

    if target_node == AgentName.ENGINEER_CODER:
        errors.extend(
            await _run_seed_validation_benchmark_gate(
                worker_client=worker_client,
                gate_name="benchmark coder validation",
                validation_scope=validation_scope,
                gate_role=AgentName.BENCHMARK_CODER,
            )
        )
        errors.extend(
            await _run_seed_validation_submit_plan_gate(
                worker_client=worker_client,
                gate_name="engineering planner submission",
                submit_fn=submit_engineering_plan,
                gate_role=AgentName.ENGINEER_PLANNER,
            )
        )
        errors.extend(
            await _run_seed_validation_plan_reviewer_gate(
                worker_client=worker_client,
                gate_name="engineering plan reviewer handover",
                manifest_path=".manifests/engineering_plan_review_manifest.json",
                expected_stage=AgentName.ENGINEER_PLAN_REVIEWER,
            )
        )
        return errors

    if target_node == AgentName.ENGINEER_EXECUTION_REVIEWER:
        errors.extend(
            await _run_seed_validation_benchmark_gate(
                worker_client=worker_client,
                gate_name="benchmark coder validation",
                validation_scope=validation_scope,
                gate_role=AgentName.BENCHMARK_CODER,
            )
        )
        errors.extend(
            await _run_seed_validation_submit_plan_gate(
                worker_client=worker_client,
                gate_name="engineering planner submission",
                submit_fn=submit_engineering_plan,
                gate_role=AgentName.ENGINEER_PLANNER,
            )
        )
        errors.extend(
            await _run_seed_validation_plan_reviewer_gate(
                worker_client=worker_client,
                gate_name="engineering plan reviewer handover",
                manifest_path=".manifests/engineering_plan_review_manifest.json",
                expected_stage=AgentName.ENGINEER_PLAN_REVIEWER,
            )
        )
        errors.extend(
            await _run_seed_validation_engineering_gate(
                worker_client=worker_client,
                gate_name="engineering coder validation",
                validation_scope=validation_scope,
                gate_role=AgentName.ENGINEER_CODER,
            )
        )
        errors.extend(
            await _run_seed_validation_reviewer_gate(
                worker_client=worker_client,
                gate_name="engineering execution reviewer handover",
                manifest_path=".manifests/engineering_execution_handoff_manifest.json",
                expected_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
                require_verification_result=True,
            )
        )
        return errors

    return errors


def _required_render_bundle_sidecars(
    *,
    manifest: RenderManifest,
    manifest_path: str,
) -> list[str]:
    bundle_root = Path(manifest.bundle_path or Path(manifest_path).parent)
    evidence_paths = [
        Path(path)
        for path in manifest.preview_evidence_paths
        if path and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"}
    ]
    if not evidence_paths:
        evidence_paths = [
            Path(path)
            for path in manifest.artifacts
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"}
        ]

    required: list[str] = []
    if any(path.suffix.lower() == ".mp4" for path in evidence_paths):
        required.extend(
            [
                str(bundle_root / "frames.jsonl"),
                str(bundle_root / "objects.parquet"),
            ]
        )
    return required


def _render_manifest_image_paths(
    manifest: RenderManifest,
) -> tuple[list[str], list[str]]:
    preview_paths = sorted(
        dict.fromkeys(
            Path(path).as_posix().lstrip("/")
            for path in manifest.preview_evidence_paths
            if path and Path(path).suffix.lower() in _RENDER_IMAGE_EXTENSIONS
        )
    )
    artifact_paths = sorted(
        dict.fromkeys(
            Path(path).as_posix().lstrip("/")
            for path in manifest.artifacts
            if Path(path).suffix.lower() in _RENDER_IMAGE_EXTENSIONS
        )
    )
    return preview_paths, artifact_paths


async def validate_seeded_workspace_handoff_artifacts(
    *,
    worker_client: WorkerClient,
    target_node: AgentName,
    validation_scope: ValidationScope = ValidationScope.CURRENT_NODE,
) -> list[NodeEntryValidationError]:
    """Fail-closed schema + semantic checks for seeded/direct entry workspaces.

    Downstream coder and reviewer seed rows must still expose the writable
    authored files from their checked-in starter templates rather than
    pre-solved outputs.
    """
    errors: list[NodeEntryValidationError] = []
    contents: dict[str, str] = {}
    benchmark_definition_model: BenchmarkDefinition | None = None
    assembly_definition_model: AssemblyDefinition | None = None
    benchmark_assembly_definition_model: AssemblyDefinition | None = None
    manufacturing_config_model = None

    errors.extend(
        await _current_role_manifest_errors(
            worker_client=worker_client,
            target_node=target_node,
        )
    )

    if target_node in {
        AgentName.BENCHMARK_PLANNER,
        AgentName.ENGINEER_PLANNER,
    }:
        manufacturing_raw = await worker_client.read_file_optional(
            "manufacturing_config.yaml",
            bypass_agent_permissions=True,
        )
        if manufacturing_raw is None:
            errors.append(
                _seeded_schema_error(
                    message=(
                        "manufacturing_config.yaml missing for planner handoff "
                        "pricing source"
                    ),
                    artifact_path="manufacturing_config.yaml",
                )
            )
        else:
            try:
                manufacturing_config_model = (
                    load_planner_manufacturing_config_from_text(manufacturing_raw)
                )
            except Exception as exc:
                errors.append(
                    _seeded_schema_error(
                        message=(
                            "manufacturing_config.yaml invalid for planner handoff "
                            f"pricing source: {exc}"
                        ),
                        artifact_path="manufacturing_config.yaml",
                    )
                )

    starter_template_errors = await _seeded_starter_template_errors(
        worker_client=worker_client,
        target_node=target_node,
    )
    errors.extend(starter_template_errors)

    for rel_path in SCHEMA_BACKED_HANDOFF_PATHS:
        content = await worker_client.read_file_optional(
            rel_path,
            bypass_agent_permissions=True,
        )
        if content is not None:
            contents[rel_path] = content

    plan_artifact_name = plan_path_for_agent(target_node).as_posix()
    plan_content = contents.get(plan_artifact_name)

    for rel_path, content in contents.items():
        if rel_path == plan_artifact_name:
            plan_type = _plan_type_for_target(target_node, content)
            is_valid, plan_errors = validate_plan_md_structure(
                content,
                plan_type,
                artifact_path=rel_path,
            )
            if not is_valid:
                errors.extend(
                    _seeded_schema_error(
                        message=f"{rel_path}: {message}",
                        artifact_path=rel_path,
                    )
                    for message in plan_errors
                )
            continue

        if rel_path == "todo.md":
            todo_result = validate_todo_md(content)
            if not todo_result.is_valid:
                errors.extend(
                    _seeded_schema_error(
                        message=f"{rel_path}: {message}",
                        artifact_path=rel_path,
                    )
                    for message in todo_result.violations
                )
            continue

        if rel_path == "plan_refusal.md":
            is_valid, refusal_errors = validate_plan_refusal(content)
            if not is_valid and isinstance(refusal_errors, list):
                errors.extend(
                    _seeded_schema_error(
                        message=f"{rel_path}: {message}",
                        artifact_path=rel_path,
                    )
                    for message in refusal_errors
                )
            continue

        if rel_path == "benchmark_definition.yaml":
            is_valid, benchmark_result = validate_benchmark_definition_yaml(
                content,
                session_id=worker_client.session_id,
            )
            if not is_valid and isinstance(benchmark_result, list):
                errors.extend(
                    _seeded_schema_error(
                        message=f"{rel_path}: {message}",
                        artifact_path=rel_path,
                    )
                    for message in benchmark_result
                )
            elif isinstance(benchmark_result, BenchmarkDefinition):
                benchmark_definition_model = benchmark_result
            continue

        if rel_path in {
            "assembly_definition.yaml",
            "benchmark_assembly_definition.yaml",
        }:
            is_valid, assembly_result = validate_assembly_definition_yaml(
                content,
                session_id=worker_client.session_id,
                manufacturing_config=manufacturing_config_model,
                exact_weight=rel_path == "assembly_definition.yaml",
            )
            if not is_valid and isinstance(assembly_result, list):
                errors.extend(
                    _seeded_schema_error(
                        message=f"{rel_path}: {message}",
                        artifact_path=rel_path,
                    )
                    for message in assembly_result
                )
            elif isinstance(assembly_result, AssemblyDefinition):
                if rel_path == "benchmark_assembly_definition.yaml":
                    benchmark_assembly_definition_model = assembly_result
                    motion_errors = validate_benchmark_assembly_motion_contract(
                        benchmark_definition=benchmark_definition_model,
                        assembly_definition=assembly_result,
                        plan_text=plan_content,
                        todo_text=contents.get("todo.md"),
                        plan_refusal_text=contents.get("plan_refusal.md"),
                    )
                    errors.extend(
                        _seeded_schema_error(
                            message=f"{rel_path}: {message}",
                            artifact_path=rel_path,
                        )
                        for message in motion_errors
                    )
                else:
                    assembly_definition_model = assembly_result
            continue

        if rel_path == "payload_trajectory_definition.yaml":
            is_valid, precise_result = validate_payload_trajectory_definition_yaml(
                content,
                benchmark_definition=benchmark_definition_model,
                coarse_motion_forecast=(
                    assembly_definition_model.motion_forecast
                    if assembly_definition_model is not None
                    else None
                ),
                expected_moving_part_names=(
                    [part.part_name for part in assembly_definition_model.moving_parts]
                    if assembly_definition_model is not None
                    else None
                ),
                assembly_definition=assembly_definition_model,
                benchmark_assembly_definition=benchmark_assembly_definition_model,
                validate_clearance=False,
                session_id=worker_client.session_id,
            )
            if not is_valid and isinstance(precise_result, list):
                errors.extend(
                    _seeded_schema_error(
                        message=message,
                        artifact_path=rel_path,
                    )
                    for message in precise_result
                )
            continue

        try:
            if rel_path == "validation_results.json":
                ValidationResultRecord.model_validate_json(content)
            elif rel_path == "simulation_result.json":
                SimulationResult.model_validate_json(content)
            elif rel_path in {
                ".manifests/benchmark_plan_review_manifest.json",
                ".manifests/engineering_plan_review_manifest.json",
            }:
                PlanReviewManifest.model_validate_json(content)
            elif rel_path in {
                ".manifests/benchmark_review_manifest.json",
                ".manifests/engineering_execution_handoff_manifest.json",
            }:
                ReviewManifest.model_validate_json(content)
        except Exception as exc:  # pragma: no cover - defensive parse guard
            errors.append(
                _seeded_schema_error(
                    message=f"{rel_path}: {exc}",
                    artifact_path=rel_path,
                )
            )

    present_paths = set(contents)

    if (
        target_node != AgentName.BENCHMARK_PLANNER
        and "benchmark_definition.yaml" in present_paths
        and "benchmark_script.py" not in present_paths
    ):
        errors.append(
            _seeded_schema_error(
                message=(
                    "benchmark_script.py missing for benchmark-backed seeded "
                    f"workspace targeting {target_node.value}."
                ),
                artifact_path="benchmark_script.py",
            )
        )

    if {
        "benchmark_definition.yaml",
        "assembly_definition.yaml",
    }.issubset(present_paths):
        handover_error = await validate_planner_artifacts_cross_contract(
            worker_client,
            expected_stage=AgentName.ENGINEER_PLAN_REVIEWER,
        )
        if handover_error is not None:
            errors.append(
                _seeded_schema_error(
                    message=f"engineering planner handoff: {handover_error}",
                    artifact_path="assembly_definition.yaml",
                )
            )

    if (
        benchmark_definition_model is not None
        and benchmark_assembly_definition_model is not None
    ):
        if manufacturing_config_model is None:
            manufacturing_raw = await worker_client.read_file_optional(
                "manufacturing_config.yaml",
                bypass_agent_permissions=True,
            )
            if manufacturing_raw is not None:
                try:
                    manufacturing_config_model = (
                        load_planner_manufacturing_config_from_text(manufacturing_raw)
                    )
                except Exception as exc:
                    errors.append(
                        _seeded_schema_error(
                            message=(
                                "manufacturing_config.yaml invalid for benchmark "
                                f"handoff pricing source: {exc}"
                            ),
                            artifact_path="manufacturing_config.yaml",
                        )
                    )

        if manufacturing_config_model is not None:
            handover_errors = validate_planner_handoff_cross_contract(
                benchmark_definition=benchmark_definition_model,
                assembly_definition=benchmark_assembly_definition_model,
                manufacturing_config=manufacturing_config_model,
                planner_node_type=AgentName.BENCHMARK_PLAN_REVIEWER,
                plan_text=plan_content,
            )
            errors.extend(
                _seeded_schema_error(
                    message=f"benchmark_assembly_definition.yaml: {message}",
                    artifact_path="benchmark_assembly_definition.yaml",
                )
                for message in handover_errors
            )

    if (
        "payload_trajectory_definition.yaml" in present_paths
        and benchmark_definition_model is not None
        and assembly_definition_model is not None
    ):
        errors.extend(
            await _validate_payload_trajectory_clearance_on_worker(worker_client)
        )

    render_error = await validate_render_images_non_black(
        worker_client,
        require_images=target_node
        in {
            AgentName.BENCHMARK_PLAN_REVIEWER,
            AgentName.BENCHMARK_REVIEWER,
        },
    )
    if render_error is not None:
        errors.append(
            _seeded_schema_error(
                message=render_error,
                artifact_path="renders",
            )
        )

    for rel_path, content in contents.items():
        if not rel_path.endswith("render_manifest.json"):
            continue
        try:
            render_manifest = RenderManifest.model_validate_json(content)
        except Exception as exc:
            errors.append(
                _seeded_schema_error(
                    message=f"{rel_path}: {exc}",
                    artifact_path=rel_path,
                )
            )
            continue

        preview_image_paths, artifact_image_paths = _render_manifest_image_paths(
            render_manifest
        )
        if (
            preview_image_paths
            and artifact_image_paths
            and (preview_image_paths != artifact_image_paths)
        ):
            errors.append(
                _seeded_schema_error(
                    message=(
                        f"{rel_path}: preview evidence paths must match the "
                        "render artifact image set"
                    ),
                    artifact_path=rel_path,
                )
            )

        expected_image_paths = (
            preview_image_paths if preview_image_paths else artifact_image_paths
        )
        missing_image_paths = [
            image_path
            for image_path in expected_image_paths
            if not await worker_client.exists(image_path, bypass_agent_permissions=True)
        ]
        for image_path in missing_image_paths:
            errors.append(
                _seeded_schema_error(
                    message=f"{rel_path}: render image '{image_path}' is missing.",
                    artifact_path=image_path,
                )
            )

        for required_sidecar in _required_render_bundle_sidecars(
            manifest=render_manifest,
            manifest_path=rel_path,
        ):
            if await worker_client.exists(
                required_sidecar, bypass_agent_permissions=True
            ):
                continue
            errors.append(
                _seeded_schema_error(
                    message=(
                        f"{rel_path}: required render sidecar "
                        f"'{required_sidecar}' is missing."
                    ),
                    artifact_path=required_sidecar,
                )
            )

    if validation_scope != ValidationScope.CURRENT_NODE:
        errors.extend(
            await _validate_seeded_workspace_scope_gates(
                worker_client=worker_client,
                target_node=target_node,
                validation_scope=validation_scope,
            )
        )

    return errors


class ArtifactExistsFn(Protocol):
    async def __call__(self, path: str) -> bool: ...


class CustomEntryCheck(Protocol):
    async def __call__(
        self,
        *,
        contract: NodeEntryContract,
        state: BaseModel | Mapping[str, Any],
    ) -> Sequence[NodeEntryValidationError]: ...


def integration_mode_enabled() -> bool:
    return bool(agent_settings.is_integration_test)


def get_previous_node(
    target_node: AgentName,
    *,
    graph: ValidationGraph,
) -> AgentName | None:
    return PREVIOUS_NODE_MAPS[graph].get(target_node)


def resolve_failure_disposition(
    *,
    integration_mode: bool,
    reroute_target: AgentName | None,
    integration_policy: EntryFailureDisposition,
) -> EntryFailureDisposition:
    if integration_mode:
        return integration_policy
    if reroute_target is None:
        return EntryFailureDisposition.FAIL_FAST
    return EntryFailureDisposition.REROUTE_PREVIOUS


def _get_state_value(state: BaseModel | Mapping[str, Any], field_name: str) -> Any:
    if isinstance(state, Mapping):
        return state.get(field_name)
    return getattr(state, field_name, None)


def _get_state_worker_client(state: BaseModel | Mapping[str, Any]) -> Any | None:
    return _get_state_value(state, "workspace_client") or _get_state_value(
        state, "worker_client"
    )


async def _current_role_manifest_errors(
    *,
    worker_client: Any | None,
    target_node: AgentName,
    state: BaseModel | Mapping[str, Any] | None = None,
) -> list[NodeEntryValidationError]:
    manifest_path = ".manifests/current_role.json"
    worker_session_id = (
        None if state is None else _get_state_value(state, "worker_session_id")
    )
    if worker_session_id is None and state is not None:
        worker_session_id = _get_state_value(state, "session_id")

    owns_client = worker_client is None
    client = worker_client
    if client is None and worker_session_id:
        client = WorkerClient(
            base_url=controller_settings.worker_light_url,
            heavy_url=controller_settings.worker_heavy_url,
            session_id=str(worker_session_id),
        )

    if client is None:
        return [
            NodeEntryValidationError(
                code=REASON_MISSING_ARTIFACT,
                message=(
                    "Current-role manifest missing; no workspace client was "
                    "available to read .manifests/current_role.json."
                ),
                source=EntryValidationSource.ARTIFACT,
                artifact_path=manifest_path,
            )
        ]

    try:
        content = await client.read_file_optional(
            manifest_path,
            bypass_agent_permissions=True,
        )
    except Exception as exc:
        return [
            NodeEntryValidationError(
                code=REASON_MISSING_ARTIFACT,
                message=(
                    "Current-role manifest could not be read from "
                    f"{manifest_path}: {exc}"
                ),
                source=EntryValidationSource.ARTIFACT,
                artifact_path=manifest_path,
            )
        ]
    finally:
        if owns_client and client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()

    if content is None:
        return [
            NodeEntryValidationError(
                code=REASON_MISSING_ARTIFACT,
                message=(
                    "Current-role manifest missing; expected "
                    f"{manifest_path} to name {target_node.value}."
                ),
                source=EntryValidationSource.ARTIFACT,
                artifact_path=manifest_path,
            )
        ]

    try:
        manifest = parse_current_role_manifest(content)
    except Exception as exc:
        return [
            NodeEntryValidationError(
                code=REASON_POLICY_INVALID,
                message=(f"Current-role manifest malformed at {manifest_path}: {exc}"),
                source=EntryValidationSource.POLICY,
                artifact_path=manifest_path,
            )
        ]

    if manifest.agent_name != target_node:
        return [
            NodeEntryValidationError(
                code=REASON_POLICY_INVALID,
                message=(
                    "Current-role manifest mismatch: "
                    f"expected {target_node.value}, found {manifest.agent_name.value}."
                ),
                source=EntryValidationSource.POLICY,
                artifact_path=manifest_path,
            )
        ]

    return []


async def evaluate_node_entry_contract(
    *,
    contract: NodeEntryContract,
    state: BaseModel | Mapping[str, Any],
    artifact_exists: ArtifactExistsFn,
    graph: ValidationGraph,
    custom_checks: Mapping[str, CustomEntryCheck] | None = None,
    integration_mode: bool | None = None,
) -> NodeEntryValidationResult:
    errors: list[NodeEntryValidationError] = []

    current_role_errors = await _current_role_manifest_errors(
        worker_client=_get_state_worker_client(state),
        target_node=contract.node,
        state=state,
    )
    errors.extend(current_role_errors)

    for required_field in contract.required_state_fields:
        if _get_state_value(state, required_field) is None:
            errors.append(
                NodeEntryValidationError(
                    code=REASON_STATE_INVALID,
                    message=(
                        f"Required state field '{required_field}' is missing or null."
                    ),
                    source=EntryValidationSource.STATE,
                )
            )

    if contract.custom_check:
        custom_check = (custom_checks or {}).get(contract.custom_check)
        if custom_check is None:
            errors.append(
                NodeEntryValidationError(
                    code=REASON_POLICY_INVALID,
                    message=(
                        f"Unknown custom check '{contract.custom_check}' "
                        "configured in node entry contract."
                    ),
                    source=EntryValidationSource.POLICY,
                )
            )
        else:
            try:
                custom_errors = await custom_check(contract=contract, state=state)
                errors.extend(custom_errors)
            except Exception as exc:  # pragma: no cover - defensive guard
                errors.append(
                    NodeEntryValidationError(
                        code=REASON_CUSTOM_CHECK_FAILED,
                        message=(
                            f"Custom check '{contract.custom_check}' raised: {exc}"
                        ),
                        source=EntryValidationSource.POLICY,
                    )
                )

    for required_artifact in contract.required_artifacts:
        if not await artifact_exists(required_artifact):
            errors.append(
                NodeEntryValidationError(
                    code=REASON_MISSING_ARTIFACT,
                    message=f"Required artifact '{required_artifact}' is missing.",
                    source=EntryValidationSource.ARTIFACT,
                    artifact_path=required_artifact,
                )
            )

    if not errors:
        return NodeEntryValidationResult(
            ok=True,
            target_node=contract.node,
            disposition=EntryFailureDisposition.ALLOW,
            errors=[],
            reroute_target=None,
            reason_code=REASON_OK,
        )

    reroute_target = get_previous_node(contract.node, graph=graph)
    resolved_integration_mode = (
        integration_mode_enabled() if integration_mode is None else integration_mode
    )
    disposition = resolve_failure_disposition(
        integration_mode=resolved_integration_mode,
        reroute_target=reroute_target,
        integration_policy=contract.integration_failure_policy,
    )

    if (
        disposition == EntryFailureDisposition.FAIL_FAST
        and reroute_target is None
        and not resolved_integration_mode
    ):
        errors.append(
            NodeEntryValidationError(
                code=REASON_NO_PREVIOUS_NODE,
                message=(
                    f"No deterministic previous node mapping exists for "
                    f"'{contract.node.value}'."
                ),
                source=EntryValidationSource.POLICY,
            )
        )

    return NodeEntryValidationResult(
        ok=False,
        target_node=contract.node,
        disposition=disposition,
        errors=errors,
        reroute_target=reroute_target,
        reason_code=errors[0].code,
    )


__all__ = [
    "BENCHMARK_CODER_HANDOVER_CHECK",
    "BENCHMARK_PLANNER_HANDOFF_ARTIFACTS",
    "BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK",
    "BENCHMARK_PLAN_REVIEW_MANIFEST",
    "BENCHMARK_PREVIOUS_NODE_MAP",
    "BENCHMARK_REVIEWER_HANDOVER_CHECK",
    "ENGINEER_BENCHMARK_CONTEXT_ARTIFACTS",
    "ENGINEER_BENCHMARK_HANDOVER_CHECK",
    "ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK",
    "ENGINEER_PLANNER_HANDOFF_ARTIFACTS",
    "ENGINEER_PREVIOUS_NODE_MAP",
    "PREVIOUS_NODE_MAPS",
    "REASON_CUSTOM_CHECK_FAILED",
    "REASON_HANDOVER_INVALID",
    "REASON_MISSING_ARTIFACT",
    "REASON_NO_PREVIOUS_NODE",
    "REASON_OK",
    "REASON_POLICY_INVALID",
    "REASON_REVIEWER_ENTRY_BLOCKED",
    "REASON_STATE_INVALID",
    "NodeEntryContract",
    "NodeEntryValidationError",
    "NodeEntryValidationResult",
    "ValidationGraph",
    "ValidationScope",
    "benchmark_coder_handover_custom_check",
    "benchmark_coder_handover_custom_check_from_session_id",
    "benchmark_plan_reviewer_handover_custom_check",
    "benchmark_plan_reviewer_handover_custom_check_from_session_id",
    "build_benchmark_node_contracts",
    "build_engineer_node_contracts",
    "engineer_benchmark_handover_custom_check",
    "evaluate_node_entry_contract",
    "get_previous_node",
    "integration_mode_enabled",
    "resolve_failure_disposition",
    "reviewer_handover_custom_check_from_session_id",
    "validate_seeded_workspace_handoff_artifacts",
]
