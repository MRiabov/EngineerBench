from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from controller.agent.node_entry_validation import (
    BENCHMARK_CODER_HANDOVER_CHECK,
    BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK,
    BENCHMARK_REVIEWER_HANDOVER_CHECK,
    ENGINEER_BENCHMARK_HANDOVER_CHECK,
    ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK,
    ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK,
    ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK,
    NodeEntryValidationError,
    NodeEntryValidationResult,
    ValidationGraph,
    benchmark_coder_handover_custom_check_from_session_id,
    benchmark_plan_reviewer_handover_custom_check_from_session_id,
    build_benchmark_node_contracts,
    build_engineer_node_contracts,
    engineer_benchmark_handover_custom_check,
    engineer_planner_evidence_layout_custom_check,
    evaluate_node_entry_contract,
    plan_reviewer_handover_custom_check_from_session_id,
    reviewer_handover_custom_check_from_session_id,
    validate_seeded_workspace_handoff_artifacts,
)
from controller.clients.worker import WorkerClient
from evals.logic.models import AgentEvalSpec, EvalDatasetItem
from evals.logic.seed_maintenance import refresh_seed_artifact_manifests
from shared.agent_templates import load_common_template_files
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, EvalMode
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    AssemblyPartConfig,
    BenchmarkDefinition,
    CostTotals,
    PartConfig,
)
from shared.script_contracts import plan_artifact_candidates_for_agent

_SEED_ARTIFACT_SKIP_DIR_NAMES = {".git", "__pycache__"}


class SeededEntryContractFailure(BaseModel):
    session_id: str
    agent_name: AgentName
    target_node: AgentName
    missing_seed_paths: list[str] = Field(default_factory=list)
    entry_validation_result: NodeEntryValidationResult | None = None
    supplemental_validation_errors: list[NodeEntryValidationError] = Field(
        default_factory=list
    )
    supplemental_messages: list[str] = Field(default_factory=list)


class SeededEntryContractError(RuntimeError):
    def __init__(self, report: SeededEntryContractFailure):
        self.report = report
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        parts = [f"Seeded entry contract invalid for {self.report.target_node.value}"]
        if self.report.supplemental_messages:
            parts.append("; ".join(self.report.supplemental_messages))
        return ": ".join(parts)

    def __str__(self) -> str:
        return self._format_message()


def resolve_seed_artifact_dir(item: EvalDatasetItem, *, root: Path) -> Path | None:
    if item.seed_artifact_dir is None:
        return None

    artifact_dir = Path(item.seed_artifact_dir)
    if artifact_dir.is_absolute():
        return artifact_dir

    repo_relative = root / artifact_dir
    if repo_relative.exists():
        return repo_relative

    if item.seed_dataset is not None:
        dataset_relative = (root / item.seed_dataset).parent / artifact_dir
        if dataset_relative.exists():
            return dataset_relative

    return repo_relative


def _is_seed_artifact_path(path: Path) -> bool:
    if any(part in _SEED_ARTIFACT_SKIP_DIR_NAMES for part in path.parts):
        return False
    if path.suffix.lower() in {".pyc", ".pyo"}:
        return False
    return True


def _iter_seed_artifact_paths(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(p for p in root.rglob("*") if p.is_file())
        if _is_seed_artifact_path(path)
    ]


def collect_seed_workspace_artifact_paths(
    item: EvalDatasetItem,
    *,
    root: Path,
) -> list[str]:
    """Return relative paths that should exist for a seeded workspace."""
    expected_paths: set[str] = set()
    artifact_dir = resolve_seed_artifact_dir(item, root=root)
    if (
        item.seed_artifact_dir is not None
        and artifact_dir is not None
        and not artifact_dir.exists()
    ):
        raise FileNotFoundError(f"Seed artifact directory not found: {artifact_dir}")

    if artifact_dir is not None and artifact_dir.exists():
        for path in _iter_seed_artifact_paths(artifact_dir):
            if path.name == "prompt.md":
                continue
            expected_paths.add(path.relative_to(artifact_dir).as_posix())

    expected_paths.update((item.seed_files or {}).keys())
    expected_paths.add(".manifests/current_role.json")
    return sorted(expected_paths)


async def validate_workspace_has_artifacts(
    worker: WorkerClient,
    *,
    artifact_paths: list[str],
) -> list[str]:
    """Return missing relative paths from a workspace-backed filesystem."""
    missing: list[str] = []
    for rel_path in artifact_paths:
        if not await worker.exists(rel_path):
            missing.append(rel_path)
    return missing


def _plan_artifact_exists_fn(
    *,
    worker: WorkerClient,
    target_node: AgentName,
):
    plan_candidate = plan_artifact_candidates_for_agent(target_node)[0]

    async def _exists(path: str) -> bool:
        if path == plan_candidate:
            return await worker.exists(plan_candidate)
        return await worker.exists(path)

    return _exists


class InMemorySeedWorkspaceClient:
    """In-memory workspace client used to build seeded snapshots."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._files: dict[str, bytes] = {}

    @staticmethod
    def _normalize(virtual_path: str) -> str:
        normalized = str(virtual_path).strip()
        if normalized in {"/workspace", "workspace"}:
            normalized = "/"
        elif normalized.startswith("/workspace/"):
            normalized = "/" + normalized[len("/workspace/") :]
        elif normalized.startswith("workspace/"):
            normalized = normalized[len("workspace/") :]

        rel = normalized.lstrip("/")
        if not rel or rel == ".":
            return ""
        if rel == ".." or rel.startswith("../") or "/../" in rel:
            raise ValueError(f"Path escapes workspace root: {virtual_path}")
        return Path(rel).as_posix()

    def snapshot_files(self) -> list[tuple[str, bytes]]:
        return sorted(self._files.items())

    async def exists(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> bool:
        key = self._normalize(path)
        if key in self._files:
            return True
        # Check if any file is under this directory
        prefix = key.rstrip("/") + "/" if key else ""
        if prefix:
            return any(f.startswith(prefix) for f in self._files)
        return False

    async def read_file(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> str:
        try:
            raw = self._files[self._normalize(path)]
            return raw.decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            return f"Error: File '{path}' not found."

    async def read_file_optional(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> str | None:
        try:
            raw = self._files[self._normalize(path)]
            return raw.decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            return None

    async def write_file(
        self,
        path: str,
        content: str,
        overwrite: bool = True,
        *,
        bypass_agent_permissions: bool = False,
    ) -> bool:
        key = self._normalize(path)
        if key in self._files and not overwrite:
            raise FileExistsError(f"Cannot write to {path} because it already exists.")
        self._files[key] = content.encode("utf-8")
        return True

    async def upload_file(
        self,
        path: str,
        content: bytes,
        *,
        bypass_agent_permissions: bool = False,
    ) -> bool:
        self._files[self._normalize(path)] = content
        return True

    async def list_files(self, path: str) -> list:
        """List files under a directory path, returning FileEntry-like objects."""
        from types import SimpleNamespace

        prefix = self._normalize(path)
        if prefix:
            prefix = prefix.rstrip("/") + "/"
        results = []
        seen_dirs: set[str] = set()
        for key in self._files:
            if prefix and not key.startswith(prefix):
                continue
            remainder = key[len(prefix) :] if prefix else key
            if "/" in remainder:
                dir_name = remainder.split("/", 1)[0]
                if dir_name not in seen_dirs:
                    seen_dirs.add(dir_name)
                    results.append(
                        SimpleNamespace(
                            path=prefix + dir_name,
                            name=dir_name,
                            is_dir=True,
                        )
                    )
            else:
                results.append(
                    SimpleNamespace(
                        path=key,
                        name=Path(key).name,
                        is_dir=False,
                    )
                )
        return results

    async def read_files_binary(self, paths: list[str]) -> dict[str, bytes | None]:
        """Read multiple files as binary content."""
        result = {}
        for path in paths:
            key = self._normalize(path)
            result[path] = self._files.get(key)
        return result

    async def aclose(self) -> None:
        return None


async def materialize_seed_workspace_snapshot(
    *,
    item: EvalDatasetItem,
    session_id: str,
    agent_name: AgentName,
    root: Path,
    workspace_client: InMemorySeedWorkspaceClient,
    update_manifests: bool = True,
) -> list[str]:
    artifact_dir = resolve_seed_artifact_dir(item, root=root)
    inline_files = item.seed_files or {}
    template_files = load_common_template_files()
    seeded_paths: list[str] = []

    if artifact_dir is None and not inline_files and not template_files:
        return seeded_paths

    if artifact_dir is not None:
        if not artifact_dir.exists():
            raise FileNotFoundError(
                f"Seed artifact directory not found: {artifact_dir}"
            )

        updated_paths = refresh_seed_artifact_manifests(
            artifact_dir, fix=update_manifests
        )
        if updated_paths and not update_manifests:
            raise ValueError(
                "Seed artifact manifest drift detected; rerun with --update-manifests."
            )

    for rel_path, content in template_files.items():
        await workspace_client.write_file(
            rel_path,
            content,
            overwrite=True,
            bypass_agent_permissions=True,
        )
        seeded_paths.append(rel_path)

    if artifact_dir is not None:
        for path in _iter_seed_artifact_paths(artifact_dir):
            rel_path = path.relative_to(artifact_dir).as_posix()
            raw_bytes = path.read_bytes()
            try:
                content = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                await workspace_client.upload_file(
                    rel_path,
                    raw_bytes,
                    bypass_agent_permissions=True,
                )
            else:
                await workspace_client.write_file(
                    rel_path,
                    content,
                    overwrite=True,
                    bypass_agent_permissions=True,
                )
            seeded_paths.append(rel_path)

    for rel_path, content in inline_files.items():
        await workspace_client.write_file(
            rel_path,
            content,
            overwrite=True,
            bypass_agent_permissions=True,
        )
        seeded_paths.append(rel_path)

    await workspace_client.write_file(
        ".manifests/current_role.json",
        current_role_manifest_json(agent_name),
        overwrite=True,
        bypass_agent_permissions=True,
    )
    seeded_paths.append(".manifests/current_role.json")

    return seeded_paths


async def _load_benchmark_caps(worker: WorkerClient) -> tuple[float, float]:
    default_unit_cost = 100.0
    default_weight = 1000.0
    benchmark_path = "benchmark_definition.yaml"
    if not await worker.exists(benchmark_path):
        return default_unit_cost, default_weight
    try:
        raw_content = await worker.read_file(benchmark_path)
        data = yaml.safe_load(raw_content) or {}
        benchmark = BenchmarkDefinition.model_validate(data)
    except Exception:
        return default_unit_cost, default_weight

    max_unit_cost = (
        benchmark.constraints.max_unit_cost
        if benchmark.constraints.max_unit_cost is not None
        else default_unit_cost
    )
    max_weight_g = (
        benchmark.constraints.max_weight_g
        if benchmark.constraints.max_weight_g is not None
        else default_weight
    )
    return float(max_unit_cost), float(max_weight_g)


def _starter_engineer_assembly(
    benchmark_max_unit_cost_usd: float, benchmark_max_weight_g: float
) -> AssemblyDefinition:
    planner_target_max_unit_cost_usd = max(1.0, benchmark_max_unit_cost_usd * 0.5)
    planner_target_max_weight_g = max(1.0, benchmark_max_weight_g * 0.5)
    target_name = "starter_assembly"
    return AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            benchmark_max_unit_cost_usd=benchmark_max_unit_cost_usd,
            benchmark_max_weight_g=benchmark_max_weight_g,
            planner_target_max_unit_cost_usd=planner_target_max_unit_cost_usd,
            planner_target_max_weight_g=planner_target_max_weight_g,
        ),
        manufactured_parts=[],
        cots_parts=[],
        final_assembly=[PartConfig(name=target_name, config=AssemblyPartConfig())],
        totals=CostTotals(
            estimated_unit_cost_usd=0.0,
            estimated_weight_g=0.0,
            estimate_confidence="high",
        ),
    )


def _starter_benchmark_assembly(
    benchmark_max_unit_cost_usd: float, benchmark_max_weight_g: float
) -> AssemblyDefinition:
    planner_target_max_unit_cost_usd = max(1.0, benchmark_max_unit_cost_usd * 0.5)
    planner_target_max_weight_g = max(1.0, benchmark_max_weight_g * 0.5)
    target_name = "starter_assembly"
    return AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            benchmark_max_unit_cost_usd=benchmark_max_unit_cost_usd,
            benchmark_max_weight_g=benchmark_max_weight_g,
            planner_target_max_unit_cost_usd=planner_target_max_unit_cost_usd,
            planner_target_max_weight_g=planner_target_max_weight_g,
        ),
        manufactured_parts=[],
        cots_parts=[],
        final_assembly=[PartConfig(name=target_name, config=AssemblyPartConfig())],
        totals=CostTotals(
            estimated_unit_cost_usd=0.0,
            estimated_weight_g=0.0,
            estimate_confidence="high",
        ),
    )


async def _write_missing_template_files(
    worker: WorkerClient, template_files: dict[str, str]
) -> list[str]:
    copied: list[str] = []
    for rel_path, content in sorted(template_files.items()):
        if await worker.exists(rel_path):
            continue
        await worker.write_file(
            rel_path,
            content,
            overwrite=True,
            bypass_agent_permissions=True,
        )
        copied.append(rel_path)
    return copied


async def seed_eval_workspace(
    *,
    item: EvalDatasetItem,
    session_id: str,
    agent_name: AgentName,
    root: Path,
    worker_light_url: str,
    logger: Any,
    update_manifests: bool = True,
) -> None:
    artifact_dir = resolve_seed_artifact_dir(item, root=root)
    inline_files = item.seed_files or {}
    template_files = load_common_template_files()
    if artifact_dir is None and not inline_files and not template_files:
        return

    if artifact_dir is not None:
        if not artifact_dir.exists():
            raise FileNotFoundError(
                f"Seed artifact directory not found: {artifact_dir}"
            )

        updated_paths = refresh_seed_artifact_manifests(
            artifact_dir, fix=update_manifests
        )
        if updated_paths and not update_manifests:
            raise ValueError(
                "Seed artifact manifest drift detected; rerun with --update-manifests."
            )

    worker = WorkerClient(base_url=worker_light_url, session_id=session_id)
    seeded_paths: list[str] = []
    try:
        for rel_path, content in template_files.items():
            await worker.write_file(
                rel_path,
                content,
                overwrite=True,
                bypass_agent_permissions=True,
            )
            seeded_paths.append(rel_path)

        if artifact_dir is not None:
            for path in _iter_seed_artifact_paths(artifact_dir):
                rel_path = path.relative_to(artifact_dir).as_posix()
                raw_bytes = path.read_bytes()
                try:
                    content = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    await worker.upload_file(
                        rel_path,
                        raw_bytes,
                        bypass_agent_permissions=True,
                    )
                else:
                    await worker.write_file(
                        rel_path,
                        content,
                        overwrite=True,
                        bypass_agent_permissions=True,
                    )
                seeded_paths.append(rel_path)

        for rel_path, content in inline_files.items():
            await worker.write_file(
                rel_path,
                content,
                overwrite=True,
                bypass_agent_permissions=True,
            )
            seeded_paths.append(rel_path)

    finally:
        await worker.aclose()

    logger.info(
        "eval_seed_workspace_applied",
        session_id=session_id,
        agent_name=agent_name,
        seed_file_count=len(seeded_paths),
        seeded_paths=seeded_paths,
    )


async def preflight_seeded_entry_contract(
    *,
    item: EvalDatasetItem,
    session_id: str,
    agent_name: AgentName,
    spec: AgentEvalSpec,
    root: Path,
    worker_light_url: str,
    logger: Any,
    workspace_client: Any | None = None,
) -> None:
    if item.seed_artifact_dir is None and not item.seed_files:
        return

    if spec.mode == EvalMode.BENCHMARK:
        target_node = spec.start_node or agent_name
        contracts = build_benchmark_node_contracts()
        graph = ValidationGraph.BENCHMARK
    elif spec.mode == EvalMode.AGENT:
        target_node = spec.start_node or agent_name
        contracts = build_engineer_node_contracts()
        graph = ValidationGraph.ENGINEER
    else:
        return

    contract = contracts.get(target_node)
    if contract is None:
        return
    if target_node == AgentName.ENGINEER_PLANNER:
        contract = contract.model_copy(update={"custom_check": None})

    custom_checks = {
        BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK: (
            lambda *, contract, state: (  # noqa: ARG005
                benchmark_plan_reviewer_handover_custom_check_from_session_id(
                    session_id=session_id,
                    worker_client=worker,
                )
            )
        ),
        BENCHMARK_CODER_HANDOVER_CHECK: (
            lambda *, contract, state: (  # noqa: ARG005
                benchmark_coder_handover_custom_check_from_session_id(
                    session_id=session_id,
                    custom_objectives=None,
                    worker_client=worker,
                )
            )
        ),
        BENCHMARK_REVIEWER_HANDOVER_CHECK: (
            lambda *, contract, state: reviewer_handover_custom_check_from_session_id(  # noqa: ARG005
                session_id=session_id,
                reviewer_label="Benchmark",
                manifest_path=".manifests/benchmark_review_manifest.json",
                expected_stage=AgentName.BENCHMARK_REVIEWER,
                worker_client=worker,
            )
        ),
        ENGINEER_BENCHMARK_HANDOVER_CHECK: (
            lambda *, contract, state: engineer_benchmark_handover_custom_check(
                contract=contract,
                state=state,
            )
        ),
        ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK: (
            lambda *, contract, state: (  # noqa: ARG005
                plan_reviewer_handover_custom_check_from_session_id(
                    session_id=session_id,
                    worker_client=worker,
                )
            )
        ),
        ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK: (
            lambda *, contract, state: engineer_planner_evidence_layout_custom_check(
                contract=contract,
                state=state,
            )
        ),
        ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK: (
            lambda *, contract, state: reviewer_handover_custom_check_from_session_id(  # noqa: ARG005
                session_id=session_id,
                reviewer_label="Execution",
                manifest_path=".manifests/engineering_execution_handoff_manifest.json",
                expected_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
                worker_client=worker,
            )
        ),
    }

    worker = workspace_client or WorkerClient(
        base_url=worker_light_url, session_id=session_id
    )
    owns_worker = workspace_client is None
    missing_seed_paths: list[str] = []
    supplemental_validation_errors: list[object] = []
    supplemental_messages: list[str] = []
    result = None
    artifact_exists = _plan_artifact_exists_fn(worker=worker, target_node=target_node)

    def add_message(message: str) -> None:
        normalized = str(message).strip()
        if normalized and normalized not in supplemental_messages:
            supplemental_messages.append(normalized)

    try:
        expected_seed_paths = collect_seed_workspace_artifact_paths(item, root=root)
        missing_seed_paths = await validate_workspace_has_artifacts(
            worker,
            artifact_paths=expected_seed_paths,
        )

        if missing_seed_paths:
            supplemental_messages.append(
                "Seeded workspace is missing copied seed artifact(s): "
                + ", ".join(missing_seed_paths)
            )

        try:
            result = await evaluate_node_entry_contract(
                contract=contract,
                state={
                    "task": item.task,
                    "episode_id": session_id,
                    "session_id": session_id,
                    "workspace_client": worker,
                    "worker_client": worker,
                    "session": {
                        "session_id": session_id,
                        "custom_objectives": None,
                    },
                },
                artifact_exists=artifact_exists,
                graph=graph,
                custom_checks=custom_checks,
                integration_mode=True,
            )
        except Exception as exc:
            add_message(
                f"Seeded entry contract evaluation failed for {target_node.value}: {exc}"
            )
        else:
            if not result.ok:
                supplemental_validation_errors.extend(result.errors)

        try:
            supplemental_errors = await validate_seeded_workspace_handoff_artifacts(
                worker_client=worker,
                target_node=target_node,
            )
        except Exception as exc:
            add_message(
                "Seeded workspace supplemental handoff validation failed for "
                f"{target_node.value}: {exc}"
            )
        else:
            supplemental_validation_errors.extend(supplemental_errors)
    finally:
        if owns_worker:
            await worker.aclose()

    if (
        not missing_seed_paths
        and not supplemental_validation_errors
        and not supplemental_messages
        and result is not None
        and result.ok
    ):
        logger.info(
            "eval_seed_entry_preflight_passed",
            session_id=session_id,
            agent_name=agent_name,
            target_node=target_node,
        )
        return

    raise SeededEntryContractError(
        SeededEntryContractFailure(
            session_id=session_id,
            agent_name=agent_name,
            target_node=target_node,
            missing_seed_paths=missing_seed_paths,
            entry_validation_result=result,
            supplemental_validation_errors=supplemental_validation_errors,
            supplemental_messages=supplemental_messages,
        )
    )
