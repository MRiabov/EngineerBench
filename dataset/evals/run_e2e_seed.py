from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.logic.models import E2EResumeStageRecord, EvalDatasetItem  # noqa: E402
from evals.logic.temp_paths import mkdtemp_in_eval_temp_root  # noqa: E402
from shared.enums import AgentName, ReviewDecision  # noqa: E402
from shared.logging import get_logger  # noqa: E402

logger = get_logger(__name__)
CLI_PROVIDERS = ("codex", "qwen")

DEFAULT_SEED_DIR = (
    ROOT / "dataset" / "data" / "seed" / "artifacts" / "e2e" / "e2e-001-drawing-full"
)
DEFAULT_TASK_ID = "e2e-001-drawing-full"


@dataclass(frozen=True, slots=True)
class StageSpec:
    agent_name: AgentName
    expected_decision: ReviewDecision | None = None
    requires_simulation_result: bool = False


@dataclass(slots=True)
class StageRunResult:
    agent_name: AgentName
    workspace_dir: Path
    session_id: str
    launch_return_code: int
    verification_name: str
    verification_success: bool
    simulation_success: bool | None
    review_decision: str | None


@dataclass(frozen=True, slots=True)
class ResumeHandle:
    agent_name: AgentName | None
    workspace_dir: Path | None

    def label(self) -> str:
        if self.agent_name is not None and self.workspace_dir is not None:
            return f"{self.agent_name.value}@{self.workspace_dir}"
        if self.workspace_dir is not None:
            return str(self.workspace_dir)
        if self.agent_name is not None:
            return self.agent_name.value
        return ""


STAGES: tuple[StageSpec, ...] = (
    StageSpec(AgentName.BENCHMARK_PLANNER),
    StageSpec(AgentName.BENCHMARK_PLAN_REVIEWER, ReviewDecision.APPROVED),
    StageSpec(AgentName.BENCHMARK_CODER, requires_simulation_result=True),
    StageSpec(AgentName.BENCHMARK_REVIEWER, ReviewDecision.APPROVED),
    StageSpec(AgentName.ENGINEER_PLANNER),
    StageSpec(AgentName.ENGINEER_PLAN_REVIEWER, ReviewDecision.APPROVED),
    StageSpec(AgentName.ENGINEER_CODER, requires_simulation_result=True),
    StageSpec(AgentName.ENGINEER_EXECUTION_REVIEWER, ReviewDecision.APPROVED),
)

RESUME_STATE_FILENAME = ".problemologist-e2e-seed.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the benchmark -> engineer smoke path from a human-written "
            "prompt seed using the local CLI provider helpers."
        )
    )
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=DEFAULT_SEED_DIR,
        help=(
            "Seed artifact directory containing human-written-description.md "
            f"(default: {DEFAULT_SEED_DIR.relative_to(ROOT)})"
        ),
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help=(
            "Optional root directory for stage workspaces and CLI runtime state. "
            "If omitted, a persistent temp directory is created under "
            "/tmp/problemologist-evals/e2e_seed/."
        ),
    )
    parser.add_argument(
        "--resume-from-dir",
        type=Path,
        default=None,
        help=(
            "Resume an existing e2e run from the given workspace root or stage "
            "workspace directory."
        ),
    )
    parser.add_argument(
        "--resume-from-agent",
        type=str,
        default=None,
        help=(
            "Resume from a stage handle. Accepts agent@workspace_dir, a "
            "workspace directory path, or an agent name when used with "
            "--resume-from-dir. Bare agent names require an existing "
            "checkpoint and no longer autodetect a stage from the workspace "
            "root."
        ),
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=os.getenv("PROBLEMOLOGIST_CLI_PROVIDER", "qwen"),
        choices=CLI_PROVIDERS,
        help="Local CLI provider to launch for each stage.",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Launch the CLI provider in bypass-approval mode.",
    )
    parser.add_argument(
        "--env-up",
        action="store_true",
        help="Run scripts/env_up.sh --profile eval before the e2e chain starts.",
    )
    parser.add_argument(
        "--open-cli-ui",
        action="store_true",
        help=(
            "Open the selected CLI provider UI on each materialized stage "
            "workspace before launching that stage."
        ),
    )
    parser.add_argument(
        "--new-terminal",
        action="store_true",
        help=(
            "When used with --open-cli-ui, open the UI in a separate terminal "
            "window instead of the current shell."
        ),
    )
    return parser.parse_args()


def _run_env_up() -> None:
    env_up_script = ROOT / "scripts" / "env_up.sh"
    subprocess.run(
        [str(env_up_script), "--profile", "eval"],
        cwd=ROOT,
        check=True,
    )


def _read_seed_prompt(seed_dir: Path) -> str:
    prompt_path = seed_dir / "human-written-description.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Seed prompt missing: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def _build_base_item(seed_dir: Path, prompt_text: str) -> EvalDatasetItem:
    try:
        seed_dataset = seed_dir.relative_to(ROOT)
    except ValueError:
        seed_dataset = None

    return EvalDatasetItem.model_validate(
        {
            "id": DEFAULT_TASK_ID,
            "task": prompt_text,
            "complexity_level": 0,
            "seed_dataset": seed_dataset,
            "seed_artifact_dir": seed_dir,
        }
    )


def _resume_state_path(workspace_root: Path) -> Path:
    return workspace_root / RESUME_STATE_FILENAME


def _load_resume_state(workspace_root: Path):
    from evals.logic.models import E2EResumeState

    state_path = _resume_state_path(workspace_root)
    if not state_path.exists():
        return None
    return E2EResumeState.model_validate_json(state_path.read_text(encoding="utf-8"))


def _save_resume_state(
    *,
    workspace_root: Path,
    seed_dir: Path,
    completed_stages: list[object],
) -> None:
    from evals.logic.models import E2EResumeState

    state = E2EResumeState.model_validate(
        {
            "seed_dir": seed_dir,
            "workspace_root": workspace_root,
            "stages": [stage.model_dump(mode="json") for stage in completed_stages],
        }
    )
    state_path = _resume_state_path(workspace_root)
    state_path.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _infer_agent_name_from_workspace_dir(workspace_dir: Path) -> AgentName | None:
    name = workspace_dir.name
    for agent in sorted(AgentName, key=lambda item: len(item.value), reverse=True):
        if name == agent.value or name.startswith(f"{agent.value}-"):
            return agent
    return None


def _parse_resume_handle(raw_handle: str | None) -> ResumeHandle | None:
    if raw_handle is None:
        return None

    handle = raw_handle.strip()
    if not handle:
        return None

    if "@" in handle:
        agent_text, workspace_text = handle.split("@", 1)
        agent_name = AgentName(agent_text) if agent_text.strip() else None
        workspace_dir = Path(workspace_text).expanduser().resolve()
        return ResumeHandle(agent_name=agent_name, workspace_dir=workspace_dir)

    workspace_candidate = Path(handle).expanduser()
    if workspace_candidate.exists():
        return ResumeHandle(
            agent_name=_infer_agent_name_from_workspace_dir(
                workspace_candidate.resolve()
            ),
            workspace_dir=workspace_candidate.resolve(),
        )

    try:
        return ResumeHandle(agent_name=AgentName(handle), workspace_dir=None)
    except ValueError as exc:
        raise SystemExit(
            f"Unsupported resume handle '{raw_handle}'. "
            "Use agent@workspace_dir, a workspace directory path, or an agent name."
        ) from exc


def _stage_index_for_agent(agent_name: AgentName) -> int:
    for index, stage in enumerate(STAGES):
        if stage.agent_name == agent_name:
            return index
    raise SystemExit(f"Unknown stage agent: {agent_name.value}")


def _resume_root_from_stage_dir(workspace_dir: Path) -> Path:
    if workspace_dir.parent.name == "workspaces":
        return workspace_dir.parent.parent
    return workspace_dir


def _stage_handle_for_result(result: StageRunResult) -> str:
    return f"{result.agent_name.value}@{result.workspace_dir}"


@dataclass(frozen=True, slots=True)
class ResumePlan:
    workspace_root: Path
    start_stage_index: int
    source_seed_dir: Path
    completed_stages: list[object]
    resume_label: str | None = None


def _latest_completed_stage_before(
    stages: list[E2EResumeStageRecord],
    *,
    stage_index: int,
) -> E2EResumeStageRecord | None:
    prior_stages = [stage for stage in stages if stage.stage_index < stage_index]
    if not prior_stages:
        return None
    latest_prior_stage = max(prior_stages, key=lambda stage: stage.stage_index)
    if latest_prior_stage.stage_index != stage_index - 1:
        return None
    return latest_prior_stage


def _build_resume_plan(
    *,
    seed_dir: Path,
    workspace_root: Path,
    resume_from_dir: Path | None,
    resume_from_agent: str | None,
) -> ResumePlan:

    if resume_from_dir is None and resume_from_agent is None:
        return ResumePlan(
            workspace_root=workspace_root,
            start_stage_index=0,
            source_seed_dir=seed_dir,
            completed_stages=[],
        )

    resume_root = workspace_root
    completed_stages: list[E2EResumeStageRecord] = []
    start_stage_index = 0
    source_seed_dir = seed_dir
    resume_label: str | None = None
    selected_stage_index: int | None = None
    resume_state = None

    if resume_from_dir is not None:
        resume_root = resume_from_dir.expanduser().resolve()
        if (resume_root / "prompt.md").exists():
            stage_agent = _infer_agent_name_from_workspace_dir(resume_root)
            if stage_agent is None:
                raise SystemExit(
                    f"Could not infer agent name from stage workspace: {resume_root}"
                )
            selected_stage_index = _stage_index_for_agent(stage_agent)
            start_stage_index = selected_stage_index + 1
            source_seed_dir = resume_root
            resume_label = str(resume_root)
            resume_root = _resume_root_from_stage_dir(resume_root)
        else:
            resume_state = _load_resume_state(resume_root)
            if resume_state is None:
                raise SystemExit(
                    f"Resume state missing from {resume_root}. "
                    f"Expected {_resume_state_path(resume_root)} or an explicit "
                    "stage workspace directory."
                )
            completed_stages = list(resume_state.stages)
            if completed_stages:
                last_stage = completed_stages[-1]
                selected_stage_index = last_stage.stage_index
                start_stage_index = selected_stage_index + 1
                source_seed_dir = last_stage.workspace_dir
                resume_label = (
                    f"{last_stage.agent_name.value}@{last_stage.workspace_dir}"
                )
                resume_root = resume_state.workspace_root

    handle = _parse_resume_handle(resume_from_agent)
    if handle is not None:
        if (
            handle.workspace_dir is not None
            and (handle.workspace_dir / "prompt.md").exists()
        ):
            stage_agent = handle.agent_name or _infer_agent_name_from_workspace_dir(
                handle.workspace_dir
            )
            if stage_agent is None:
                raise SystemExit(
                    f"Could not infer agent name from resume handle: {resume_from_agent}"
                )
            resume_root = _resume_root_from_stage_dir(handle.workspace_dir)
            selected_stage_index = _stage_index_for_agent(stage_agent)
            start_stage_index = selected_stage_index + 1
            source_seed_dir = handle.workspace_dir
            resume_label = handle.label()
        elif handle.agent_name is not None:
            if resume_state is None:
                raise SystemExit(
                    "Bare resume-from-agent names require an existing checkpoint "
                    f"under {resume_root}."
                )
            target_stage_index = _stage_index_for_agent(handle.agent_name)
            previous_stage = _latest_completed_stage_before(
                list(resume_state.stages), stage_index=target_stage_index
            )
            if previous_stage is None and target_stage_index > 0:
                previous_name = STAGES[target_stage_index - 1].agent_name.value
                raise SystemExit(
                    f"Cannot resume {handle.agent_name.value} without a completed "
                    f"{previous_name} stage in {resume_root}."
                )
            if previous_stage is None:
                source_seed_dir = seed_dir
            else:
                source_seed_dir = previous_stage.workspace_dir
            completed_stages = [
                stage
                for stage in resume_state.stages
                if stage.stage_index < target_stage_index
            ]
            selected_stage_index = target_stage_index
            start_stage_index = selected_stage_index
            resume_label = f"{handle.agent_name.value}@{source_seed_dir}"

    if selected_stage_index is not None and completed_stages:
        completed_stages = [
            stage
            for stage in completed_stages
            if stage.stage_index <= selected_stage_index
        ]

    return ResumePlan(
        workspace_root=resume_root,
        start_stage_index=start_stage_index,
        source_seed_dir=source_seed_dir,
        completed_stages=completed_stages,
        resume_label=resume_label,
    )


def _simulation_success(workspace_dir: Path) -> bool | None:
    simulation_path = workspace_dir / "simulation_result.json"
    if not simulation_path.exists():
        return None
    try:
        payload = simulation_path.read_text(encoding="utf-8")
        from shared.models.simulation import SimulationResult

        return bool(SimulationResult.model_validate_json(payload).success)
    except Exception:
        return False


def _format_verification_errors(errors: list[str]) -> str:
    if not errors:
        return "unknown verification failure"
    return "; ".join(errors)


async def _run_stage(
    *,
    stage: StageSpec,
    item: EvalDatasetItem,
    workspace_root: Path,
    provider_name: str,
    yolo: bool,
    source_seed_dir: Path,
    open_cli_ui_requested: bool,
    open_cli_ui_new_terminal: bool,
) -> StageRunResult:
    from evals.logic.codex_workspace import (
        LocalWorkspaceClient,
        launch_cli_exec,
        materialize_seed_workspace,
        open_cli_ui,
        verify_workspace_for_agent,
    )
    from evals.logic.specs import AGENT_SPECS
    from evals.logic.workspace import preflight_seeded_entry_contract

    stage_workspace_dir = (
        workspace_root
        / "workspaces"
        / f"{stage.agent_name.value}-{uuid.uuid4().hex[:8]}"
    )
    stage_workspace_dir.parent.mkdir(parents=True, exist_ok=True)

    stage_item = item.model_copy(update={"seed_artifact_dir": source_seed_dir})
    materialized = materialize_seed_workspace(
        item=stage_item,
        agent_name=stage.agent_name,
        workspace_dir=stage_workspace_dir,
    )

    session_id = f"e2e-seed-{stage.agent_name.value}-{item.id}-{uuid.uuid4().hex[:8]}"
    worker_client = LocalWorkspaceClient(
        root=materialized.workspace_dir,
        session_id=session_id,
    )
    spec = AGENT_SPECS[stage.agent_name]
    await preflight_seeded_entry_contract(
        item=stage_item,
        session_id=session_id,
        agent_name=stage.agent_name,
        spec=spec,
        root=ROOT,
        worker_light_url=os.getenv("WORKER_LIGHT_URL", "http://localhost:18001"),
        logger=logger,
        workspace_client=worker_client,
    )

    if open_cli_ui_requested:
        launch_return_code = await asyncio.to_thread(
            open_cli_ui,
            materialized.workspace_dir,
            materialized.prompt_text,
            task_id=item.id,
            agent_name=stage.agent_name,
            session_id=session_id,
            runtime_root=workspace_root,
            yolo=yolo,
            provider_name=provider_name,
            new_terminal=open_cli_ui_new_terminal,
        )
    else:
        launch_return_code = await asyncio.to_thread(
            launch_cli_exec,
            materialized.workspace_dir,
            materialized.prompt_text,
            task_id=item.id,
            agent_name=stage.agent_name,
            session_id=session_id,
            runtime_root=workspace_root,
            yolo=yolo,
            provider_name=provider_name,
        )

    verification = await verify_workspace_for_agent(
        workspace_dir=materialized.workspace_dir,
        agent_name=stage.agent_name,
        session_id=session_id,
        expected_decision=stage.expected_decision,
    )
    sim_success = _simulation_success(materialized.workspace_dir)

    review_decision = None
    details = verification.details if isinstance(verification.details, dict) else {}
    review_data = details.get("review_decision") if isinstance(details, dict) else None
    if isinstance(review_data, dict):
        review_decision = str(review_data.get("decision") or "").strip() or None

    return StageRunResult(
        agent_name=stage.agent_name,
        workspace_dir=materialized.workspace_dir,
        session_id=session_id,
        launch_return_code=launch_return_code,
        verification_name=verification.verification_name,
        verification_success=verification.success,
        simulation_success=sim_success,
        review_decision=review_decision,
    )


def _print_stage_result(result: StageRunResult) -> None:
    print(
        f"[{result.agent_name.value}] workspace={result.workspace_dir} "
        f"resume_from_dir={_resume_root_from_stage_dir(result.workspace_dir)} "
        f"resume_from_agent={_stage_handle_for_result(result)} "
        f"launch_rc={result.launch_return_code} "
        f"verification={result.verification_name}:{result.verification_success} "
        f"simulation_success={result.simulation_success} "
        f"review_decision={result.review_decision}"
    )


async def _run_chain(args: argparse.Namespace) -> int:
    if args.env_up:
        _run_env_up()

    seed_dir = args.seed_dir.expanduser().resolve()
    prompt_text = _read_seed_prompt(seed_dir)
    base_item = _build_base_item(seed_dir, prompt_text)

    if args.workspace_root is not None and args.resume_from_dir is not None:
        raise SystemExit("--workspace-root cannot be combined with --resume-from-dir.")
    if args.resume_from_agent is not None and args.resume_from_dir is None:
        parsed_handle = _parse_resume_handle(args.resume_from_agent)
        if (
            parsed_handle is not None
            and parsed_handle.agent_name is not None
            and parsed_handle.workspace_dir is None
        ):
            raise SystemExit(
                "--resume-from-agent requires --resume-from-dir unless the handle includes a workspace directory."
            )

    if args.resume_from_dir is not None:
        workspace_root = args.resume_from_dir.expanduser().resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
    elif args.workspace_root is None:
        workspace_root = mkdtemp_in_eval_temp_root(
            family_name="e2e_seed",
            prefix="problemologist-e2e-seed-",
        )
    else:
        workspace_root = args.workspace_root.expanduser().resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)

    resume_plan = _build_resume_plan(
        seed_dir=seed_dir,
        workspace_root=workspace_root,
        resume_from_dir=args.resume_from_dir,
        resume_from_agent=args.resume_from_agent,
    )
    workspace_root = resume_plan.workspace_root
    workspace_root.mkdir(parents=True, exist_ok=True)

    print(f"workspace_root={workspace_root}")
    print(f"seed_dir={seed_dir}")
    if resume_plan.resume_label is not None:
        print(f"resume_from={resume_plan.resume_label}")

    source_seed_dir = resume_plan.source_seed_dir
    last_result: StageRunResult | None = None
    completed_stages = list(resume_plan.completed_stages)

    if resume_plan.start_stage_index >= len(STAGES):
        if last_completed := (completed_stages[-1] if completed_stages else None):
            print(f"final_workspace={last_completed.workspace_dir}")
        return 0

    if resume_plan.start_stage_index > 0:
        print(
            f"resume_stage_index={resume_plan.start_stage_index} "
            f"completed_stages={len(completed_stages)}"
        )

    for stage_index, stage in enumerate(
        STAGES[resume_plan.start_stage_index :], start=resume_plan.start_stage_index
    ):
        result = await _run_stage(
            stage=stage,
            item=base_item,
            workspace_root=workspace_root,
            provider_name=args.provider,
            yolo=args.yolo,
            source_seed_dir=source_seed_dir,
            open_cli_ui_requested=args.open_cli_ui,
            open_cli_ui_new_terminal=args.new_terminal,
        )
        _print_stage_result(result)

        failure_reasons: list[str] = []
        if result.launch_return_code != 0:
            failure_reasons.append(f"launch exited with {result.launch_return_code}")
        if not result.verification_success:
            failure_reasons.append(f"verification failed: {result.verification_name}")
        if stage.requires_simulation_result:
            if result.simulation_success is False:
                failure_reasons.append("simulation_result.json reported failure")
            if result.simulation_success is None:
                failure_reasons.append("simulation_result.json missing")
        if stage.expected_decision is not None and result.review_decision is None:
            failure_reasons.append(
                f"review decision missing: expected {stage.expected_decision.value}"
            )
        if (
            stage.expected_decision is not None
            and result.review_decision is not None
            and result.review_decision != stage.expected_decision.value
        ):
            failure_reasons.append(
                f"review decision mismatch: expected {stage.expected_decision.value}, "
                f"got {result.review_decision}"
            )

        if failure_reasons:
            print(
                f"[{stage.agent_name.value}] failed: "
                + _format_verification_errors(failure_reasons)
            )
            return 1

        source_seed_dir = result.workspace_dir
        from evals.logic.models import E2EResumeStageRecord

        completed_stages.append(
            E2EResumeStageRecord(
                stage_index=stage_index,
                agent_name=result.agent_name,
                workspace_dir=result.workspace_dir,
                session_id=result.session_id,
                launch_return_code=result.launch_return_code,
                verification_name=result.verification_name,
                verification_success=result.verification_success,
                simulation_success=result.simulation_success,
                review_decision=result.review_decision,
            )
        )
        _save_resume_state(
            workspace_root=workspace_root,
            seed_dir=seed_dir,
            completed_stages=completed_stages,
        )
        last_result = result

    if last_result is not None:
        print(f"final_workspace={last_result.workspace_dir}")
    return 0


def main() -> None:
    args = _parse_args()
    if args.new_terminal and not args.open_cli_ui:
        raise SystemExit("--new-terminal requires --open-cli-ui.")
    raise SystemExit(asyncio.run(_run_chain(args)))


if __name__ == "__main__":
    main()
