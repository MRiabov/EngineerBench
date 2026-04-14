#!/usr/bin/env python3
"""Validate integration mock-response inputs via node-entry preflight.

This script is stricter than the fixture normalizer:

- it loads `tests/integration/mock_responses/*.yaml` and validates transcript
  schema plus all referenced `content_file` / `template_file` payloads
- it seeds a temporary worker session with the baseline benchmark context used
  by the engineering intake
- it replays each scenario's `entry_*` fixture directories cumulatively and
  validates them with the real node-entry contract helper
- it then runs seeded workspace handoff validation so schema mismatches and
  missing handoff artifacts fail closed
- it is intentionally happy-path only for the current `INT-###` corpus and
  does not try to infer or special-case future negative-test semantics

Reviewer-only transcript nodes are skipped when the scenario does not include a
corresponding preflightable artifact directory. Those nodes are materialized by
runtime handoff logic, not by the static fixture inputs themselves.

Backend-owned `.manifests/current_role.json` fixtures are treated specially:
they are required inside each entry directory, validated against the active
node, and written into the workspace separately from authored `write_file`
steps so the corpus can carry the manifest without inflating the transcript
count.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
MOCK_RESPONSES_ROOT = ROOT / "tests" / "integration" / "mock_responses"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.logic.stack_profiles import apply_stack_profile_env  # noqa: E402

apply_stack_profile_env("integration", env=os.environ, root=ROOT)

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
MANUFACTURING_CONFIG_TEXT = (
    ROOT / "worker_heavy" / "workbenches" / "manufacturing_config.yaml"
).read_text(encoding="utf-8")

from controller.agent.mock_scenarios import load_integration_mock_scenarios
from controller.agent.node_entry_validation import (
    BENCHMARK_CODER_HANDOVER_CHECK,
    BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK,
    BENCHMARK_REVIEWER_HANDOVER_CHECK,
    ENGINEER_BENCHMARK_HANDOVER_CHECK,
    ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK,
    ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK,
    NodeEntryValidationError,
    ValidationGraph,
    build_benchmark_node_contracts,
    build_engineer_node_contracts,
    evaluate_node_entry_contract,
    validate_seeded_workspace_handoff_artifacts,
)
from controller.clients.worker import WorkerClient
from shared.current_role import parse_current_role_manifest
from shared.enums import AgentName
from shared.logging import get_logger
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    BenchmarkDefinition,
    CostTotals,
)
from shared.script_contracts import CURRENT_ROLE_MANIFEST_PATH

logger = get_logger(__name__)

ENGINEER_CONTRACTS = build_engineer_node_contracts()
BENCHMARK_CONTRACTS = build_benchmark_node_contracts()


async def _no_op_custom_check(
    *,
    contract,
    state,  # noqa: ARG001
) -> list[NodeEntryValidationError]:
    return []


def _benchmark_assembly_definition_content(
    *,
    benchmark_max_unit_cost_usd: float = 200.0,
    benchmark_max_weight_g: float = 1000.0,
    planner_target_max_unit_cost_usd: float | None = None,
    planner_target_max_weight_g: float | None = None,
    estimated_unit_cost_usd: float = 0.0,
    estimated_weight_g: float = 0.0,
    estimate_confidence: str = "medium",
) -> str:
    planner_target_max_unit_cost_usd = (
        benchmark_max_unit_cost_usd
        if planner_target_max_unit_cost_usd is None
        else planner_target_max_unit_cost_usd
    )
    planner_target_max_weight_g = (
        benchmark_max_weight_g
        if planner_target_max_weight_g is None
        else planner_target_max_weight_g
    )
    assembly = AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            planner_target_max_unit_cost_usd=planner_target_max_unit_cost_usd,
            planner_target_max_weight_g=planner_target_max_weight_g,
        ),
        manufactured_parts=[],
        cots_parts=[],
        final_assembly=[],
        totals=CostTotals(
            estimated_unit_cost_usd=estimated_unit_cost_usd,
            estimated_weight_g=estimated_weight_g,
            estimate_confidence=estimate_confidence,
        ),
    )
    return yaml.safe_dump(
        assembly.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=False,
    )


def _scenario_ids_from_args(
    args: argparse.Namespace,
    all_scenarios: dict[str, dict[str, object]],
) -> list[str]:
    selected: list[str] = []

    if args.all:
        selected.extend(sorted(all_scenarios))

    for scenario_id in args.scenario:
        if scenario_id not in all_scenarios:
            raise FileNotFoundError(f"Unknown integration scenario: {scenario_id}")
        selected.append(scenario_id)

    for raw_path in args.path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = (ROOT / path).resolve()

        scenario_id = None
        if path.is_file() and path.suffix in {".yaml", ".yml"}:
            scenario_id = path.stem
        else:
            for parent in [path, *path.parents]:
                if parent.parent == MOCK_RESPONSES_ROOT and parent.name.startswith(
                    "INT-"
                ):
                    scenario_id = parent.name
                    break

        if scenario_id is None:
            raise FileNotFoundError(
                f"Unable to infer integration scenario from path: {raw_path}"
            )
        if scenario_id not in all_scenarios:
            raise FileNotFoundError(f"Unknown integration scenario: {scenario_id}")
        selected.append(scenario_id)

    if not selected:
        raise SystemExit("Provide at least one --scenario, --path, or --all target.")

    return list(dict.fromkeys(selected))


def _scenario_node_entry_dirs(scenario_id: str) -> list[tuple[AgentName, Path]]:
    scenario_root = MOCK_RESPONSES_ROOT / scenario_id
    if not scenario_root.exists():
        raise FileNotFoundError(f"Scenario directory not found: {scenario_root}")
    if not scenario_root.is_dir():
        raise ValueError(f"Scenario path must be a directory: {scenario_root}")

    pairs: list[tuple[AgentName, Path]] = []
    for node_dir in sorted(p for p in scenario_root.iterdir() if p.is_dir()):
        try:
            agent_name = AgentName(node_dir.name)
        except ValueError:
            continue

        entry_dirs = sorted(
            entry_dir for entry_dir in node_dir.iterdir() if entry_dir.is_dir()
        )
        for entry_dir in entry_dirs:
            pairs.append((agent_name, entry_dir))

    return pairs


def _node_write_paths(node_block: dict[str, object]) -> list[str]:
    write_paths: list[str] = []
    steps = node_block.get("steps")
    if not isinstance(steps, list):
        return write_paths

    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("tool_name") != "write_file":
            continue
        tool_args = step.get("tool_args")
        if not isinstance(tool_args, dict):
            continue
        path = tool_args.get("path")
        if isinstance(path, str) and path.strip():
            write_paths.append(path)
    return write_paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate tests/integration/mock_responses via node-entry preflight."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Validate one INT-### scenario directory (repeatable).",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Validate a scenario file or scenario/entry directory (repeatable).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate every scenario under tests/integration/mock_responses.",
    )
    parser.add_argument(
        "--skip-env-up",
        action="store_true",
        help="Skip scripts/env_up.sh before validation.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first invalid scenario entry.",
    )
    return parser.parse_args()


def _run_env_up() -> None:
    env_up_path = ROOT / "scripts" / "env_up.sh"
    result = subprocess.run(
        [str(env_up_path), "--profile", "integration"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def _custom_checks() -> dict[str, object]:
    # Offline fixture validation cannot reproduce the DB-backed approval state
    # used by the live engine, so the fixture validator treats those gates as
    # preflight-safe no-ops and relies on seeded workspace validation for the
    # file-backed contract surface.
    return {
        BENCHMARK_CODER_HANDOVER_CHECK: _no_op_custom_check,
        BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK: _no_op_custom_check,
        BENCHMARK_REVIEWER_HANDOVER_CHECK: _no_op_custom_check,
        ENGINEER_BENCHMARK_HANDOVER_CHECK: _no_op_custom_check,
        ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK: _no_op_custom_check,
        ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK: _no_op_custom_check,
    }


def _resolve_contract(
    agent_name: AgentName,
) -> tuple[object, ValidationGraph] | tuple[None, None]:
    engineer_contract = ENGINEER_CONTRACTS.get(agent_name)
    benchmark_contract = BENCHMARK_CONTRACTS.get(agent_name)

    if engineer_contract is not None and benchmark_contract is None:
        return engineer_contract, ValidationGraph.ENGINEER
    if benchmark_contract is not None and engineer_contract is None:
        return benchmark_contract, ValidationGraph.BENCHMARK
    if engineer_contract is not None and benchmark_contract is not None:
        # Shared helper nodes exist in both graphs. In the fixture corpus we
        # only validate the first-class planning/coding nodes, so default to the
        # engineer graph when a shared helper is encountered.
        return engineer_contract, ValidationGraph.ENGINEER
    return None, None


async def _sync_workspace(
    worker: WorkerClient,
    workspace_root: Path,
) -> None:
    for file_path in sorted(p for p in workspace_root.rglob("*") if p.is_file()):
        rel_path = file_path.relative_to(workspace_root).as_posix()
        ok = await worker.upload_file(
            rel_path,
            file_path.read_bytes(),
            bypass_agent_permissions=True,
        )
        if not ok:
            raise RuntimeError(f"Failed to upload {workspace_root / rel_path}.")


def _seed_workspace_root(workspace_root: Path) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "manufacturing_config.yaml").write_text(
        MANUFACTURING_CONFIG_TEXT,
        encoding="utf-8",
    )


def _apply_entry_dir_to_workspace(
    *,
    workspace_root: Path,
    entry_dir: Path,
    target_paths: list[str],
    agent_name: AgentName,
) -> None:
    current_role_path = entry_dir / CURRENT_ROLE_MANIFEST_PATH
    if not current_role_path.is_file():
        raise RuntimeError(
            f"Entry dir {entry_dir} is missing required backend manifest "
            f"{CURRENT_ROLE_MANIFEST_PATH.as_posix()}."
        )

    current_role_content = current_role_path.read_text(encoding="utf-8")
    try:
        current_role_manifest = parse_current_role_manifest(current_role_content)
    except Exception as exc:  # pragma: no cover - defensive validation
        raise RuntimeError(
            f"Entry dir {entry_dir} has invalid current role manifest "
            f"{CURRENT_ROLE_MANIFEST_PATH.as_posix()}: {exc}"
        ) from exc
    if current_role_manifest.agent_name != agent_name:
        raise RuntimeError(
            f"Entry dir {entry_dir} current role "
            f"{current_role_manifest.agent_name.value} does not match transcript "
            f"node {agent_name.value}."
        )

    entry_files = sorted(
        p
        for p in entry_dir.rglob("*")
        if p.is_file() and p.relative_to(entry_dir) != CURRENT_ROLE_MANIFEST_PATH
    )
    if len(entry_files) != len(target_paths):
        raise RuntimeError(
            f"Entry dir {entry_dir} has {len(entry_files)} files but the node "
            f"transcript declares {len(target_paths)} write_file steps."
        )

    for source_path, target_path in zip(entry_files, target_paths, strict=True):
        dest_path = workspace_root / target_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(source_path.read_bytes())

    workspace_current_role_path = workspace_root / CURRENT_ROLE_MANIFEST_PATH
    workspace_current_role_path.parent.mkdir(parents=True, exist_ok=True)
    workspace_current_role_path.write_text(current_role_content, encoding="utf-8")


def _seed_benchmark_assembly_from_benchmark_definition(
    workspace_root: Path,
) -> None:
    benchmark_definition_path = workspace_root / "benchmark_definition.yaml"
    benchmark_assembly_path = workspace_root / "benchmark_assembly_definition.yaml"
    if benchmark_assembly_path.exists() or not benchmark_definition_path.exists():
        return

    benchmark_definition = BenchmarkDefinition.model_validate(
        yaml.safe_load(benchmark_definition_path.read_text(encoding="utf-8"))
    )
    benchmark_max_unit_cost = benchmark_definition.constraints.max_unit_cost
    benchmark_max_weight_g = benchmark_definition.constraints.max_weight_g
    if benchmark_max_unit_cost is None or benchmark_max_weight_g is None:
        return

    benchmark_assembly_path.write_text(
        _benchmark_assembly_definition_content(
            benchmark_max_unit_cost_usd=float(benchmark_max_unit_cost),
            benchmark_max_weight_g=float(benchmark_max_weight_g),
            planner_target_max_unit_cost_usd=float(benchmark_max_unit_cost),
            planner_target_max_weight_g=float(benchmark_max_weight_g),
        ),
        encoding="utf-8",
    )


async def _validate_entry(
    *,
    worker: WorkerClient,
    scenario_id: str,
    agent_name: AgentName,
) -> None:
    contract, graph = _resolve_contract(agent_name)
    if contract is None or graph is None:
        raise RuntimeError(f"No node-entry contract registered for {agent_name.value}.")

    state = {
        "task": scenario_id,
        "episode_id": worker.session_id,
        "session": {
            "session_id": worker.session_id,
            "custom_objectives": None,
        },
    }

    result = await evaluate_node_entry_contract(
        contract=contract,
        state=state,
        artifact_exists=worker.exists,
        graph=graph,
        custom_checks=_custom_checks(),
        integration_mode=True,
    )
    if not result.ok:
        raise ValueError(
            "; ".join(f"{error.code}: {error.message}" for error in result.errors)
        )

    supplemental_errors = await validate_seeded_workspace_handoff_artifacts(
        worker_client=worker,
        target_node=agent_name,
    )
    if supplemental_errors:
        raise ValueError(
            "; ".join(f"{error.code}: {error.message}" for error in supplemental_errors)
        )


async def _validate_scenario(
    scenario_id: str,
    *,
    fail_fast: bool,
    scenarios: dict[str, dict[str, object]],
) -> tuple[list[str], list[str]]:
    scenario = scenarios.get(scenario_id)
    if scenario is None:
        return [f"scenario missing from loader: {scenario_id}"], []

    transcript = scenario.get("transcript") or []
    try:
        node_entry_dirs = _scenario_node_entry_dirs(scenario_id)
    except FileNotFoundError as exc:
        return [], [
            f"{scenario_id}: skipping because no scenario directory is present ({exc})"
        ]
    node_entry_lookup: dict[str, list[Path]] = {}
    for agent_name, entry_dir in node_entry_dirs:
        node_entry_lookup.setdefault(agent_name.value, []).append(entry_dir)

    session_id = f"mock-preflight-{scenario_id}-{uuid.uuid4().hex}"
    warnings: list[str] = []
    errors: list[str] = []

    tmp_root = Path(tempfile.mkdtemp(prefix=f"mock-preflight-{scenario_id}-"))
    workspace_root = tmp_root / "workspace"
    try:
        _seed_workspace_root(workspace_root)

        async with httpx.AsyncClient() as http_client:
            seed_worker = WorkerClient(
                base_url=WORKER_LIGHT_URL,
                session_id=session_id,
                http_client=http_client,
                agent_role=AgentName.ENGINEER_CODER,
            )
            try:
                await _sync_workspace(seed_worker, workspace_root)

                for node_block in transcript:
                    node_name = node_block.get("node")
                    if not isinstance(node_name, str):
                        continue

                    try:
                        agent_name = AgentName(node_name)
                    except ValueError:
                        warnings.append(
                            f"{scenario_id}: skipping unknown node '{node_name}'"
                        )
                        continue

                    entry_dirs = node_entry_lookup.get(agent_name.value, [])
                    if not entry_dirs:
                        warnings.append(
                            f"{scenario_id}: skipping {agent_name.value} because no "
                            "preflightable entry_* directory is present"
                        )
                        continue

                    for entry_dir in entry_dirs:
                        try:
                            _apply_entry_dir_to_workspace(
                                workspace_root=workspace_root,
                                entry_dir=entry_dir,
                                target_paths=_node_write_paths(node_block),
                                agent_name=agent_name,
                            )
                            _seed_benchmark_assembly_from_benchmark_definition(
                                workspace_root
                            )
                            await _sync_workspace(seed_worker, workspace_root)
                            validation_worker = WorkerClient(
                                base_url=WORKER_LIGHT_URL,
                                session_id=session_id,
                                http_client=http_client,
                                agent_role=agent_name,
                            )
                            await _validate_entry(
                                worker=validation_worker,
                                scenario_id=scenario_id,
                                agent_name=agent_name,
                            )
                        except Exception as exc:
                            errors.append(
                                f"{scenario_id}:{agent_name.value}:{entry_dir.name}: {exc}"
                            )
                            if fail_fast:
                                return errors, warnings
            finally:
                await seed_worker.aclose()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    return errors, warnings


async def _async_main(args: argparse.Namespace) -> int:
    scenarios = load_integration_mock_scenarios()
    scenario_ids = _scenario_ids_from_args(args, scenarios)

    logger.warning(
        "mock_preflight_happy_path_only",
        message=(
            "!!! important validation warning !!! "
            "This validator checks happy-path mock-response fixtures only. "
            "It does not account for explicit-failure cases. Before treating a "
            "failure as a fixture defect, check specs/integration-test-rules.md and "
            "specs/integration-test-list.md to confirm whether the case is "
            "intentionally negative or actually invalid. "
            "--- validation warning end ---"
        ),
    )

    if not args.skip_env_up:
        _run_env_up()

    all_errors: list[str] = []
    all_warnings: list[str] = []
    for scenario_id in scenario_ids:
        errors, warnings = await _validate_scenario(
            scenario_id,
            fail_fast=args.fail_fast,
            scenarios=scenarios,
        )
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        if errors and args.fail_fast:
            break

    for warning in all_warnings:
        logger.info("mock_preflight_skip", message=warning)

    if all_errors:
        print("validation errors:")
        for error in all_errors:
            print(f"- {error}")
        return 1

    print(f"validated {len(scenario_ids)} scenario(s) via node-entry preflight.")
    if all_warnings:
        print(f"skipped {len(all_warnings)} reviewer-only / non-preflightable node(s).")
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
