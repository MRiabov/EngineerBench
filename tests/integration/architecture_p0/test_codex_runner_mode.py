from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from build123d import Box, BuildPart

from controller.agent.prompt_manager import PromptManager
from controller.prompts import load_prompts
from evals.logic import runner
from evals.logic.cli_provider import (
    CliInvocation,
    CodexCliProvider,
    PiCliProvider,
    QwenCliProvider,
    get_cli_provider,
)
from evals.logic.codex_session_trace import (
    CodexSessionTraceArtifact,
    diff_workspace_snapshots,
)
from evals.logic.codex_workspace import (
    CodexExecRunResult,
    build_cli_env,
    launch_cli_exec,
    materialize_seed_workspace,
    open_cli_ui,
    prepare_cli_home,
    resolve_cli_home_root,
    resume_cli_exec,
    verify_planner_workspace,
)
from evals.logic.models import EvalDatasetItem
from evals.logic.seed_maintenance import refresh_plan_review_manifest_hashes
from shared.agents.config import AgentsConfig
from shared.current_role import current_role_manifest_json, parse_current_role_manifest
from shared.enums import AgentName, ManufacturingMethod, ReviewDecision
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    CostTotals,
    DatasetCurationManifest,
    PartMetadata,
    PlannerSubmissionResult,
)
from shared.workers.bundling import extract_bundle_base64
from tests.integration.agent.helpers import (
    REPO_MANUFACTURING_CONFIG,
    _fixture_entry_file_content,
)
from worker_renderer.utils.build123d_rendering import (
    export_preview_scene_bundle,
    render_preview_view,
)

ROOT = Path(__file__).resolve().parents[3]
CODEX_FIXTURE_ARTIFACT_DIR = (
    ROOT
    / "tests"
    / "integration"
    / "fixtures"
    / "codex_runner_mode"
    / "artifacts"
    / "common"
)
AGENTS_CONFIG_PATH = Path("config/agents_config.yaml")
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
pytestmark = pytest.mark.xdist_group(name="eval_runner")


def _validate_eval_seed_env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), pythonpath] if pythonpath else [str(ROOT)]
    )
    env.update(extra)
    return env


def _run_validate_eval_seed(
    *args: str, timeout: int = 300
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/validate_eval_seed.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=_validate_eval_seed_env(),
    )


def _load_dataset_item(_dataset_rel_path: str, row_id: str) -> EvalDatasetItem:
    dataset_path = ROOT / _dataset_rel_path
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)

    dataset_rows = json.loads(dataset_path.read_text(encoding="utf-8"))
    row = next((row for row in dataset_rows if row["id"] == row_id), None)
    if row is None:
        raise KeyError(f"Row {row_id!r} not found in {dataset_path}")
    return EvalDatasetItem.model_validate(
        {
            **row,
            "seed_dataset": dataset_path.relative_to(ROOT),
        }
    )


def _synthetic_planner_item(agent_name: AgentName, item_id: str) -> EvalDatasetItem:
    def _normalize_benchmark_definition_content(
        benchmark_definition_content: str,
    ) -> str:
        benchmark_definition = yaml.safe_load(benchmark_definition_content) or {}
        physics = benchmark_definition.get("physics")
        if isinstance(physics, dict) and "fem_enabled" in physics:
            physics = dict(physics)
            physics.pop("fem_enabled", None)
            benchmark_definition["physics"] = physics
        return yaml.safe_dump(benchmark_definition, sort_keys=False)

    def _minimal_benchmark_assembly_definition_content(
        benchmark_definition_content: str,
    ) -> str:
        benchmark_definition = yaml.safe_load(benchmark_definition_content) or {}
        constraints = benchmark_definition.get("constraints") or {}
        max_unit_cost = float(constraints["max_unit_cost"])
        max_weight_g = float(constraints["max_weight_g"])
        benchmark_assembly_definition = AssemblyDefinition(
            version="1.0",
            constraints=AssemblyConstraints(
                benchmark_max_unit_cost_usd=max_unit_cost,
                benchmark_max_weight_g=max_weight_g,
                planner_target_max_unit_cost_usd=max_unit_cost,
                planner_target_max_weight_g=max_weight_g,
            ),
            manufactured_parts=[],
            final_assembly=[],
            totals=CostTotals(
                estimated_unit_cost_usd=0.0,
                estimated_weight_g=0.0,
                estimate_confidence="high",
            ),
        )
        return yaml.safe_dump(
            benchmark_assembly_definition.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            sort_keys=False,
        )

    if agent_name == AgentName.BENCHMARK_PLANNER:
        benchmark_definition_content = _normalize_benchmark_definition_content(
            _fixture_entry_file_content(
                "INT-204",
                filename_suffix="benchmark_definition.yaml",
                node="benchmark_planner",
            )
        )
        return EvalDatasetItem(
            id=item_id,
            task="benchmark planner workspace contract smoke test",
            complexity_level=0,
            seed_dataset=None,
            seed_files={
                "benchmark_plan.md": textwrap.dedent(
                    """
                    ## 1. Learning Objective

                    Show a solvable benchmark for `projectile_ball` moving through
                    the open corridor toward the goal zone.

                    ## 2. Static Geometry

                    - `open_corridor_frame` keeps the corridor open between the
                      spawn side and the goal zone.
                    - The geometry stays inside the declared build zone.

                    ## 3. Input Object

                    - `projectile_ball` starts on the spawn side and remains a
                      single moving payload.

                    ## 4. Objectives

                    - Reach the goal zone without colliding with any forbid zone.

                    ## 5. Design

                    - Keep the path open and legible for downstream implementation.

                    ## 6. Randomization

                    - Use the declared open-corridor variation and no runtime
                      jitter beyond the seeded policy.

                    ## 7. Build123d Strategy

                    - Build the visible fixture with labeled, metadata-complete
                      parts so reviewers can inspect the scene directly.

                    ## 8. Cost & Weight Envelope

                    - Respect the benchmark cost and weight caps derived from the
                      planner estimates.

                    ## 9. Part Metadata

                    - Preserve the labels and metadata for `open_corridor_frame`
                      and any other benchmark-owned parts exactly.
                    """
                ).strip()
                + "\n",
                "todo.md": _fixture_entry_file_content(
                    "INT-204",
                    filename_suffix="todo.md",
                    node="benchmark_planner",
                ),
                "benchmark_assembly_definition.yaml": _minimal_benchmark_assembly_definition_content(
                    benchmark_definition_content
                ),
                "benchmark_definition.yaml": benchmark_definition_content,
                "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
            },
        )
    if agent_name == AgentName.ENGINEER_PLANNER:
        benchmark_definition_content = _normalize_benchmark_definition_content(
            _fixture_entry_file_content(
                "INT-033",
                filename_suffix="benchmark_definition.yaml",
                node="engineer_planner",
            )
        )
        return EvalDatasetItem(
            id=item_id,
            task="engineer planner workspace contract smoke test",
            complexity_level=0,
            seed_dataset=None,
            seed_files={
                "engineering_plan.md": _fixture_entry_file_content(
                    "INT-033",
                    filename_suffix="plan.md",
                    node="engineer_planner",
                ),
                "todo.md": _fixture_entry_file_content(
                    "INT-033",
                    filename_suffix="todo.md",
                    node="engineer_planner",
                ),
                "assembly_definition.yaml": _fixture_entry_file_content(
                    "INT-033",
                    filename_suffix="assembly_definition.yaml",
                    node="engineer_planner",
                ),
                "benchmark_definition.yaml": benchmark_definition_content,
                "benchmark_assembly_definition.yaml": _minimal_benchmark_assembly_definition_content(
                    benchmark_definition_content
                ),
                "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
            },
        )
    raise ValueError(f"Unsupported planner agent for synthetic item: {agent_name}")


def _load_submission_result(stdout: str) -> PlannerSubmissionResult:
    lines = stdout.splitlines()
    start_index = next(
        index for index, line in enumerate(lines) if line.lstrip().startswith("{")
    )
    json_text = "\n".join(lines[start_index:])
    return PlannerSubmissionResult.model_validate_json(json_text)


def _workspace_snapshot(workspace_dir: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(p for p in workspace_dir.rglob("*") if p.is_file()):
        if any(part == ".git" for part in path.parts):
            continue
        rel_path = path.relative_to(workspace_dir).as_posix()
        snapshot[rel_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _assert_skills_tree_materialized(workspace_dir: Path) -> None:
    assert (workspace_dir / ".agents" / "skills").is_dir()


_ROLE_SCOPED_SKILLS: dict[AgentName, str] = {
    AgentName.BENCHMARK_PLANNER: "benchmark-planner",
    AgentName.BENCHMARK_PLAN_REVIEWER: "benchmark-plan-reviewer",
    AgentName.BENCHMARK_CODER: "benchmark-coder",
    AgentName.BENCHMARK_REVIEWER: "benchmark-reviewer",
    AgentName.ENGINEER_PLANNER: "engineer-planner",
    AgentName.ENGINEER_PLAN_REVIEWER: "engineer-plan-reviewer",
    AgentName.ENGINEER_CODER: "engineer-coder",
}


def _assert_skill_projection(workspace_dir: Path, agent_name: AgentName) -> None:
    skill_root = workspace_dir / ".agents" / "skills"
    assert (skill_root / "runtime-script-contract" / "SKILL.md").is_file()
    for owning_agent, skill_name in _ROLE_SCOPED_SKILLS.items():
        skill_path = skill_root / skill_name
        if owning_agent == agent_name:
            assert skill_path.is_dir()
            assert (skill_path / "SKILL.md").is_file()
        else:
            assert not skill_path.exists()


class RecordingCliProvider:
    provider_name = "codex"
    binary_name = sys.executable
    home_dir_name = ".codex"
    runtime_root_name = "codex-runtime"
    session_prefix = "local-codex"

    def __init__(self, args_log_path: Path):
        self._delegate = CodexCliProvider()
        self._args_log_path = args_log_path

    def prepare_home(self, **kwargs):
        return self._delegate.prepare_home(**kwargs)

    def translate_reasoning_effort(self, reasoning_effort):
        return self._delegate.translate_reasoning_effort(reasoning_effort)

    def build_env(self, **kwargs):
        env = self._delegate.build_env(**kwargs)
        env["CLI_PROVIDER_ARGS_LOG"] = str(self._args_log_path)
        return env

    def build_exec_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> CliInvocation:
        actual_invocation = self._delegate.build_exec_invocation(
            workspace_dir=workspace_dir,
            prompt_text=prompt_text,
            yolo=yolo,
            resume_session_id=resume_session_id,
            output_last_message_path=output_last_message_path,
        )
        code = textwrap.dedent(
            """\
            from __future__ import annotations

            import os
            import pathlib
            import sys

            log_path = pathlib.Path(os.environ["CLI_PROVIDER_ARGS_LOG"])
            log_path.write_text("\\n".join(sys.argv[2:]), encoding="utf-8")
            """
        )
        return CliInvocation(
            argv=[sys.executable, "-c", code, *actual_invocation.argv],
            prompt_text=actual_invocation.prompt_text,
            prompt_transport=actual_invocation.prompt_transport,
            cwd=actual_invocation.cwd,
            env_overrides=actual_invocation.env_overrides,
            resume_session_id=actual_invocation.resume_session_id,
            output_last_message_path=actual_invocation.output_last_message_path,
        )

    def build_exec_command(
        self,
        *,
        workspace_dir: Path,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> list[str]:
        return self.build_exec_invocation(
            workspace_dir=workspace_dir,
            prompt_text="",
            yolo=yolo,
            resume_session_id=resume_session_id,
            output_last_message_path=output_last_message_path,
        ).argv

    def build_ui_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> CliInvocation:
        actual_invocation = self._delegate.build_ui_invocation(
            workspace_dir=workspace_dir,
            prompt_text=prompt_text,
            yolo=yolo,
        )
        code = textwrap.dedent(
            """\
            from __future__ import annotations

            import os
            import pathlib
            import sys

            log_path = pathlib.Path(os.environ["CLI_PROVIDER_ARGS_LOG"])
            log_path.write_text("\\n".join(sys.argv[2:]), encoding="utf-8")
            """
        )
        return CliInvocation(
            argv=[sys.executable, "-c", code, *actual_invocation.argv],
            prompt_text=actual_invocation.prompt_text,
            prompt_transport=actual_invocation.prompt_transport,
            cwd=actual_invocation.cwd,
            env_overrides=actual_invocation.env_overrides,
            resume_session_id=actual_invocation.resume_session_id,
            output_last_message_path=actual_invocation.output_last_message_path,
        )

    def build_ui_command(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> list[str]:
        return self.build_ui_invocation(
            workspace_dir=workspace_dir,
            prompt_text=prompt_text,
            yolo=yolo,
        ).argv

    def build_help_command(self) -> list[str]:
        return [
            sys.executable,
            "-c",
            "print('workspace-write --sandbox')",
        ]

    def build_help_invocation(self) -> CliInvocation:
        return CliInvocation(
            argv=self.build_help_command(),
            prompt_transport="none",
        )


def _load_agents_config_with_reasoning_effort_enabled(
    enabled: bool,
) -> AgentsConfig:
    data = yaml.safe_load(AGENTS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    llm = data.setdefault("llm", {})
    llm["reasoning_effort_enabled"] = enabled
    return AgentsConfig.model_validate(data)


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-220")
def test_run_evals_help_exposes_cli_backend():
    completed = subprocess.run(
        [sys.executable, "dataset/evals/run_evals.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    normalized_stdout = " ".join(completed.stdout.split())
    assert "--runner-backend" in normalized_stdout
    assert "--provider" in normalized_stdout
    assert "--call-paid-api" in normalized_stdout
    assert "--level" in normalized_stdout
    assert re.search(
        r"default:\s*benchmark_planner\s*smoke-\s*test\s*run", completed.stdout
    )
    assert re.search(r"default:\s*1\s*smoke-\s*test\s*item", completed.stdout)
    assert re.search(r"default:\s*1\s*for\s*smoke-\s*test\s*runs", completed.stdout)
    assert "explicit execution backend override" in normalized_stdout.lower()
    assert "'cli' for the local cli llm path" in normalized_stdout.lower()
    assert "qwen" in normalized_stdout
    assert "--codex-skill-loop" in normalized_stdout


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-221")
def test_train_skills_help_exposes_retained_bundle_cli():
    completed = subprocess.run(
        [sys.executable, "-m", "evals.logic.skill_training", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    normalized_stdout = " ".join(completed.stdout.split())
    assert "--session-metadata-path" in normalized_stdout
    assert "--session-log-root" in normalized_stdout
    assert "--eval-log-key" in normalized_stdout
    assert "--codex-runtime-root" in normalized_stdout


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-222")
def test_eval_entrypoints_ignore_outer_integration_env_under_eval_profile(
    tmp_path,
):
    run_evals = subprocess.run(
        [
            sys.executable,
            "dataset/evals/run_evals.py",
            "--skip-env-up",
            "--runner-backend",
            "cli",
            "--task-id",
            "missing-task-id",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "IS_INTEGRATION_TEST": "true",
            "CONTROLLER_URL": "http://127.0.0.1:9",
        },
        check=False,
    )
    run_evals_output = "\n".join(
        part for part in (run_evals.stdout, run_evals.stderr) if part
    )
    assert run_evals.returncode == 0, run_evals_output
    assert "Agent evals started" in run_evals_output, run_evals_output
    assert "Agent evals finished" in run_evals_output, run_evals_output
    assert "integration-test setup via controller" not in run_evals_output
    assert (ROOT / "logs" / "evals" / "current" / "run_evals.log").exists()


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-223")
def test_materialize_seed_workspace_overrides_integration_test_env(
    tmp_path: Path,
):
    workspace_dir = tmp_path / "workspace"
    completed = subprocess.run(
        [
            sys.executable,
            "dataset/evals/materialize_seed_workspace.py",
            "--agent",
            "engineer_coder",
            "--task-id",
            "ec-001",
            "--output-dir",
            str(workspace_dir),
            "--no-yolo",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CONTROLLER_URL": "http://127.0.0.1:9",
            "IS_INTEGRATION_TEST": "true",
        },
        check=False,
    )
    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 1, combined_output
    assert workspace_dir.exists(), combined_output
    assert "workspace:" in combined_output
    assert "integration-test setup via IS_INTEGRATION_TEST=true" not in combined_output


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-224")
def test_materialize_seed_workspace_requires_explicit_yolo_choice(
    tmp_path: Path,
):
    workspace_dir = tmp_path / "workspace"
    completed = subprocess.run(
        [
            sys.executable,
            "dataset/evals/materialize_seed_workspace.py",
            "--agent",
            "engineer_coder",
            "--task-id",
            "ec-001",
            "--output-dir",
            str(workspace_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 2, combined_output
    assert "one of the arguments --yolo --no-yolo is required" in combined_output
    assert not workspace_dir.exists(), combined_output


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-225")
@pytest.mark.parametrize(
    ("flag_name", "attr_name"),
    [
        pytest.param("--launch-cli-exec", "launch_cli_exec", id="launch"),
        pytest.param("--open-cli-ui", "open_cli_ui", id="open"),
    ],
)
def test_materialize_seed_workspace_uses_generic_cli_flag_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag_name: str,
    attr_name: str,
):
    from dataset.evals.materialize_seed_workspace import _parse_args

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "materialize_seed_workspace.py",
            "--agent",
            "engineer_coder",
            "--task-id",
            "ec-001",
            "--output-dir",
            str(tmp_path / "workspace"),
            "--provider",
            "qwen",
            "--no-yolo",
            flag_name,
        ],
    )
    args = _parse_args()

    assert args.provider == "qwen"
    assert getattr(args, attr_name) is True


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-226")
def test_materialize_seed_workspace_defaults_provider_to_qwen(
    monkeypatch: pytest.MonkeyPatch,
):
    from dataset.evals.materialize_seed_workspace import _parse_args

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "materialize_seed_workspace.py",
            "--agent",
            "engineer_coder",
            "--task-id",
            "ec-001",
            "--no-yolo",
        ],
    )
    args = _parse_args()

    assert args.provider == "qwen"


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-227")
def test_materialize_seed_workspace_forwards_new_terminal_flag_to_open_cli_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import dataset.evals.materialize_seed_workspace as materialize_seed_workspace_module

    workspace_dir = tmp_path / "workspace"
    prompt_path = workspace_dir / "prompt.md"
    captured: dict[str, object] = {}
    materialize_kwargs: dict[str, object] = {}

    monkeypatch.setattr(
        materialize_seed_workspace_module,
        "materialize_workspace",
        lambda **kwargs: (
            materialize_kwargs.update(kwargs)
            or SimpleNamespace(
                workspace_dir=workspace_dir,
                prompt_path=prompt_path,
                prompt_text="prompt text",
                copied_paths=["foo.txt"],
            )
        ),
    )
    monkeypatch.setattr(
        materialize_seed_workspace_module,
        "open_cli_ui",
        lambda *args, **kwargs: captured.update(kwargs) or 0,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "materialize_seed_workspace.py",
            "--agent",
            "engineer_coder",
            "--task-id",
            "ec-001",
            "--output-dir",
            str(workspace_dir),
            "--provider",
            "qwen",
            "--no-yolo",
            "--open-cli-ui",
            "--new-terminal",
            "--force-no-validate-seed",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        materialize_seed_workspace_module.main()

    assert exc_info.value.code == 0
    assert materialize_kwargs["provider_name"] == "qwen"
    assert captured["new_terminal"] is True
    assert captured["provider_name"] == "qwen"
    assert captured["task_id"] == "ec-001"


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-228")
def test_run_e2e_seed_stage_continues_after_closing_open_cli_ui_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import dataset.evals.run_e2e_seed as run_e2e_seed_module

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    stage_calls: list[str] = []

    class FakeLocalWorkspaceClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def fake_preflight_seeded_entry_contract(**kwargs):
        return None

    async def fake_verify_workspace_for_agent(**kwargs):
        return SimpleNamespace(
            success=True,
            verification_name="local-verification",
            errors=[],
            details={},
        )

    def fake_materialize_seed_workspace(**kwargs):
        stage_calls.append("materialize_seed_workspace")
        return SimpleNamespace(
            workspace_dir=workspace_dir,
            prompt_text="prompt text",
        )

    def fake_open_cli_ui(*args, **kwargs):
        stage_calls.append("open_cli_ui")
        return 0

    monkeypatch.setattr(
        "evals.logic.codex_workspace.LocalWorkspaceClient",
        FakeLocalWorkspaceClient,
    )
    monkeypatch.setattr(
        "evals.logic.codex_workspace.materialize_seed_workspace",
        fake_materialize_seed_workspace,
    )
    monkeypatch.setattr(
        "evals.logic.codex_workspace.open_cli_ui",
        fake_open_cli_ui,
    )
    monkeypatch.setattr(
        "evals.logic.codex_workspace.verify_workspace_for_agent",
        fake_verify_workspace_for_agent,
    )
    monkeypatch.setattr(
        "evals.logic.workspace.preflight_seeded_entry_contract",
        fake_preflight_seeded_entry_contract,
    )
    monkeypatch.setattr(run_e2e_seed_module, "_simulation_success", lambda _: True)

    stage = run_e2e_seed_module.StageSpec(AgentName.BENCHMARK_PLANNER)
    item = EvalDatasetItem.model_validate(
        {
            "id": run_e2e_seed_module.DEFAULT_TASK_ID,
            "task": "benchmark planner seed",
            "complexity_level": 0,
        }
    )

    result = asyncio.run(
        run_e2e_seed_module._run_stage(
            stage=stage,
            item=item,
            workspace_root=tmp_path,
            provider_name="qwen",
            yolo=True,
            source_seed_dir=tmp_path / "seed",
            open_cli_ui_requested=True,
            open_cli_ui_new_terminal=True,
        )
    )

    assert result.launch_return_code == 0
    assert result.verification_success is True
    assert stage_calls == [
        "materialize_seed_workspace",
        "open_cli_ui",
    ]


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-229")
def test_run_e2e_seed_resume_from_dir_uses_checkpoint(tmp_path: Path):
    import dataset.evals.run_e2e_seed as run_e2e_seed_module
    from evals.logic.models import E2EResumeStageRecord

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    workspace_root = tmp_path / "resume-root"
    stage_dir = workspace_root / "workspaces" / "benchmark_planner-1111aaaa"
    stage_dir.mkdir(parents=True)

    stage_record = E2EResumeStageRecord(
        stage_index=0,
        agent_name=AgentName.BENCHMARK_PLANNER,
        workspace_dir=stage_dir,
        session_id="session-1",
        launch_return_code=0,
        verification_name="local-verification",
        verification_success=True,
        simulation_success=None,
        review_decision=None,
    )
    run_e2e_seed_module._save_resume_state(
        workspace_root=workspace_root,
        seed_dir=seed_dir,
        completed_stages=[stage_record],
    )

    plan = run_e2e_seed_module._build_resume_plan(
        seed_dir=seed_dir,
        workspace_root=workspace_root,
        resume_from_dir=workspace_root,
        resume_from_agent=None,
    )

    assert plan.start_stage_index == 1
    assert plan.source_seed_dir == stage_dir
    assert plan.resume_label == f"{stage_record.agent_name.value}@{stage_dir}"
    assert len(plan.completed_stages) == 1


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-230")
def test_run_e2e_seed_resume_from_dir_requires_checkpoint(tmp_path: Path):
    import dataset.evals.run_e2e_seed as run_e2e_seed_module

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    workspace_root = tmp_path / "resume-root"
    stage_dir = workspace_root / "some" / "nested" / "benchmark_planner-1111aaaa"
    stage_dir.mkdir(parents=True)
    (stage_dir / "prompt.md").write_text("prompt\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Resume state missing"):
        run_e2e_seed_module._build_resume_plan(
            seed_dir=seed_dir,
            workspace_root=workspace_root,
            resume_from_dir=workspace_root,
            resume_from_agent=None,
        )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-231")
def test_run_e2e_seed_resume_from_agent_handle_uses_stage_dir(tmp_path: Path):
    import dataset.evals.run_e2e_seed as run_e2e_seed_module

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    workspace_root = tmp_path / "resume-root"
    stage_dir = workspace_root / "workspaces" / "benchmark_planner-1111aaaa"
    stage_dir.mkdir(parents=True)
    (stage_dir / "prompt.md").write_text("prompt\n", encoding="utf-8")

    plan = run_e2e_seed_module._build_resume_plan(
        seed_dir=seed_dir,
        workspace_root=workspace_root,
        resume_from_dir=None,
        resume_from_agent=f"benchmark_planner@{stage_dir}",
    )

    assert plan.workspace_root == workspace_root
    assert plan.start_stage_index == 1
    assert plan.source_seed_dir == stage_dir
    assert plan.resume_label == f"benchmark_planner@{stage_dir}"


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-232")
def test_run_e2e_seed_resume_from_agent_handle_uses_checkpoint_chain(
    tmp_path: Path,
):
    import dataset.evals.run_e2e_seed as run_e2e_seed_module
    from evals.logic.models import E2EResumeStageRecord

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    workspace_root = tmp_path / "resume-root"
    planner_dir = workspace_root / "workspaces" / "benchmark_planner-1111aaaa"
    planner_dir.mkdir(parents=True)

    planner_stage = E2EResumeStageRecord(
        stage_index=0,
        agent_name=AgentName.BENCHMARK_PLANNER,
        workspace_dir=planner_dir,
        session_id="session-1",
        launch_return_code=0,
        verification_name="local-verification",
        verification_success=True,
        simulation_success=None,
        review_decision=None,
    )

    run_e2e_seed_module._save_resume_state(
        workspace_root=workspace_root,
        seed_dir=seed_dir,
        completed_stages=[planner_stage],
    )

    plan = run_e2e_seed_module._build_resume_plan(
        seed_dir=seed_dir,
        workspace_root=workspace_root,
        resume_from_dir=workspace_root,
        resume_from_agent="benchmark_plan_reviewer",
    )

    assert plan.workspace_root == workspace_root
    assert plan.start_stage_index == 1
    assert plan.source_seed_dir == planner_dir
    assert plan.resume_label == f"benchmark_plan_reviewer@{planner_dir}"
    assert [stage.agent_name for stage in plan.completed_stages] == [
        AgentName.BENCHMARK_PLANNER
    ]


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-233")
def test_run_e2e_seed_resume_from_agent_handle_requires_completed_predecessor(
    tmp_path: Path,
):
    import dataset.evals.run_e2e_seed as run_e2e_seed_module

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    workspace_root = tmp_path / "resume-root"
    workspace_root.mkdir()

    with pytest.raises(SystemExit, match="Resume state missing"):
        run_e2e_seed_module._build_resume_plan(
            seed_dir=seed_dir,
            workspace_root=workspace_root,
            resume_from_dir=workspace_root,
            resume_from_agent="benchmark_plan_reviewer",
        )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-234")
@pytest.mark.asyncio
async def test_seed_workspace_artifacts_skip_git_metadata(
    tmp_path: Path,
):
    from evals.logic.models import EvalDatasetItem
    from evals.logic.workspace import (
        InMemorySeedWorkspaceClient,
        collect_seed_workspace_artifact_paths,
        materialize_seed_workspace_snapshot,
    )

    seed_dir = tmp_path / "seed"
    git_objects_dir = seed_dir / ".git" / "objects" / "05"
    git_objects_dir.mkdir(parents=True)
    (git_objects_dir / "deadbeef").write_text("git object\n", encoding="utf-8")
    (seed_dir / "benchmark_plan.md").write_text("plan\n", encoding="utf-8")

    item = EvalDatasetItem.model_validate(
        {
            "id": "e2e-001",
            "task": "seed artifact filtering",
            "complexity_level": 0,
            "seed_artifact_dir": seed_dir,
        }
    )

    expected_paths = collect_seed_workspace_artifact_paths(item, root=tmp_path)
    assert "benchmark_plan.md" in expected_paths
    assert ".manifests/current_role.json" in expected_paths
    assert not any(path.startswith(".git/") for path in expected_paths)

    workspace_client = InMemorySeedWorkspaceClient(session_id="session-1")
    seeded_paths = await materialize_seed_workspace_snapshot(
        item=item,
        session_id="session-1",
        agent_name=AgentName.BENCHMARK_PLANNER,
        root=tmp_path,
        workspace_client=workspace_client,
    )

    assert "benchmark_plan.md" in seeded_paths
    assert ".manifests/current_role.json" in seeded_paths
    assert not any(path.startswith(".git/") for path in seeded_paths)
    assert all(
        not path.startswith(".git/") for path, _ in workspace_client.snapshot_files()
    )
    current_role = await workspace_client.read_file_optional(
        ".manifests/current_role.json",
        bypass_agent_permissions=True,
    )
    assert current_role is not None
    assert (
        parse_current_role_manifest(current_role).agent_name
        == AgentName.BENCHMARK_PLANNER
    )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-235")
def test_cli_provider_registry_supports_qwen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from evals.logic.cli_provider import available_cli_providers, get_cli_provider

    fake_home = tmp_path / "source-home"
    qwen_home = fake_home / ".qwen"
    qwen_home.mkdir(parents=True, exist_ok=True)
    (qwen_home / "settings.json").write_text(
        json.dumps(
            {
                "security": {"auth": {"selectedType": "qwen-oauth"}},
                "model": {"name": "coder-model"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (qwen_home / "oauth_creds.json").write_text(
        json.dumps(
            {
                "access_token": "token-1",
                "token_type": "Bearer",
                "refresh_token": "refresh-1",
                "resource_url": "portal.qwen.ai",
                "expiry_date": 1775310754389,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (qwen_home / "installation_id").write_text(
        "d803ea40-01b8-46bf-8863-89d16777dfb1\n", encoding="utf-8"
    )
    (qwen_home / "source.json").write_text(
        json.dumps({"source": "qwenchat"}, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))

    provider = get_cli_provider("qwen")
    qwen_home_root = resolve_cli_home_root(
        task_id="task-1",
        runtime_root=tmp_path,
        provider_name="qwen",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    codex_home_dir = provider.prepare_home(
        codex_home_root=qwen_home_root,
        workspace_dir=workspace_dir,
    )
    env = provider.build_env(
        task_id="task-1",
        workspace_dir=workspace_dir,
        codex_home_root=qwen_home_root,
        session_id="session-1",
    )
    exec_invocation = provider.build_exec_invocation(
        workspace_dir=workspace_dir,
        prompt_text="inspect this workspace",
        yolo=False,
        resume_session_id="resume-1",
    )
    ui_invocation = provider.build_ui_invocation(
        workspace_dir=workspace_dir,
        prompt_text="open ui prompt",
        yolo=True,
    )

    assert available_cli_providers() == ["codex", "pi", "qwen"]
    assert isinstance(provider, QwenCliProvider)
    assert provider.provider_name == "qwen"
    assert provider.binary_name == "qwen"
    assert provider.home_dir_name == ".qwen"
    assert provider.runtime_root_name == "qwen-runtime"
    assert provider.session_prefix == "local-qwen"
    assert env["CODEX_HOME"].endswith("/.qwen")
    assert env["QWEN_HOME"] == env["CODEX_HOME"]
    assert (
        json.loads((codex_home_dir / "settings.json").read_text(encoding="utf-8"))[
            "security"
        ]["auth"]["selectedType"]
        == "qwen-oauth"
    )
    assert (
        json.loads((codex_home_dir / "oauth_creds.json").read_text(encoding="utf-8"))[
            "refresh_token"
        ]
        == "refresh-1"
    )
    assert qwen_home_root.parent.parent.name == "qwen-runtime"
    assert qwen_home_root.parent.name == "homes"
    assert qwen_home_root.name.startswith("local-qwen-task-1-")
    assert provider.build_help_command() == ["qwen", "--help"]
    assert provider.build_exec_command(
        workspace_dir=workspace_dir,
        yolo=False,
        resume_session_id="resume-1",
    ) == ["qwen", "--chat-recording", "--sandbox", "--resume", "resume-1"]
    assert exec_invocation.prompt_transport == "positional"
    assert exec_invocation.argv[-1] == "inspect this workspace"
    assert "--resume" in exec_invocation.argv
    assert "--chat-recording" in exec_invocation.argv
    assert "--sandbox" in exec_invocation.argv
    assert ui_invocation.prompt_transport == "prompt_flag"
    assert ui_invocation.argv[1:3] == ["--chat-recording", "--yolo"]
    assert "--prompt-interactive" in ui_invocation.argv


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-238")
def test_pi_cli_provider_selection_and_invocation_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))

    provider = get_cli_provider("pi")
    pi_home_root = resolve_cli_home_root(
        task_id="task-1",
        runtime_root=tmp_path,
        provider_name="pi",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    pi_home_dir = provider.prepare_home(
        codex_home_root=pi_home_root,
        workspace_dir=workspace_dir,
    )
    env = provider.build_env(
        task_id="task-1",
        workspace_dir=workspace_dir,
        codex_home_root=pi_home_root,
        session_id="session-1",
    )
    exec_invocation = provider.build_exec_invocation(
        workspace_dir=workspace_dir,
        prompt_text="inspect this workspace",
        yolo=False,
        resume_session_id="resume-1",
    )
    ui_invocation = provider.build_ui_invocation(
        workspace_dir=workspace_dir,
        prompt_text="open ui prompt",
        yolo=True,
    )

    assert isinstance(provider, PiCliProvider)
    assert provider.provider_name == "pi"
    assert provider.binary_name == "pi"
    assert provider.home_dir_name == ".pi/agent"
    assert provider.runtime_root_name == "pi-runtime"
    assert provider.session_prefix == "local-pi"
    assert env["PI_CODING_AGENT_DIR"].endswith("/.pi/agent")
    assert env["CODEX_HOME"] == env["PI_CODING_AGENT_DIR"]
    assert pi_home_dir.parent.name == ".pi"
    assert pi_home_dir.name == "agent"
    assert pi_home_root.parent.parent.name == "pi-runtime"
    assert pi_home_root.parent.name == "homes"
    assert pi_home_root.name.startswith("local-pi-task-1-")
    assert provider.build_help_command() == ["pi", "--help"]
    assert provider.build_exec_command(
        workspace_dir=workspace_dir,
        yolo=False,
        resume_session_id="resume-1",
    ) == ["pi", "--print", "--resume", "resume-1"]
    assert exec_invocation.prompt_transport == "positional"
    assert exec_invocation.argv[-1] == "inspect this workspace"
    assert "--resume" in exec_invocation.argv
    assert "--print" in exec_invocation.argv
    assert ui_invocation.prompt_transport == "positional"
    assert ui_invocation.argv == ["pi", "open ui prompt"]


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-236")
def test_cli_provider_invocation_supports_prompt_flag_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class PromptFlagProvider:
        provider_name = "qwen"
        binary_name = "qwen"
        home_dir_name = ".qwen"
        runtime_root_name = "qwen-runtime"
        session_prefix = "local-qwen"

        def prepare_home(self, **kwargs):
            codex_home_root = kwargs["codex_home_root"]
            codex_home_root.mkdir(parents=True, exist_ok=True)
            (codex_home_root / self.home_dir_name).mkdir(parents=True, exist_ok=True)
            return codex_home_root / self.home_dir_name

        def translate_reasoning_effort(self, reasoning_effort):
            return reasoning_effort

        def build_env(self, **kwargs):
            env = dict(os.environ)
            env["CODEX_HOME"] = str(kwargs["codex_home_root"] / self.home_dir_name)
            env["QWEN_HOME"] = env["CODEX_HOME"]
            env["SESSION_ID"] = kwargs.get("session_id") or "session-1"
            return env

        def build_exec_invocation(
            self,
            *,
            workspace_dir: Path,
            prompt_text: str,
            yolo: bool,
            resume_session_id: str | None = None,
            output_last_message_path: Path | None = None,
        ) -> CliInvocation:
            return CliInvocation(
                argv=[
                    "qwen",
                    "--prompt",
                    prompt_text,
                    "--workspace",
                    str(workspace_dir),
                ],
                prompt_text=prompt_text,
                prompt_transport="prompt_flag",
                cwd=workspace_dir,
                resume_session_id=resume_session_id,
                output_last_message_path=output_last_message_path,
            )

        def build_ui_invocation(
            self,
            *,
            workspace_dir: Path,
            prompt_text: str,
            yolo: bool,
        ) -> CliInvocation:
            return CliInvocation(
                argv=[
                    "qwen",
                    "--prompt",
                    prompt_text,
                    "--workspace",
                    str(workspace_dir),
                ],
                prompt_text=prompt_text,
                prompt_transport="prompt_flag",
                cwd=workspace_dir,
            )

        def build_help_command(self) -> list[str]:
            return ["qwen", "--help"]

        def build_help_invocation(self) -> CliInvocation:
            return CliInvocation(
                argv=self.build_help_command(),
                prompt_transport="none",
            )

    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("evals.logic.codex_workspace.subprocess.run", fake_run)
    monkeypatch.setattr(
        "evals.logic.codex_workspace.get_cli_provider",
        lambda provider_name=None: PromptFlagProvider(),
    )

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    result = launch_cli_exec(
        workspace_dir,
        "prompt transport smoke",
        task_id="task-1",
        agent_name=AgentName.ENGINEER_CODER,
        session_id="session-1",
        runtime_root=tmp_path / "qwen-runtime",
        yolo=False,
    )

    assert result == 0
    assert captured["kwargs"]["input"] is None
    assert captured["kwargs"]["cwd"] == str(workspace_dir)
    argv = captured["args"][0]
    assert argv[0] == "qwen"
    assert "--prompt" in argv
    assert "prompt transport smoke" in argv
    assert captured["kwargs"]["env"]["QWEN_HOME"].endswith("/.qwen")


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-237")
def test_open_cli_ui_uses_new_terminal_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class PromptFlagProvider:
        provider_name = "qwen"
        binary_name = "qwen"
        home_dir_name = ".qwen"
        runtime_root_name = "qwen-runtime"
        session_prefix = "local-qwen"

        def prepare_home(self, **kwargs):
            codex_home_root = kwargs["codex_home_root"]
            codex_home_root.mkdir(parents=True, exist_ok=True)
            (codex_home_root / self.home_dir_name).mkdir(parents=True, exist_ok=True)
            return codex_home_root / self.home_dir_name

        def build_env(self, **kwargs):
            env = dict(os.environ)
            env["CODEX_HOME"] = str(kwargs["codex_home_root"] / self.home_dir_name)
            env["QWEN_HOME"] = env["CODEX_HOME"]
            env["SESSION_ID"] = kwargs.get("session_id") or "session-1"
            return env

        def build_ui_invocation(
            self,
            *,
            workspace_dir: Path,
            prompt_text: str,
            yolo: bool,
        ) -> CliInvocation:
            return CliInvocation(
                argv=[
                    "qwen",
                    "--prompt",
                    prompt_text,
                    "--workspace",
                    str(workspace_dir),
                ],
                prompt_text=prompt_text,
                prompt_transport="prompt_flag",
                cwd=workspace_dir,
            )

    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("evals.logic.codex_workspace.subprocess.run", fake_run)
    monkeypatch.setattr(
        "evals.logic.codex_workspace.shutil.which",
        lambda name: "/usr/bin/gnome-terminal" if name == "gnome-terminal" else None,
    )
    monkeypatch.setattr(
        "evals.logic.codex_workspace.get_cli_provider",
        lambda provider_name=None: PromptFlagProvider(),
    )
    monkeypatch.setenv("DISPLAY", ":99")

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / ".git").mkdir()
    result = open_cli_ui(
        workspace_dir,
        "open ui prompt",
        task_id="task-1",
        agent_name=AgentName.ENGINEER_CODER,
        session_id="session-1",
        runtime_root=tmp_path / "qwen-runtime",
        yolo=True,
        provider_name="qwen",
        timeout_seconds=123,
        new_terminal=True,
    )

    assert result == 0
    argv = captured["args"][0]
    assert Path(argv[0]).name == "gnome-terminal"
    assert "--wait" in argv
    assert any(arg.startswith("--title=") for arg in argv)
    assert any(arg.startswith("--working-directory=") for arg in argv)
    assert "--" in argv
    assert "qwen" in argv
    assert "open ui prompt" in argv
    assert captured["kwargs"]["cwd"] == str(workspace_dir)
    assert captured["kwargs"]["timeout"] == 123
    assert captured["kwargs"]["env"]["DISPLAY"] == ":99"
    assert captured["kwargs"]["env"]["QWEN_HOME"].endswith("/.qwen")


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-238")
def test_skill_training_preserves_legacy_provider_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import asyncio

    from evals.logic import skill_training
    from shared.models.simulation import SimulationResult

    session_log_root = tmp_path / "sessions"
    eval_log_key = "ec-legacy"
    session_dir = session_log_root / eval_log_key
    session_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    metadata_path = session_dir / "session_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "agent_name": "engineer_coder",
                "task_id": "ec-legacy",
                "task": "legacy retained bundle",
                "session_id": "session-legacy",
                "workspace_dir": str(workspace_dir),
                "launch_return_code": 0,
                "success": True,
                "verification_name": "local-verification",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    provider_calls: list[str | None] = []

    def fake_get_cli_provider(provider_name=None):
        provider_calls.append(provider_name)
        return SimpleNamespace(
            provider_name=provider_name,
            home_dir_name=".codex",
        )

    from evals.logic.codex_workspace import WorkspaceVerificationResult

    async def fake_verify_workspace_for_agent(**kwargs):
        return WorkspaceVerificationResult(
            success=True,
            verification_name="local-verification",
        )

    def fake_seed_skill_overlay_state(workspace_dir: Path):
        overlay_dir = workspace_dir / "suggested_skills"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        return overlay_dir, None, None, None

    monkeypatch.setattr(skill_training, "get_cli_provider", fake_get_cli_provider)
    monkeypatch.setattr(
        skill_training,
        "verify_workspace_for_agent",
        fake_verify_workspace_for_agent,
    )
    monkeypatch.setattr(
        skill_training,
        "_load_workspace_simulation_result",
        lambda workspace_dir: SimulationResult(success=True, summary="ok"),
    )
    monkeypatch.setattr(
        skill_training,
        "_seed_skill_overlay_state",
        fake_seed_skill_overlay_state,
    )

    args = SimpleNamespace(
        session_metadata_path=metadata_path,
        session_log_root=None,
        eval_log_key=None,
        workspace_dir=None,
        session_id=None,
        task_id=None,
        agent=None,
        codex_runtime_root=None,
    )
    session = asyncio.run(skill_training.load_skill_training_session(args=args))

    assert session.provider_name == "codex"
    assert session.item.complexity_level == 0
    assert provider_calls == ["codex"]

    reloaded_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "provider_name" not in reloaded_metadata
    assert reloaded_metadata["suggested_skills_dir"].endswith("suggested_skills")

    dummy_log = SimpleNamespace(
        info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None
    )
    summary, trace = asyncio.run(
        skill_training.run_skill_training_session(session=session, log=dummy_log)
    )

    assert provider_calls == ["codex", "codex"]
    assert summary.enabled is True
    assert trace is None


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-239")
def test_run_evals_codex_exec_help_exposes_workspace_write_sandbox(
    tmp_path: Path,
):
    provider = RecordingCliProvider(tmp_path / "provider-args.log")
    completed = subprocess.run(
        provider.build_help_command(),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "workspace-write" in completed.stdout
    assert "--sandbox" in completed.stdout


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-240")
def test_resume_codex_exec_uses_cli_provider_resume_command(
    tmp_path: Path, monkeypatch
):
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    fake_home = tmp_path / "home"
    auth_path = fake_home / ".codex" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    provider = RecordingCliProvider(tmp_path / "codex-resume-args.log")
    monkeypatch.setattr(
        "evals.logic.codex_workspace.get_cli_provider",
        lambda: provider,
    )

    monkeypatch.setenv("HOME", str(fake_home))

    result = resume_cli_exec(
        workspace_dir=workspace_dir,
        prompt_text="self-analyze the failed run",
        task_id="task-1",
        codex_session_id="019d0000-0000-7000-9000-000000000099",
        session_id="home-session-1",
        runtime_root=tmp_path / "codex-runtime",
        yolo=False,
    )

    assert result.return_code == 0
    logged_args = (
        (tmp_path / "codex-resume-args.log").read_text(encoding="utf-8").splitlines()
    )
    assert logged_args[0] == "exec"
    assert logged_args[1] == "-C"
    assert logged_args[2] == str(workspace_dir)
    assert logged_args[3] == "resume"
    assert logged_args[4] == "019d0000-0000-7000-9000-000000000099"
    assert "--full-auto" in logged_args
    assert "--cd" not in logged_args


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-241")
def test_run_evals_defaults_are_smoke_test_contract():
    from evals.logic.runner import _build_parser

    args = _build_parser().parse_args([])

    assert args.agent == "benchmark_planner"
    assert args.limit == 1
    assert args.concurrency == 1
    assert args.level is None
    assert args.open_cli_ui is False


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-242")
@pytest.mark.asyncio
async def test_run_evals_codex_judge_does_not_launch_reviewers_without_flag(
    tmp_path, monkeypatch
):
    item = EvalDatasetItem(
        id="codex-judge-001",
        task="codex judge reviewer gate regression",
        complexity_level=0,
        expected_decision=ReviewDecision.APPROVED,
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "simulation_result.json").write_text(
        json.dumps({"success": True, "summary": "simulation completed"}),
        encoding="utf-8",
    )
    materialized = SimpleNamespace(
        workspace_dir=workspace_dir,
        prompt_path=workspace_dir / "prompt.md",
        prompt_text="prompt",
        copied_paths=(),
    )

    monkeypatch.setattr(runner, "SESSION_LOG_ROOT", tmp_path / "session-root")
    monkeypatch.setattr(runner, "_materialize_workspace", lambda **_: materialized)
    monkeypatch.setattr(runner, "_launch_cli_exec", lambda *_, **__: 0)

    async def fake_verify_workspace_for_agent(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            success=True,
            errors=[],
            details={},
            verification_name="codex-verify",
        )

    async def fake_record_hard_check_outcomes(**_: object) -> bool:
        return True

    async def fake_record_judge_outcomes(**_: object) -> None:
        return None

    monkeypatch.setattr(
        runner,
        "_verify_workspace_for_agent",
        fake_verify_workspace_for_agent,
    )
    monkeypatch.setattr(
        runner, "_record_hard_check_outcomes", fake_record_hard_check_outcomes
    )
    monkeypatch.setattr(runner, "_record_judge_outcomes", fake_record_judge_outcomes)
    monkeypatch.setattr(runner, "_write_eval_session_metadata", lambda **_: None)
    monkeypatch.setattr(
        runner,
        "_resolve_cli_home_root",
        lambda **_: tmp_path / "codex-home",
    )
    monkeypatch.setattr(
        runner,
        "_capture_latest_codex_session_artifacts",
        lambda **_: None,
    )

    async def fail_codex_skill_loop(**_: object) -> tuple[object, object]:
        raise AssertionError("codex skill loop should stay disabled by default")

    monkeypatch.setattr(runner, "_run_skill_loop", fail_codex_skill_loop)

    reviewer_called = False

    async def fail_reviewer_chain_for_judge(**_: object) -> list[dict[str, object]]:
        nonlocal reviewer_called
        reviewer_called = True
        raise AssertionError(
            "reviewer chain should not run without run_reviewers_with_judge"
        )

    monkeypatch.setattr(
        runner,
        "_run_reviewer_chain_for_judge",
        fail_reviewer_chain_for_judge,
    )

    stats = {AgentName.BENCHMARK_CODER: {"total": 0, "success": 0}}
    success = await runner._run_cli_eval(
        item=item,
        stats=stats,
        agent_name=AgentName.BENCHMARK_CODER,
        reward_agent_configs={},
        case_label="judge-gate",
        run_judge=True,
        run_reviewers_with_judge=False,
    )

    assert success is True
    assert reviewer_called is False
    assert stats[AgentName.BENCHMARK_CODER]["total"] == 1
    assert stats[AgentName.BENCHMARK_CODER]["success"] == 1


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-243")
@pytest.mark.asyncio
async def test_run_evals_codex_skill_loop_flag_enables_loop_backend(
    tmp_path, monkeypatch
):
    item = EvalDatasetItem(
        id="codex-skill-loop-enabled-001",
        task="codex skill loop flag regression",
        complexity_level=0,
        expected_decision=ReviewDecision.APPROVED,
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "simulation_result.json").write_text(
        json.dumps({"success": True, "summary": "simulation completed"}),
        encoding="utf-8",
    )
    materialized = SimpleNamespace(
        workspace_dir=workspace_dir,
        prompt_path=workspace_dir / "prompt.md",
        prompt_text="prompt",
        copied_paths=(),
    )

    monkeypatch.setattr(runner, "SESSION_LOG_ROOT", tmp_path / "session-root")
    monkeypatch.setattr(runner, "_materialize_workspace", lambda **_: materialized)
    monkeypatch.setattr(runner, "_launch_cli_exec", lambda *_, **__: 0)

    async def fake_verify_workspace_for_agent(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            success=True,
            errors=[],
            details={},
            verification_name="codex-verify",
        )

    async def fake_run_skill_loop(**_: object):
        return runner.CodexSkillLoopSummary(enabled=True, triggered=True), None

    monkeypatch.setattr(
        runner,
        "_verify_workspace_for_agent",
        fake_verify_workspace_for_agent,
    )
    monkeypatch.setattr(runner, "_run_skill_loop", fake_run_skill_loop)
    monkeypatch.setattr(runner, "_write_eval_session_metadata", lambda **_: None)
    monkeypatch.setattr(
        runner,
        "_resolve_cli_home_root",
        lambda **_: tmp_path / "codex-home",
    )
    monkeypatch.setattr(
        runner,
        "_capture_latest_codex_session_artifacts",
        lambda **_: None,
    )

    stats = {AgentName.BENCHMARK_CODER: {"total": 0, "success": 0}}
    success = await runner._run_cli_eval(
        item=item,
        stats=stats,
        agent_name=AgentName.BENCHMARK_CODER,
        reward_agent_configs={},
        case_label="skill-loop-enabled",
        run_judge=True,
        run_reviewers_with_judge=False,
        enable_codex_skill_loop=True,
    )

    assert success is True
    assert stats[AgentName.BENCHMARK_CODER]["total"] == 1
    assert stats[AgentName.BENCHMARK_CODER]["success"] == 1


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-244")
@pytest.mark.parametrize(
    "launch_return_code,expected_timed_out",
    [
        pytest.param(1, False, id="early-exit"),
        pytest.param(124, True, id="timeout"),
    ],
)
@pytest.mark.asyncio
async def test_run_evals_codex_skill_loop_resumes_same_session_twice(
    tmp_path, monkeypatch, launch_return_code, expected_timed_out
):
    item = EvalDatasetItem(
        id="codex-skill-loop-001",
        task="codex skill loop regression",
        complexity_level=0,
        expected_decision=ReviewDecision.APPROVED,
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "prompt.md").write_text(
        "Workspace: current directory\n",
        encoding="utf-8",
    )
    (workspace_dir / "journal.md").write_text(
        "# Journal\n\n- Initial note before the skill loop.\n",
        encoding="utf-8",
    )
    (workspace_dir / "simulation_result.json").write_text(
        json.dumps({"success": False, "summary": "simulation did not report success"}),
        encoding="utf-8",
    )

    codex_trace_artifacts = CodexSessionTraceArtifact(
        session_id="019d0000-0000-7000-9000-000000000123"
    )
    verification_result = SimpleNamespace(
        success=False,
        verification_name="coder_workspace_contract",
        errors=["missing simulation_result.json"],
        details={},
    )
    baseline_snapshot = runner._snapshot_workspace_state(workspace_dir=workspace_dir)
    captured_prompts: list[tuple[str, str]] = []
    resume_calls: list[tuple[str, str, float | None, str]] = []
    resume_call_count = 0

    def fake_resume_cli_exec(
        workspace_dir: Path,
        prompt_text: str,
        *,
        task_id: str,
        codex_session_id: str,
        agent_name: AgentName | None = None,
        session_id: str | None = None,
        runtime_root: Path | None = None,
        yolo: bool = True,
        timeout_seconds: float | None = None,
        output_last_message_path: Path | None = None,
        reasoning_effort: str = "high",
    ) -> CodexExecRunResult:
        nonlocal resume_call_count
        resume_call_count += 1
        resume_calls.append(
            (codex_session_id, prompt_text, timeout_seconds, reasoning_effort)
        )
        if resume_call_count == 1:
            (workspace_dir / "journal.md").write_text(
                "# Journal\n\n- Self-analysis captured the failure mode.\n",
                encoding="utf-8",
            )
        if resume_call_count == 2:
            drafted_skill_path = (
                workspace_dir / "suggested_skills" / "generated-skill.md"
            )
            drafted_skill_path.parent.mkdir(parents=True, exist_ok=True)
            drafted_skill_path.write_text(
                "# Generated skill\n\n- drafted from retained bundle\n",
                encoding="utf-8",
            )
        if output_last_message_path is not None:
            output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
            output_last_message_path.write_text("last message", encoding="utf-8")
        return CodexExecRunResult(
            command=[
                "codex",
                "exec",
                "resume",
                codex_session_id,
                "-",
            ],
            return_code=0,
            timed_out=False,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            output_last_message_path=output_last_message_path,
        )

    def fake_capture_latest_codex_session_artifacts(**kwargs: object):
        captured_prompts.append(
            (
                str(kwargs.get("artifact_root")),
                str(kwargs.get("sessions_root")),
            )
        )
        after_snapshot = runner._snapshot_workspace_state(workspace_dir=workspace_dir)
        return CodexSessionTraceArtifact(
            session_id=codex_trace_artifacts.session_id,
            workspace_diff=diff_workspace_snapshots(
                before=baseline_snapshot,
                after=after_snapshot,
            ),
        )

    monkeypatch.setattr(runner, "_resume_cli_exec", fake_resume_cli_exec)
    monkeypatch.setattr(
        runner,
        "_capture_latest_codex_session_artifacts",
        fake_capture_latest_codex_session_artifacts,
    )
    monkeypatch.setattr(runner, "SESSION_LOG_ROOT", tmp_path / "session-root")

    summary, updated_trace = await runner._run_skill_loop(
        item=item,
        agent_name=AgentName.ENGINEER_CODER,
        workspace_dir=workspace_dir,
        cli_runtime_root=tmp_path / "codex-runtime",
        eval_log_key="ec-001",
        baseline_snapshot=baseline_snapshot,
        codex_trace_artifacts=codex_trace_artifacts,
        launch_return_code=launch_return_code,
        verification_result=verification_result,
        log=runner.logger,
    )

    assert summary.triggered is True
    assert summary.primary_turn is not None
    assert summary.primary_turn.session_id == codex_trace_artifacts.session_id
    assert summary.primary_turn.timed_out is expected_timed_out
    assert summary.primary_turn.simulation_success is False
    assert summary.self_analysis_turn is not None
    assert summary.skill_update_turn is not None
    assert summary.event_count == 2
    assert summary.events_path is not None
    assert len(resume_calls) == 2
    assert resume_calls[0][0] == codex_trace_artifacts.session_id
    assert resume_calls[1][0] == codex_trace_artifacts.session_id
    assert resume_calls[0][3] == "xhigh"
    assert resume_calls[1][3] == "xhigh"
    assert "journal.md" in resume_calls[0][1]
    assert "suggested_skills/" in resume_calls[1][1]
    assert (workspace_dir / "suggested_skills" / "generated-skill.md").exists()
    assert (workspace_dir / "logs" / "skill_loop" / "self_analysis.md").exists()
    assert (workspace_dir / "logs" / "skill_loop" / "skill_update.md").exists()
    assert (workspace_dir / "logs" / "skill_loop" / "journal.md").exists()
    assert (workspace_dir / "logs" / "skill_loop" / "context_snapshot.md").exists()
    events_path = workspace_dir / "logs" / "skill_loop" / "events.jsonl"
    assert events_path.exists()
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_type"] for event in events] == [
        "skill_self_reflection",
        "skill_update",
    ]
    assert events[0]["reflection_text"] == "last message"
    assert events[1]["skill_update_text"] == "last message"
    assert "suggested_skills/generated-skill.md" in events[1]["updated_skill_paths"]
    assert events[0]["codex_session_id"] == codex_trace_artifacts.session_id
    assert events[1]["codex_session_id"] == codex_trace_artifacts.session_id
    assert events[0]["journal_path"].endswith("logs/skill_loop/journal.md")
    assert events[1]["context_snapshot_path"].endswith(
        "logs/skill_loop/context_snapshot.md"
    )
    assert updated_trace is not None
    assert updated_trace.session_id == codex_trace_artifacts.session_id
    assert "suggested_skills/generated-skill.md" in (
        updated_trace.workspace_diff.changed_paths
        if updated_trace.workspace_diff
        else []
    )
    assert "logs/skill_loop/journal.md" in (
        updated_trace.workspace_diff.changed_paths
        if updated_trace.workspace_diff
        else []
    )
    assert "logs/skill_loop/context_snapshot.md" in (
        updated_trace.workspace_diff.changed_paths
        if updated_trace.workspace_diff
        else []
    )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-245")
@pytest.mark.asyncio
async def test_run_evals_codex_skill_loop_falls_back_to_primary_session_when_trace_missing(
    tmp_path, monkeypatch
):
    item = EvalDatasetItem(
        id="codex-skill-loop-fallback-001",
        task="codex skill loop fallback regression",
        complexity_level=0,
        expected_decision=ReviewDecision.APPROVED,
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "prompt.md").write_text(
        "Workspace: current directory\n",
        encoding="utf-8",
    )
    (workspace_dir / "journal.md").write_text(
        "# Journal\n\n- Initial note before the skill loop.\n",
        encoding="utf-8",
    )
    (workspace_dir / "simulation_result.json").write_text(
        json.dumps({"success": False, "summary": "simulation did not report success"}),
        encoding="utf-8",
    )

    primary_session_id = "019d0000-0000-7000-9000-000000000456"
    baseline_snapshot = runner._snapshot_workspace_state(workspace_dir=workspace_dir)
    resume_calls: list[tuple[str, str, float | None, str]] = []

    def fake_resume_cli_exec(
        workspace_dir: Path,
        prompt_text: str,
        *,
        task_id: str,
        codex_session_id: str,
        agent_name: AgentName | None = None,
        session_id: str | None = None,
        runtime_root: Path | None = None,
        yolo: bool = True,
        timeout_seconds: float | None = None,
        output_last_message_path: Path | None = None,
        reasoning_effort: str = "high",
    ) -> CodexExecRunResult:
        resume_calls.append(
            (codex_session_id, prompt_text, timeout_seconds, reasoning_effort)
        )
        if output_last_message_path is not None:
            output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
            output_last_message_path.write_text("last message", encoding="utf-8")
        return CodexExecRunResult(
            command=[
                "codex",
                "exec",
                "resume",
                codex_session_id,
                "-",
            ],
            return_code=0,
            timed_out=False,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            output_last_message_path=output_last_message_path,
        )

    monkeypatch.setattr(runner, "_resume_cli_exec", fake_resume_cli_exec)
    monkeypatch.setattr(
        runner,
        "_capture_latest_codex_session_artifacts",
        lambda **_: None,
    )
    monkeypatch.setattr(runner, "SESSION_LOG_ROOT", tmp_path / "session-root")

    summary, updated_trace = await runner._run_skill_loop(
        item=item,
        agent_name=AgentName.ENGINEER_CODER,
        workspace_dir=workspace_dir,
        cli_runtime_root=tmp_path / "codex-runtime",
        eval_log_key="ec-001",
        baseline_snapshot=baseline_snapshot,
        codex_trace_artifacts=None,
        primary_session_id=primary_session_id,
        launch_return_code=1,
        verification_result=SimpleNamespace(
            success=False,
            verification_name="coder_workspace_contract",
            errors=["missing simulation_result.json"],
            details={},
        ),
        log=runner.logger,
    )

    assert summary.triggered is True
    assert summary.primary_turn is not None
    assert summary.primary_turn.session_id == primary_session_id
    assert summary.self_analysis_turn is not None
    assert summary.skill_update_turn is not None
    assert summary.failure_reason is None
    assert len(resume_calls) == 2
    assert resume_calls[0][0] == primary_session_id
    assert resume_calls[1][0] == primary_session_id
    assert updated_trace is None


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-246")
def test_run_evals_codex_readable_logs_mirror_imported_transcript(
    tmp_path, monkeypatch
):
    readable_log = tmp_path / "readable_agent_logs.log"
    session_root = tmp_path / "sessions"
    transcript_path = tmp_path / "transcript.log"
    transcript_path.write_text(
        "\n".join(
            [
                "SESSION_META id=codex-123 cwd=/workspace model=gpt-5.4-mini originator=codex",
                "MESSAGE role=user phase=prompt text=Workspace: current directory",
                'TOOL_CALL python args={"code":"print(1)"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(runner, "READABLE_AGENT_LOG_FILE", readable_log)
    monkeypatch.setattr(runner, "SESSION_LOG_ROOT", session_root)

    artifact = CodexSessionTraceArtifact(
        session_id="codex-123",
        transcript_path=transcript_path,
    )

    runner._mirror_session_trace_to_readable_logs(  # type: ignore[attr-defined]
        artifact,
        eval_log_key="ec-001",
    )

    readable_text = readable_log.read_text(encoding="utf-8")
    session_text = (session_root / "ec-001" / "readable_agent_logs.log").read_text(
        encoding="utf-8"
    )

    assert "CODEX_SESSION_TRACE_IMPORTED session_id=codex-123" in readable_text
    assert "SESSION_META id=codex-123 cwd=/workspace" in readable_text
    assert (
        "MESSAGE role=user phase=prompt text=Workspace: current directory"
        in readable_text
    )
    assert 'TOOL_CALL python args={"code":"print(1)"}' in readable_text
    assert readable_text == session_text


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-247")
def test_run_evals_level_filter_parser_accepts_repeated_and_bracketed_values():
    from evals.logic.runner import _parse_level_filters

    assert _parse_level_filters(["0", "1,2", "[3,4]", "5 or 0"]) == {
        0,
        1,
        2,
        3,
        4,
        5,
    }


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-248")
def test_run_evals_codex_env_uses_isolated_home_and_workspace_pythonpath(tmp_path):
    source_auth_path = tmp_path / "source-home" / ".codex" / "auth.json"
    source_auth_path.parent.mkdir(parents=True, exist_ok=True)
    source_auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    codex_home_root = tmp_path / "codex-home"
    codex_home_dir = prepare_cli_home(
        codex_home_root=codex_home_root,
        workspace_dir=workspace_dir,
        source_auth_path=source_auth_path,
    )

    env = build_cli_env(
        task_id="task-1",
        workspace_dir=workspace_dir,
        codex_home_root=codex_home_root,
        session_id="session-1",
    )

    assert env["HOME"] == str(codex_home_root)
    assert env["CODEX_HOME"] == str(codex_home_dir)
    assert env["PYTHONPATH"].split(os.pathsep)[:2] == [
        str(workspace_dir.resolve()),
        str(ROOT),
    ]
    assert env["PROBLEMOLOGIST_REPO_ROOT"] == str(ROOT)
    assert env["PYTHON_BIN"] == str(ROOT / ".venv" / "bin" / "python")
    assert env["CONTROLLER_URL"] == "http://127.0.0.1:28000"
    assert env["WORKER_LIGHT_URL"] == "http://127.0.0.1:28001"
    assert env["WORKER_HEAVY_URL"] == "http://127.0.0.1:28002"
    assert env["WORKER_RENDERER_URL"] == "http://127.0.0.1:28003"
    assert (
        json.loads((codex_home_dir / "auth.json").read_text(encoding="utf-8"))[
            "tokens"
        ]["account_id"]
        == "acct-1"
    )
    config_text = (codex_home_dir / "config.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-5.4-mini"' in config_text
    assert 'model_reasoning_effort = "high"' in config_text
    assert "use_legacy_landlock = true" in config_text
    assert str(workspace_dir.resolve()) in config_text
    assert "mcp_servers" not in config_text


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-249")
def test_cli_provider_reasoning_effort_translation_hook_is_used(tmp_path):
    source_auth_path = tmp_path / "source-home" / ".codex" / "auth.json"
    source_auth_path.parent.mkdir(parents=True, exist_ok=True)
    source_auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    class RemappedCodexProvider(CodexCliProvider):
        def translate_reasoning_effort(
            self, reasoning_effort: str | None
        ) -> str | None:
            if reasoning_effort == "xhigh":
                return "ultra"
            return super().translate_reasoning_effort(reasoning_effort)

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    provider = RemappedCodexProvider()
    codex_home_root = tmp_path / "codex-home"
    codex_home_dir = provider.prepare_home(
        codex_home_root=codex_home_root,
        workspace_dir=workspace_dir,
        source_auth_path=source_auth_path,
        agent_name=AgentName.ENGINEER_PLANNER,
        reasoning_effort="xhigh",
    )

    config_text = (codex_home_dir / "config.toml").read_text(encoding="utf-8")
    assert 'model_reasoning_effort = "ultra"' in config_text


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-250")
def test_run_evals_codex_env_supports_repo_root_imports(tmp_path):
    source_auth_path = tmp_path / "source-home" / ".codex" / "auth.json"
    source_auth_path.parent.mkdir(parents=True, exist_ok=True)
    source_auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "script.py").write_text(
        "from shared.models.schemas import PartMetadata\n"
        "print(PartMetadata(material_id='aluminum_6061', is_fixed=True).model_dump())\n",
        encoding="utf-8",
    )

    codex_home_root = tmp_path / "codex-home"
    prepare_cli_home(
        codex_home_root=codex_home_root,
        workspace_dir=workspace_dir,
        source_auth_path=source_auth_path,
    )

    env = build_cli_env(
        task_id="task-1",
        workspace_dir=workspace_dir,
        codex_home_root=codex_home_root,
        session_id="session-1",
    )

    completed = subprocess.run(
        [env["PYTHON_BIN"], "script.py"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "aluminum_6061" in completed.stdout


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-251")
def test_run_evals_codex_env_uses_role_reasoning_effort_and_can_disable(
    tmp_path, monkeypatch
):
    source_auth_path = tmp_path / "source-home" / ".codex" / "auth.json"
    source_auth_path.parent.mkdir(parents=True, exist_ok=True)
    source_auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    planner_home_root = tmp_path / "codex-home-planner"
    planner_home = prepare_cli_home(
        codex_home_root=planner_home_root,
        workspace_dir=workspace_dir,
        source_auth_path=source_auth_path,
        agent_name=AgentName.ENGINEER_PLANNER,
    )
    planner_config = (planner_home / "config.toml").read_text(encoding="utf-8")
    assert 'model_reasoning_effort = "xhigh"' in planner_config

    coder_home_root = tmp_path / "codex-home-coder"
    coder_home = prepare_cli_home(
        codex_home_root=coder_home_root,
        workspace_dir=workspace_dir,
        source_auth_path=source_auth_path,
        agent_name=AgentName.ENGINEER_CODER,
    )
    coder_config = (coder_home / "config.toml").read_text(encoding="utf-8")
    assert 'model_reasoning_effort = "high"' in coder_config

    disabled_agents_config = _load_agents_config_with_reasoning_effort_enabled(False)
    monkeypatch.setattr(
        "evals.logic.cli_provider.load_agents_config",
        lambda: disabled_agents_config,
    )
    disabled_home_root = tmp_path / "codex-home-disabled"
    disabled_home = prepare_cli_home(
        codex_home_root=disabled_home_root,
        workspace_dir=workspace_dir,
        source_auth_path=source_auth_path,
        agent_name=AgentName.ENGINEER_PLANNER,
    )
    disabled_config = (disabled_home / "config.toml").read_text(encoding="utf-8")
    assert "model_reasoning_effort" not in disabled_config


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-252")
def test_run_evals_build_dspy_lm_uses_configured_reasoning_effort_and_toggle(
    monkeypatch,
):
    from controller.agent import config as agent_config

    captured: list[str | None] = []

    class DummyLM:
        def __init__(self) -> None:
            self.node_type = None
            self.session_id = None

        def copy(self) -> DummyLM:
            return self

    def fake_build_cached_dspy_lm(
        model: str,
        api_key: str,
        api_base: str | None,
        timeout_seconds: int,
        max_tokens: int,
        num_retries: int,
        reasoning_effort: str | None = None,
    ) -> DummyLM:
        captured.append(reasoning_effort)
        return DummyLM()

    monkeypatch.setattr(agent_config.settings, "is_integration_test", False)
    monkeypatch.setattr(
        agent_config,
        "_build_cached_dspy_lm",
        fake_build_cached_dspy_lm,
    )

    enabled_agents_config = _load_agents_config_with_reasoning_effort_enabled(True)
    monkeypatch.setattr(
        agent_config,
        "load_agents_config",
        lambda: enabled_agents_config,
    )

    planner_lm = agent_config.build_dspy_lm(
        model_name="gpt-5.4-mini",
        session_id="session-1",
        agent_role=AgentName.ENGINEER_PLANNER.value,
    )

    assert captured[-1] == "xhigh"
    assert planner_lm.node_type == AgentName.ENGINEER_PLANNER.value
    assert planner_lm.session_id == "session-1"

    disabled_agents_config = _load_agents_config_with_reasoning_effort_enabled(False)
    monkeypatch.setattr(
        agent_config,
        "load_agents_config",
        lambda: disabled_agents_config,
    )

    coder_lm = agent_config.build_dspy_lm(
        model_name="gpt-5.4-mini",
        session_id="session-2",
        agent_role=AgentName.ENGINEER_CODER.value,
    )

    assert captured[-1] is None
    assert coder_lm.node_type == AgentName.ENGINEER_CODER.value
    assert coder_lm.session_id == "session-2"


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-253")
def test_run_evals_codex_vtk_preview_renders_headlessly(tmp_path, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("XAUTHORITY", raising=False)

    with BuildPart() as builder:
        Box(1, 1, 1)
    component = builder.part
    component.label = "display_box"
    component.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum_6061",
        is_fixed=True,
    )

    output_path = tmp_path / "renders" / "preview.png"
    rendered_path = render_preview_view(
        component,
        output_path=output_path,
        pitch=-35.0,
        yaw=45.0,
        workspace_root=tmp_path,
    )

    assert rendered_path == output_path
    assert output_path.exists(), output_path
    assert output_path.stat().st_size > 0


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-254")
def test_preview_scene_bundle_carries_current_role_manifest(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    manifest_path = workspace_root / ".manifests" / "current_role.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        current_role_manifest_json(AgentName.ENGINEER_CODER),
        encoding="utf-8",
    )

    with BuildPart() as builder:
        Box(1, 1, 1)
    component = builder.part
    component.label = "bundle_box"
    component.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum_6061",
        is_fixed=True,
    )

    bundle_base64 = export_preview_scene_bundle(
        component,
        objectives=None,
        workspace_root=workspace_root,
    )

    extracted_root = tmp_path / "extracted"
    extracted_root.mkdir()
    extract_bundle_base64(bundle_base64, extracted_root)

    extracted_manifest = extracted_root / ".manifests" / "current_role.json"
    assert extracted_manifest.is_file(), extracted_manifest
    assert (
        parse_current_role_manifest(
            extracted_manifest.read_text(encoding="utf-8")
        ).agent_name
        == AgentName.ENGINEER_CODER
    )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-255")
def test_run_evals_codex_submit_helper_imports_workspace_script_from_cwd(
    tmp_path,
):
    item = _load_dataset_item(
        "dataset/data/seed/role_based/engineer_coder.json",
        "ec-001",
    )
    workspace_dir = tmp_path / "workspace"
    materialize_seed_workspace(
        item=item,
        agent_name=AgentName.ENGINEER_CODER,
        workspace_dir=workspace_dir,
    )

    env = os.environ.copy()
    env.update(
        {
            "PROBLEMOLOGIST_REPO_ROOT": str(ROOT),
            "PYTHON_BIN": str(ROOT / ".venv" / "bin" / "python"),
            "DISPLAY": ":109",
        }
    )
    completed = subprocess.run(
        ["bash", "scripts/submit_solution_for_review.sh"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )
    assert "No module named 'script'" not in combined_output, combined_output
    assert len(combined_output.splitlines()) <= 25, combined_output

    payload = json.loads(completed.stdout)
    assert payload["stage"] != "load"
    assert payload["log_path"] == "logs/submit_for_review.log"

    submission_log = workspace_dir / "logs" / "submit_for_review.log"
    assert submission_log.exists(), submission_log
    submission_log_text = submission_log.read_text(encoding="utf-8")
    assert "validate_start" in submission_log_text, submission_log_text


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-256")
def test_run_evals_codex_submit_helper_forces_headless_rendering_env(tmp_path):
    item = _load_dataset_item(
        "dataset/data/seed/role_based/engineer_coder.json",
        "ec-001",
    )
    workspace_dir = tmp_path / "workspace"
    materialize_seed_workspace(
        item=item,
        agent_name=AgentName.ENGINEER_CODER,
        workspace_dir=workspace_dir,
    )

    python_probe = tmp_path / "python-probe"
    python_probe.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            from __future__ import annotations

            import json
            import os
            import sys

            if len(sys.argv) > 1 and sys.argv[1] == "-":
                raise SystemExit(0)

            payload = {
                "argv": sys.argv[1:],
                "DISPLAY": os.environ.get("DISPLAY"),
                "XAUTHORITY": os.environ.get("XAUTHORITY"),
                "LIBGL_ALWAYS_SOFTWARE": os.environ.get("LIBGL_ALWAYS_SOFTWARE"),
                "MUJOCO_GL": os.environ.get("MUJOCO_GL"),
                "PYOPENGL_PLATFORM": os.environ.get("PYOPENGL_PLATFORM"),
                "PYVISTA_OFF_SCREEN": os.environ.get("PYVISTA_OFF_SCREEN"),
                "VTK_DEFAULT_OPENGL_WINDOW": os.environ.get(
                    "VTK_DEFAULT_OPENGL_WINDOW"
                ),
                "PYGLET_HEADLESS": os.environ.get("PYGLET_HEADLESS"),
                "PYTHONPATH": os.environ.get("PYTHONPATH"),
            }
            print(json.dumps(payload))
            """
        ),
        encoding="utf-8",
    )
    python_probe.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PROBLEMOLOGIST_REPO_ROOT": str(ROOT),
            "PYTHON_BIN": str(python_probe),
            "DISPLAY": ":109",
            "XAUTHORITY": "/tmp/xauthority",
            "MUJOCO_GL": "osmesa",
            "PYOPENGL_PLATFORM": "osmesa",
            "VTK_DEFAULT_OPENGL_WINDOW": "vtkOSOpenGLRenderWindow",
        }
    )
    completed = subprocess.run(
        ["bash", "scripts/submit_solution_for_review.sh"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip(), completed.stderr
    payload = json.loads(completed.stdout.strip())
    assert payload["argv"] == ["scripts/submit_for_review.py"]
    assert payload["DISPLAY"] is None
    assert payload["XAUTHORITY"] is None
    assert payload["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert payload["MUJOCO_GL"] == "egl"
    assert payload["PYOPENGL_PLATFORM"] == "osmesa"
    assert payload["PYVISTA_OFF_SCREEN"] == "true"
    assert payload["VTK_DEFAULT_OPENGL_WINDOW"] == "vtkOSOpenGLRenderWindow"
    assert payload["PYGLET_HEADLESS"] == "1"
    assert str(ROOT) in (payload["PYTHONPATH"] or "")


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-257")
@pytest.mark.parametrize(
    ("extra_flags", "expected_fragment", "unexpected_fragment"),
    [
        (("--no-yolo",), "--full-auto", "--dangerously-bypass-approvals-and-sandbox"),
        (("--yolo",), "--dangerously-bypass-approvals-and-sandbox", "--full-auto"),
    ],
)
def test_launch_codex_exec_uses_expected_sandbox_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_flags: tuple[str, ...],
    expected_fragment: str,
    unexpected_fragment: str,
):
    fake_home = tmp_path / "home"
    auth_path = fake_home / ".codex" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    provider = RecordingCliProvider(tmp_path / "codex-args.log")
    monkeypatch.setattr(
        "evals.logic.codex_workspace.get_cli_provider",
        lambda: provider,
    )
    monkeypatch.setenv("HOME", str(fake_home))

    result = launch_cli_exec(
        workspace_dir,
        "run the seeded workspace",
        task_id="ec-001",
        agent_name=AgentName.ENGINEER_CODER,
        session_id="home-session-1",
        runtime_root=tmp_path / "codex-runtime",
        yolo="--yolo" in extra_flags,
    )

    assert result == 0
    logged_args = (tmp_path / "codex-args.log").read_text(encoding="utf-8")
    assert expected_fragment in logged_args
    assert unexpected_fragment not in logged_args


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-258")
def test_launch_codex_exec_allows_host_loopback_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_home = tmp_path / "home"
    auth_path = fake_home / ".codex" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    provider = RecordingCliProvider(tmp_path / "codex-args.log")
    monkeypatch.setattr(
        "evals.logic.codex_workspace.get_cli_provider",
        lambda: provider,
    )
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("PROBLEMOLOGIST_CLI_ALLOW_HOST_LOOPBACK", "1")

    result = launch_cli_exec(
        workspace_dir,
        "run the seeded workspace",
        task_id="ec-001",
        agent_name=AgentName.ENGINEER_CODER,
        session_id="home-session-1",
        runtime_root=tmp_path / "codex-runtime",
        yolo=False,
    )

    assert result == 0
    logged_args = (tmp_path / "codex-args.log").read_text(encoding="utf-8")
    assert "--dangerously-bypass-approvals-and-sandbox" in logged_args
    assert "--full-auto" not in logged_args
    assert workspace_dir.exists()


def _build_cli_runtime_context_for_test(
    item: EvalDatasetItem, agent_name: AgentName
) -> str:
    dataset_note = (
        f"Seed dataset: {item.seed_dataset}"
        if item.seed_dataset is not None
        else "Seed dataset: not provided"
    )
    return "\n".join(
        [
            "Workspace: current directory",
            f"Agent: {agent_name.value}",
            f"Task ID: {item.id}",
            dataset_note,
            "",
            "Task:",
            item.task.strip(),
            "",
            "Workspace contract:",
            "- Use workspace-relative paths only.",
            "- The workspace already contains the starter files, role templates, and any copied seed artifacts.",
            "- Treat `.manifests/` as system-owned and do not edit it directly.",
            "- If you need a clean retry, run `python .admin/clear_env.py` to restore the seeded workspace in place.",
        ]
    )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-259")
def test_prompt_source_role_prompts_follow_runtime_order():
    prompt_source = load_prompts()

    assert list(prompt_source["role_prompts"].keys()) == [
        "benchmark_planner",
        "benchmark_plan_reviewer",
        "benchmark_coder",
        "benchmark_reviewer",
        "engineer_planner",
        "engineer_plan_reviewer",
        "engineer_coder",
        "engineer_execution_reviewer",
        "journalling_agent",
        "default",
    ]
    assert "bug_reporting" in prompt_source["appendices"]
    assert sorted(prompt_source["appendices"]["cli"]["providers"].keys()) == [
        "codex",
        "qwen",
    ]


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-260")
def test_prompt_manager_unified_render_uses_shared_source_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    data = yaml.safe_load(AGENTS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    data.setdefault("bug_reports", {})["enabled"] = False
    config = AgentsConfig.model_validate(data)
    monkeypatch.setattr(
        "controller.agent.prompt_manager.load_agents_config",
        lambda: config,
    )

    item = _load_dataset_item(
        "dataset/data/seed/role_based/engineer_coder.json",
        "ec-001",
    )
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(
        "evals.logic.codex_workspace.resolve_seed_artifact_dir",
        lambda *args, **kwargs: None,
    )
    materialized = materialize_seed_workspace(
        item=item,
        agent_name=AgentName.ENGINEER_CODER,
        workspace_dir=workspace_dir,
    )

    prompt_manager = PromptManager()
    api_prompt = prompt_manager.render(AgentName.ENGINEER_CODER)
    cli_prompt = prompt_manager.render(
        AgentName.ENGINEER_CODER,
        backend_family="cli_based",
        runtime_context=_build_cli_runtime_context_for_test(
            item, AgentName.ENGINEER_CODER
        ),
    )

    assert "You are the Engineer Coder." in api_prompt
    assert "You are the Engineer Coder." in cli_prompt
    assert "Use workspace-relative paths only." in api_prompt
    assert "Use workspace-relative paths only." in cli_prompt
    assert api_prompt.index("Use workspace-relative paths only.") < api_prompt.index(
        "Use controller-managed tools and provider-native tool calls."
    )
    assert cli_prompt.index("Use workspace-relative paths only.") < cli_prompt.index(
        "This is a local CLI-provider workspace."
    )
    assert "Available skills you can read:" in api_prompt
    assert "Available skills you can read:" not in cli_prompt
    assert cli_prompt.index(
        "This is a local CLI-provider workspace."
    ) < cli_prompt.index("Workspace: current directory")
    assert "common.code_template" not in cli_prompt
    assert "Bug-report mode is a global diagnostic overlay." not in api_prompt
    assert "Bug-report mode is a global diagnostic overlay." not in cli_prompt
    assert materialized.prompt_text == cli_prompt


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-261")
def test_prompt_manager_appends_cli_provider_specific_appendix():
    item = _load_dataset_item(
        "dataset/data/seed/role_based/engineer_coder.json",
        "ec-001",
    )

    prompt_manager = PromptManager()
    prompt = prompt_manager.render(
        AgentName.ENGINEER_CODER,
        backend_family="cli_based",
        cli_provider_name="qwen",
        runtime_context=_build_cli_runtime_context_for_test(
            item, AgentName.ENGINEER_CODER
        ),
    )

    assert "This is a local CLI-provider workspace." in prompt
    assert (
        "Qwen-specific reminder: use `render_cad(...)` for CAD geometry, then inspect the generated render files with `read_file` even if you think you do not have a dedicated image tool. Reread the active workspace state before answering and do not rely on memory across turns."
        in prompt
    )
    assert (
        "Codex-specific reminder: keep the local shell helper flow and resume syntax in mind."
        not in prompt
    )
    assert prompt.index("This is a local CLI-provider workspace.") < prompt.index(
        "Qwen-specific reminder: use `render_cad(...)` for CAD geometry, then inspect the generated render files with `read_file` even if you think you do not have a dedicated image tool. Reread the active workspace state before answering and do not rely on memory across turns."
    )
    assert prompt.index(
        "Qwen-specific reminder: use `render_cad(...)` for CAD geometry, then inspect the generated render files with `read_file` even if you think you do not have a dedicated image tool. Reread the active workspace state before answering and do not rely on memory across turns."
    ) < prompt.index("Workspace: current directory")


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-262")
def test_prompt_manager_injects_bug_reporting_appendix_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    data = yaml.safe_load(AGENTS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    data.setdefault("bug_reports", {})["enabled"] = True
    config = AgentsConfig.model_validate(data)
    monkeypatch.setattr(
        "controller.agent.prompt_manager.load_agents_config",
        lambda: config,
    )

    item = _load_dataset_item(
        "dataset/data/seed/role_based/engineer_coder.json",
        "ec-001",
    )
    prompt_manager = PromptManager()
    api_prompt = prompt_manager.render(AgentName.ENGINEER_CODER)
    cli_prompt = prompt_manager.render(
        AgentName.ENGINEER_CODER,
        backend_family="cli_based",
        runtime_context=_build_cli_runtime_context_for_test(
            item, AgentName.ENGINEER_CODER
        ),
    )

    assert "Bug-report mode is a global diagnostic overlay." in api_prompt
    assert "Bug-report mode is a global diagnostic overlay." in cli_prompt
    assert (
        "Keep the report concise and factual: include the active role, session or episode identifiers when available, the exact failing command or tool call, expected versus actual behavior, and the relevant artifact paths."
        in api_prompt
    )
    assert (
        "Filing a bug report is diagnostic, not terminal; continue working unless the task is otherwise blocked or the run has reached a hard stop."
        in cli_prompt
    )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-263")
def test_materialize_seed_workspace_threads_cli_provider_specific_appendix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    item = _load_dataset_item(
        "dataset/data/seed/role_based/engineer_coder.json",
        "ec-001",
    )
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(
        "evals.logic.codex_workspace.resolve_seed_artifact_dir",
        lambda *args, **kwargs: None,
    )

    materialized = materialize_seed_workspace(
        item=item,
        agent_name=AgentName.ENGINEER_CODER,
        workspace_dir=workspace_dir,
        provider_name="qwen",
    )

    assert (
        "Qwen-specific reminder: use `render_cad(...)` for CAD geometry, then inspect the generated render files with `read_file` even if you think you do not have a dedicated image tool. Reread the active workspace state before answering and do not rely on memory across turns."
        in materialized.prompt_text
    )
    assert (
        "Codex-specific reminder: keep the local shell helper flow and resume syntax in mind."
        not in materialized.prompt_text
    )


async def _assert_codex_materialized_planner_workspace_submits(
    *,
    tmp_path: Path,
    int_id: str,
    agent_name: AgentName,
    expected_manifest: str,
    prompt_fragments: tuple[str, ...],
    expected_files: tuple[str, ...],
    expected_helper_scripts: tuple[str, ...],
) -> None:
    item = _synthetic_planner_item(agent_name, int_id)
    workspace_dir = tmp_path / agent_name.value / item.id
    materialized = materialize_seed_workspace(
        item=item,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
    )
    mirror_workspace_dir = tmp_path / f"{agent_name.value}-mirror" / item.id
    mirror_materialized = materialize_seed_workspace(
        item=item,
        agent_name=agent_name,
        workspace_dir=mirror_workspace_dir,
    )

    assert materialized.helper_script_paths == list(expected_helper_scripts)
    assert mirror_materialized.helper_script_paths == list(expected_helper_scripts)
    assert "Workspace: current directory" in materialized.prompt_text
    assert "/workspace" not in materialized.prompt_text
    assert "python .admin/clear_env.py" in materialized.prompt_text
    assert "Available skills you can read:" not in materialized.prompt_text
    assert "/skills/runtime-script-contract/SKILL.md" not in materialized.prompt_text
    _assert_skills_tree_materialized(workspace_dir)
    _assert_skills_tree_materialized(mirror_workspace_dir)
    _assert_skill_projection(workspace_dir, agent_name)
    _assert_skill_projection(mirror_workspace_dir, agent_name)
    assert any(path.startswith(".agents/skills/") for path in materialized.copied_paths)
    assert any(
        path.startswith(".agents/skills/") for path in mirror_materialized.copied_paths
    )
    assert materialized.prompt_text == mirror_materialized.prompt_text
    assert materialized.copied_paths == mirror_materialized.copied_paths
    assert _workspace_snapshot(workspace_dir) == _workspace_snapshot(
        mirror_workspace_dir
    )
    for fragment in prompt_fragments:
        assert fragment in materialized.prompt_text
    assert not any(path.endswith("result.py") for path in materialized.copied_paths)
    for rel_path in expected_files:
        assert (workspace_dir / rel_path).exists(), rel_path
    for rel_path in expected_helper_scripts:
        assert (workspace_dir / rel_path).exists(), rel_path
    current_role_path = workspace_dir / ".manifests" / "current_role.json"
    assert current_role_path.exists()
    assert (
        parse_current_role_manifest(
            current_role_path.read_text(encoding="utf-8")
        ).agent_name
        == agent_name
    )

    shutil.rmtree(workspace_dir / ".manifests", ignore_errors=True)

    source_auth_path = tmp_path / "source-home" / ".codex" / "auth.json"
    source_auth_path.parent.mkdir(parents=True, exist_ok=True)
    source_auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    codex_home_root = tmp_path / "codex-home"
    prepare_cli_home(
        codex_home_root=codex_home_root,
        workspace_dir=workspace_dir,
        source_auth_path=source_auth_path,
    )

    env = build_cli_env(
        task_id=item.id,
        workspace_dir=workspace_dir,
        codex_home_root=codex_home_root,
        session_id=f"{int_id}-{agent_name.value}",
        agent_name=agent_name,
    )
    assert "AGENT_NAME" not in env
    assert env["PROBLEMOLOGIST_REPO_ROOT"] == str(ROOT)
    assert str(ROOT) in env["PYTHONPATH"].split(os.pathsep)
    assert current_role_path.exists()
    assert (
        parse_current_role_manifest(
            current_role_path.read_text(encoding="utf-8")
        ).agent_name
        == agent_name
    )

    completed = subprocess.run(
        ["bash", expected_helper_scripts[0]],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = _load_submission_result(completed.stdout)
    assert result.ok is True
    assert result.status == "submitted"
    assert result.node_type == agent_name
    assert not result.errors

    manifest_path = workspace_dir / expected_manifest
    assert manifest_path.exists(), manifest_path

    verification = await verify_planner_workspace(
        workspace_dir=workspace_dir,
        agent_name=agent_name,
        session_id=env["SESSION_ID"],
    )
    assert verification.success, verification.errors
    assert verification.verification_name == "planner_workspace_contract"


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-218")
@pytest.mark.asyncio
async def test_codex_materialized_benchmark_planner_workspace_submits(
    tmp_path: Path,
):
    await _assert_codex_materialized_planner_workspace_submits(
        tmp_path=tmp_path,
        int_id="INT-218",
        agent_name=AgentName.BENCHMARK_PLANNER,
        expected_manifest=".manifests/benchmark_plan_review_manifest.json",
        prompt_fragments=(
            "Use workspace-relative paths only.",
            "bash scripts/submit_benchmark_plan.sh",
            "benchmark_assembly_definition.yaml",
        ),
        expected_files=(
            ".admin/clear_env.py",
            "benchmark_plan.md",
            "todo.md",
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
            "benchmark_plan_evidence_script.py",
            "scripts/submit_benchmark_plan.sh",
            "scripts/submit_plan.py",
            "journal.md",
        ),
        expected_helper_scripts=("scripts/submit_benchmark_plan.sh",),
    )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-219")
@pytest.mark.asyncio
async def test_codex_materialized_engineer_planner_workspace_submits(
    tmp_path: Path,
):
    await _assert_codex_materialized_planner_workspace_submits(
        tmp_path=tmp_path,
        int_id="INT-219",
        agent_name=AgentName.ENGINEER_PLANNER,
        expected_manifest=".manifests/engineering_plan_review_manifest.json",
        prompt_fragments=(
            "Use workspace-relative paths only.",
            "bash scripts/submit_engineering_plan.sh",
            "assembly_definition.yaml",
        ),
        expected_files=(
            ".admin/clear_env.py",
            "engineering_plan.md",
            "todo.md",
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
            "assembly_definition.yaml",
            "benchmark_plan_evidence_script.py",
            "solution_plan_evidence_script.py",
            "scripts/submit_engineering_plan.sh",
            "scripts/submit_plan.py",
            "journal.md",
        ),
        expected_helper_scripts=("scripts/submit_engineering_plan.sh",),
    )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-264")
@pytest.mark.asyncio
async def test_codex_role_scoped_planner_wrapper_rejects_mismatched_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    item = _load_dataset_item(
        "dataset/data/seed/role_based/engineer_plan_reviewer.json",
        "epr-001",
    )
    workspace_dir = tmp_path / AgentName.ENGINEER_PLANNER.value / item.id
    materialize_seed_workspace(
        item=item,
        agent_name=AgentName.ENGINEER_PLANNER,
        workspace_dir=workspace_dir,
    )

    source_auth_path = tmp_path / "source-home" / ".codex" / "auth.json"
    source_auth_path.parent.mkdir(parents=True, exist_ok=True)
    source_auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"account_id": "acct-1", "access_token": "token-1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    codex_home_root = tmp_path / "codex-home"
    prepare_cli_home(
        codex_home_root=codex_home_root,
        workspace_dir=workspace_dir,
        source_auth_path=source_auth_path,
    )

    env = build_cli_env(
        task_id=item.id,
        workspace_dir=workspace_dir,
        codex_home_root=codex_home_root,
        session_id=f"INT-CODEX-{AgentName.ENGINEER_PLANNER.value}-{item.id}",
        agent_name=AgentName.ENGINEER_PLANNER,
    )

    completed = subprocess.run(
        ["bash", "scripts/submit_benchmark_plan.sh"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode != 0
    assert (
        "submit_benchmark_plan.sh requires current role benchmark_planner"
        in completed.stderr
    )
    assert "found engineer_planner" in completed.stderr


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-265")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "seed_dataset",
        "row_id",
        "agent_name",
        "prompt_fragments",
        "expected_files",
        "expected_helper_scripts",
    ),
    [
        (
            "dataset/data/seed/role_based/benchmark_plan_reviewer.json",
            "bpr-012",
            AgentName.BENCHMARK_PLAN_REVIEWER,
            (
                "You are the Plan Reviewer.",
                "Inspect the planner artifacts",
                "reviews/",
                "bash scripts/submit_review.sh",
                "python .admin/clear_env.py",
            ),
            (
                ".admin/clear_env.py",
                "benchmark_plan.md",
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
                "scripts/submit_review.sh",
                "scripts/submit_review.py",
            ),
            ("scripts/submit_review.sh",),
        ),
        (
            "dataset/data/seed/role_based/benchmark_coder.json",
            "bc-001",
            AgentName.BENCHMARK_CODER,
            (
                "You are the Benchmark Coder.",
                "Edit `benchmark_script.py` and any supporting `*.py` files",
                "journal.md",
                "bash scripts/submit_benchmark_for_review.sh",
                "utils.submission",
                "result = build()",
                "python benchmark_script.py",
                "python .admin/clear_env.py",
            ),
            (
                ".admin/clear_env.py",
                "benchmark_plan.md",
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
                "benchmark_script.py",
                "journal.md",
                "scripts/submit_benchmark_for_review.sh",
                "scripts/submit_for_review.py",
            ),
            ("scripts/submit_benchmark_for_review.sh",),
        ),
        (
            "dataset/data/seed/role_based/engineer_coder.json",
            "ec-001",
            AgentName.ENGINEER_CODER,
            (
                "You are the Engineer Coder.",
                "Edit `solution_script.py` and any supporting `*.py` files",
                "journal.md",
                "bash scripts/submit_solution_for_review.sh",
                "utils.submission",
                "result = build()",
                "python solution_script.py",
                "python .admin/clear_env.py",
            ),
            (
                ".admin/clear_env.py",
                "engineering_plan.md",
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_script.py",
                "assembly_definition.yaml",
                "benchmark_assembly_definition.yaml",
                "journal.md",
                "scripts/submit_solution_for_review.sh",
                "scripts/submit_for_review.py",
            ),
            ("scripts/submit_solution_for_review.sh",),
        ),
        (
            "dataset/data/seed/role_based/engineer_plan_reviewer.json",
            "epr-001",
            AgentName.ENGINEER_PLAN_REVIEWER,
            (
                "You are the Plan Reviewer.",
                "Inspect the planner artifacts",
                "reviews/",
                "bash scripts/submit_review.sh",
                "python .admin/clear_env.py",
            ),
            (
                ".admin/clear_env.py",
                "engineering_plan.md",
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
                "assembly_definition.yaml",
                "solution_plan_evidence_script.py",
                "scripts/submit_review.sh",
                "scripts/submit_review.py",
            ),
            ("scripts/submit_review.sh",),
        ),
        (
            "dataset/data/seed/role_based/benchmark_reviewer.json",
            "br-001",
            AgentName.BENCHMARK_REVIEWER,
            (
                "You are the Benchmark Reviewer.",
                "Inspect the implementation, validation results, simulation result",
                "benchmark_assembly_definition.yaml",
                "benchmark_script.py",
                "reviews/",
                "bash scripts/submit_review.sh",
                "python .admin/clear_env.py",
            ),
            (
                ".admin/clear_env.py",
                "benchmark_plan.md",
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
                "benchmark_script.py",
                "benchmark_plan_evidence_script.py",
                "journal.md",
                "validation_results.json",
                "simulation_result.json",
                "scripts/submit_review.sh",
                "scripts/submit_review.py",
            ),
            ("scripts/submit_review.sh",),
        ),
        (
            "dataset/data/seed/role_based/engineer_execution_reviewer.json",
            "eer-001",
            AgentName.ENGINEER_EXECUTION_REVIEWER,
            (
                "You are the Execution Reviewer.",
                "Inspect the implementation, validation results, simulation result",
                "reviews/",
                "solution_script.py",
                "bash scripts/submit_review.sh",
                "python .admin/clear_env.py",
            ),
            (
                ".admin/clear_env.py",
                "engineering_plan.md",
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
                "assembly_definition.yaml",
                "solution_script.py",
                "journal.md",
                "validation_results.json",
                "simulation_result.json",
                "scripts/submit_review.sh",
                "scripts/submit_review.py",
            ),
            ("scripts/submit_review.sh",),
        ),
    ],
)
async def test_codex_seed_workspace_materialization_is_role_specific_and_deterministic(
    tmp_path: Path,
    seed_dataset: str,
    row_id: str,
    agent_name: AgentName,
    prompt_fragments: tuple[str, ...],
    expected_files: tuple[str, ...],
    expected_helper_scripts: tuple[str, ...],
):
    """
    INT-034: reviewer evidence completeness.

    Verifies curated benchmark plan-reviewer, benchmark-coder, and benchmark-reviewer
    fixture rows materialize into workspace-relative, deterministic local workspaces.
    """

    item = _load_dataset_item(seed_dataset, row_id)
    workspace_dir = tmp_path / agent_name.value / row_id
    mirror_workspace_dir = tmp_path / f"{agent_name.value}-mirror" / row_id

    materialized = materialize_seed_workspace(
        item=item,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
    )
    mirror_materialized = materialize_seed_workspace(
        item=item,
        agent_name=agent_name,
        workspace_dir=mirror_workspace_dir,
    )

    assert materialized.helper_script_paths == list(expected_helper_scripts)
    assert mirror_materialized.helper_script_paths == list(expected_helper_scripts)
    assert materialized.prompt_text == mirror_materialized.prompt_text
    assert materialized.copied_paths == mirror_materialized.copied_paths
    assert _workspace_snapshot(workspace_dir) == _workspace_snapshot(
        mirror_workspace_dir
    )
    assert "Workspace: current directory" in materialized.prompt_text
    assert "/workspace" not in materialized.prompt_text
    assert "Available skills you can read:" not in materialized.prompt_text
    assert "/skills/runtime-script-contract/SKILL.md" not in materialized.prompt_text
    _assert_skills_tree_materialized(workspace_dir)
    _assert_skills_tree_materialized(mirror_workspace_dir)
    _assert_skill_projection(workspace_dir, agent_name)
    _assert_skill_projection(mirror_workspace_dir, agent_name)
    assert any(path.startswith(".agents/skills/") for path in materialized.copied_paths)
    assert any(
        path.startswith(".agents/skills/") for path in mirror_materialized.copied_paths
    )
    for fragment in prompt_fragments:
        assert fragment in materialized.prompt_text
    for rel_path in expected_files:
        assert (workspace_dir / rel_path).exists(), rel_path
    for rel_path in expected_helper_scripts:
        assert (workspace_dir / rel_path).exists(), rel_path


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-266")
def test_clear_env_re_materializes_seeded_workspace_in_place(tmp_path: Path):
    item = _load_dataset_item(
        "dataset/data/seed/role_based/engineer_coder.json",
        "ec-001",
    )
    workspace_dir = tmp_path / "workspace"
    materialize_seed_workspace(
        item=item,
        agent_name=AgentName.ENGINEER_CODER,
        workspace_dir=workspace_dir,
    )
    original_snapshot = _workspace_snapshot(workspace_dir)
    original_benchmark_definition = yaml.safe_load(
        (workspace_dir / "benchmark_definition.yaml").read_text(encoding="utf-8")
    )

    (workspace_dir / "journal.md").write_text("dirty\n", encoding="utf-8")
    (workspace_dir / "scratch.txt").write_text("stale\n", encoding="utf-8")
    shutil.rmtree(workspace_dir / ".manifests", ignore_errors=True)

    codex_home_root = tmp_path / "codex-home"
    env = build_cli_env(
        task_id=item.id,
        workspace_dir=workspace_dir,
        codex_home_root=codex_home_root,
        session_id="INT-CLEAR-ENV-ec-001",
        agent_name=AgentName.ENGINEER_CODER,
    )
    completed = subprocess.run(
        [sys.executable, ".admin/clear_env.py"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 1, combined_output
    assert '"ok": true' in completed.stdout.lower()
    refreshed_snapshot = _workspace_snapshot(workspace_dir)
    refreshed_snapshot.pop("benchmark_definition.yaml", None)
    original_snapshot_without_benchmark = dict(original_snapshot)
    original_snapshot_without_benchmark.pop("benchmark_definition.yaml", None)
    assert refreshed_snapshot == original_snapshot_without_benchmark
    assert (
        yaml.safe_load(
            (workspace_dir / "benchmark_definition.yaml").read_text(encoding="utf-8")
        )
        == original_benchmark_definition
    )


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-267")
def test_validate_eval_seed_accepts_curated_rows_and_preserves_redundancy_metadata():
    """
    Seeded render evidence sanity gate and judge cost guard.

    Exercises the seed-validation CLI against representative curated rows,
    verifies the persisted curation manifests still expose deterministic
    redundancy provenance, and checks the optional judge wrapper fails closed
    when the expensive path is requested for more than 10 selected seeds
    without an explicit yes.
    """

    help_completed = subprocess.run(
        [
            sys.executable,
            "scripts/validate_eval_seed.py",
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=_validate_eval_seed_env(),
    )
    assert help_completed.returncode == 0, help_completed.stderr
    help_output = " ".join(help_completed.stdout.split()).lower()
    assert "--run-judge" in help_output, help_completed.stdout
    assert "--judge-provider" in help_output, help_completed.stdout
    assert "-y" in help_output, help_completed.stdout
    assert "--runner-backend" in help_output, help_completed.stdout
    assert "--validation-scope" in help_output, help_completed.stdout
    assert "cli" in help_output, help_completed.stdout

    validation_cases = (
        ("benchmark_planner", "bp-001"),
        ("benchmark_plan_reviewer", "bpr-002"),
        ("benchmark_coder", "bc-001"),
        ("benchmark_reviewer", "br-001"),
        ("engineer_planner", "ep-002"),
        ("engineer_plan_reviewer", "epr-002"),
        ("engineer_coder", "ec-001"),
        ("engineer_execution_reviewer", "eer-002"),
    )
    for agent_name, row_id in validation_cases:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/validate_eval_seed.py",
                "--skip-env-up",
                "--agent",
                agent_name,
                "--task-id",
                row_id,
                "--fail-fast",
                "--concurrency",
                "1",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env=_validate_eval_seed_env(),
        )

        assert completed.returncode == 0, completed.stderr
        assert "Validated 1 row(s): all passed." in completed.stdout, completed.stdout
        assert f"PASS {agent_name} {row_id}:" in completed.stdout, completed.stdout

    all_agents = subprocess.run(
        [
            sys.executable,
            "scripts/validate_eval_seed.py",
            "--skip-env-up",
            "--agent",
            "all",
            "--limit",
            "1",
            "--concurrency",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env=_validate_eval_seed_env(),
    )
    all_agents_output = "\n".join(
        part for part in (all_agents.stdout, all_agents.stderr) if part
    )
    assert "benchmark_coder" in all_agents_output, all_agents_output
    assert "engineer_execution_reviewer" in all_agents_output, all_agents_output
    assert "journalling_agent" not in all_agents_output, all_agents_output

    for manifest_path in (
        ROOT / "dataset/data/generated/component_seeded/v0.0.1/manifest.json",
        ROOT / "dataset/data/generated/workflow/v0.0.1/manifest.json",
    ):
        manifest = DatasetCurationManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        assert manifest.counts.accepted_after_pending_filter > 0
        assert manifest.counts.dedup_identity_groups_with_drops > 0
        assert manifest.counts.rejected > 0
        assert manifest.dropped_lineage, manifest_path
        assert manifest.rejected, manifest_path
        for lineage_key, dropped_episode_ids in manifest.dropped_lineage.items():
            assert lineage_key.strip()
            assert dropped_episode_ids == sorted(set(dropped_episode_ids))
        for rejected_row in manifest.rejected:
            assert rejected_row.reasons

    judge_guard = subprocess.run(
        [
            sys.executable,
            "scripts/validate_eval_seed.py",
            "--skip-env-up",
            "--agent",
            "engineer_coder",
            "--limit",
            "11",
            "--run-judge",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env=_validate_eval_seed_env(),
    )
    judge_guard_output = "\n".join(
        part for part in (judge_guard.stdout, judge_guard.stderr) if part
    )
    assert judge_guard.returncode != 0, judge_guard_output
    assert "-y" in judge_guard_output, judge_guard_output
    assert "11" in judge_guard_output, judge_guard_output


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-268")
def test_validate_eval_seed_removes_preview_bundles_from_all_seed_artifacts():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/validate_eval_seed.py",
            "--skip-env-up",
            "--agent",
            "benchmark_planner",
            "--task-id",
            "bp-001",
            "--fail-fast",
            "--concurrency",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env=_validate_eval_seed_env(),
    )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 1, combined_output
    assert "PASS benchmark_planner bp-001:" in completed.stdout, completed.stdout
    assert "black/empty" not in combined_output, combined_output

    seed_root = ROOT / "dataset" / "data" / "seed" / "role_based"
    seed_artifact_dirs = sorted(
        {
            ROOT / row["seed_artifact_dir"]
            for dataset_path in seed_root.glob("*.json")
            for row in json.loads(dataset_path.read_text(encoding="utf-8"))
            if row.get("seed_artifact_dir")
        }
    )

    assert seed_artifact_dirs, "Expected seeded artifact directories to exist."
    for artifact_dir in seed_artifact_dirs:
        assert not any(
            path.is_dir() and path.name == "current-episode"
            for path in artifact_dir.rglob("current-episode")
        ), artifact_dir
        assert not any(
            path.is_dir() and path.name == "tmp" for path in artifact_dir.rglob("tmp")
        ), artifact_dir


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-269")
def test_validate_eval_seed_can_filter_rows_by_complexity_level():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/validate_eval_seed.py",
            "--skip-env-up",
            "--agent",
            "benchmark_planner",
            "--task-id",
            "bp-001",
            "--level",
            "0",
            "--fail-fast",
            "--concurrency",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env=_validate_eval_seed_env(),
    )

    assert completed.returncode == 0, completed.stderr
    assert "Validated 1 row(s): all passed." in completed.stdout, completed.stdout
    assert "PASS benchmark_planner bp-001:" in completed.stdout, completed.stdout


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-270")
def test_validate_eval_seed_errors_only_suppresses_pass_output():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/validate_eval_seed.py",
            "--skip-env-up",
            "--agent",
            "benchmark_planner",
            "--task-id",
            "bp-001",
            "--fail-fast",
            "--concurrency",
            "1",
            "--errors-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env=_validate_eval_seed_env(),
    )

    assert completed.returncode == 0, completed.stderr
    assert "PASS benchmark_planner bp-001:" not in completed.stdout
    assert "Validated 1 row(s): all passed." not in completed.stdout


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-271")
def test_validate_eval_seed_skip_env_up_can_join_shared_eval_lock(tmp_path: Path):
    lock_path = tmp_path / "problemologist-eval.lock"
    state_path = tmp_path / "problemologist-eval.run.json"

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/validate_eval_seed.py",
                "--skip-env-up",
                "--agent",
                "benchmark_planner",
                "--task-id",
                "bp-001",
                "--fail-fast",
                "--concurrency",
                "1",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env=_validate_eval_seed_env(
                EVAL_RUN_LOCK_PATH=str(lock_path),
                EVAL_RUN_STATE_PATH=str(state_path),
            ),
        )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 0, combined_output
    assert "PASS benchmark_planner bp-001:" in completed.stdout, completed.stdout
    assert not state_path.exists(), state_path


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-272")
def test_validate_eval_seed_skip_env_up_fails_while_exclusive_eval_lock_is_held(
    tmp_path: Path,
):
    lock_path = tmp_path / "problemologist-eval.lock"
    state_path = tmp_path / "problemologist-eval.run.json"

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/validate_eval_seed.py",
                "--skip-env-up",
                "--agent",
                "benchmark_planner",
                "--task-id",
                "bp-001",
                "--fail-fast",
                "--concurrency",
                "1",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env=_validate_eval_seed_env(
                EVAL_RUN_LOCK_PATH=str(lock_path),
                EVAL_RUN_STATE_PATH=str(state_path),
            ),
        )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 1, combined_output
    assert "another eval run is already running." in completed.stderr
    assert not state_path.exists(), state_path


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-276")
def test_validate_eval_seed_default_scope_passes_ec002():
    completed = _run_validate_eval_seed(
        "--skip-env-up",
        "--agent",
        "engineer_coder",
        "--task-id",
        "ec-002",
        "--fail-fast",
        "--concurrency",
        "1",
    )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 0, combined_output
    assert "Validated 1 row(s): all passed." in completed.stdout, completed.stdout
    assert "PASS engineer_coder ec-002:" in completed.stdout, completed.stdout


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-277")
def test_validate_eval_seed_current_node_scope_still_passes_ec002():
    completed = _run_validate_eval_seed(
        "--skip-env-up",
        "--agent",
        "engineer_coder",
        "--task-id",
        "ec-002",
        "--validation-scope",
        "current-node",
        "--fail-fast",
        "--concurrency",
        "1",
    )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 0, combined_output
    assert "PASS engineer_coder ec-002:" in completed.stdout, completed.stdout
    assert "seeded-entry contract valid" in completed.stdout, completed.stdout


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-278")
def test_validate_eval_seed_rejects_invalid_validation_scope():
    completed = _run_validate_eval_seed(
        "--skip-env-up",
        "--agent",
        "engineer_coder",
        "--task-id",
        "ec-002",
        "--validation-scope",
        "not-a-real-scope",
    )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode != 0, combined_output
    assert "Unknown validation scope" in combined_output, combined_output


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-273")
def test_run_evals_skip_env_up_can_join_shared_eval_lock(tmp_path: Path):
    lock_path = tmp_path / "problemologist-eval.lock"
    state_path = tmp_path / "problemologist-eval.run.json"

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        completed = subprocess.run(
            [
                sys.executable,
                "dataset/evals/run_evals.py",
                "--skip-env-up",
                "--agent",
                "benchmark_planner",
                "--task-id",
                "bp-does-not-exist",
                "--concurrency",
                "1",
                "--no-rate-limit",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env={
                **os.environ,
                "EVAL_RUN_LOCK_PATH": str(lock_path),
                "EVAL_RUN_STATE_PATH": str(state_path),
            },
        )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 0, combined_output
    assert "Agent evals started:" in completed.stdout, completed.stdout
    assert "Agent evals finished:" in completed.stdout, completed.stdout
    assert not state_path.exists(), state_path


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-274")
def test_update_eval_seed_renders_skip_env_up_can_join_shared_eval_lock(
    tmp_path: Path,
):
    lock_path = tmp_path / "problemologist-eval.lock"
    state_path = tmp_path / "problemologist-eval.run.json"

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/update_eval_seed_renders.py",
                "--skip-env-up",
                "--agent",
                "benchmark_planner",
                "--task-id",
                "bp-does-not-exist",
                "--errors-only",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env={
                **os.environ,
                "EVAL_RUN_LOCK_PATH": str(lock_path),
                "EVAL_RUN_STATE_PATH": str(state_path),
            },
        )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )

    assert completed.returncode == 1, combined_output
    assert "another eval run is already running." not in completed.stderr
    assert "task id not found in dataset" in combined_output
    assert not state_path.exists(), state_path


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-275")
def test_refresh_plan_review_manifest_hashes_can_fix_drift(tmp_path: Path):
    artifact_dir = tmp_path / "seed_artifacts"
    artifact_dir.mkdir()

    payload_path = artifact_dir / "script.py"
    payload_path.write_text("print('hello world')\n", encoding="utf-8")

    manifest_path = artifact_dir / "benchmark_plan_review_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_hashes": {
                    "script.py": "deadbeef",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    dry_run_updates = refresh_plan_review_manifest_hashes(artifact_dir, fix=False)
    assert dry_run_updates == [manifest_path]
    assert (
        json.loads(manifest_path.read_text(encoding="utf-8"))["artifact_hashes"][
            "script.py"
        ]
        == "deadbeef"
    )

    fixed_updates = refresh_plan_review_manifest_hashes(artifact_dir, fix=True)
    assert fixed_updates == [manifest_path]

    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert (
        updated_manifest["artifact_hashes"]["script.py"]
        == hashlib.sha256(payload_path.read_bytes()).hexdigest()
    )
