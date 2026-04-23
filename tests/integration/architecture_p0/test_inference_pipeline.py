from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dataset.evals.eval_inference_pipeline import (
    _load_resume_state_skip_ids,
    _load_stage_items,
    _run_workspace_job,
    _workspace_dir_for_item,
    main,
)
from evals.logic.inference_pipeline import (
    InferenceJobState,
    InferenceJobStatus,
    InferencePipelineConfig,
    InferencePipelineMode,
    InferenceStageConfig,
    InferenceStageExecutorName,
    load_inference_config,
)
from shared.enums import AgentName
from shared.eval_artifacts import workspace_artifacts_for_agent

ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.integration_p0


def _extract_summary_path(stdout: str) -> Path:
    match = re.search(r"Summary written to (.+)", stdout)
    if not match:
        raise AssertionError(f"Could not find summary path in output:\n{stdout}")
    return Path(match.group(1).strip())


def test_inference_pipeline_dry_run_writes_summary() -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "dataset/evals/eval_inference_pipeline.py",
            "--author",
            "--stage",
            "engineer_planner",
            "--dry-run",
            "--task-id",
            "ep-gap-bridge-01",
            "--limit",
            "1",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    summary_path = _extract_summary_path(completed.stdout)
    assert summary_path.exists(), summary_path

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["pipeline_name"] == "application_inference"
    assert payload["mode"] == "application"
    assert payload.get("resume_token") is None
    assert payload["next_resume_token"] == "engineer_planner:ep-gap-bridge-01"
    assert payload["selected_job_ids"] == ["engineer_planner:ep-gap-bridge-01"]
    assert payload["completed_job_ids"] == []
    assert payload["failed_job_ids"] == []
    assert payload["queued_job_ids"] == [
        "engineer_planner:ep-gap-bridge-01->engineer_coder#01"
    ]
    assert payload["jobs"][0]["status"] == "queued"


def test_inference_pipeline_config_declares_benchmark_chain() -> None:
    config = load_inference_config(ROOT / "inference_config.yaml")
    assert config.entry_stage_name == "benchmark_planner"
    assert config.stage_names() == (
        "benchmark_planner",
        "benchmark_plan_reviewer",
        "benchmark_coder",
        "benchmark_reviewer",
        "engineer_planner",
        "engineer_coder",
    )
    assert config.stage("benchmark_planner").downstream_stage_names == [
        "benchmark_plan_reviewer"
    ]
    assert config.stage("benchmark_planner").executor.value == "seed_worker"
    assert config.stage("benchmark_plan_reviewer").downstream_stage_names == [
        "benchmark_coder"
    ]
    assert config.stage("benchmark_plan_reviewer").executor.value == "seed_worker"
    assert config.stage("benchmark_coder").downstream_stage_names == [
        "benchmark_reviewer"
    ]
    assert config.stage("benchmark_coder").executor.value == "seed_worker"
    assert config.stage("benchmark_reviewer").downstream_stage_names == [
        "engineer_planner"
    ]
    assert config.stage("benchmark_reviewer").executor.value == "seed_worker"
    assert config.stage("benchmark_reviewer").persist_back_to_seed is True
    assert config.stage("engineer_coder").executor.value == "planned"


def test_inference_pipeline_drains_wired_stage_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = InferencePipelineConfig(
        pipeline_name="application_inference",
        version=1,
        mode=InferencePipelineMode.APPLICATION,
        entry_stage_name="benchmark_planner",
        stages=[
            InferenceStageConfig(
                name="benchmark_planner",
                agent_name=AgentName.BENCHMARK_PLANNER,
                outputs_per_success=1,
                downstream_stage_names=["benchmark_plan_reviewer"],
                executor=InferenceStageExecutorName.SEED_WORKER,
            ),
            InferenceStageConfig(
                name="benchmark_plan_reviewer",
                agent_name=AgentName.BENCHMARK_PLAN_REVIEWER,
                outputs_per_success=1,
                downstream_stage_names=["benchmark_coder"],
                executor=InferenceStageExecutorName.SEED_WORKER,
            ),
            InferenceStageConfig(
                name="benchmark_coder",
                agent_name=AgentName.BENCHMARK_CODER,
                outputs_per_success=1,
                downstream_stage_names=["benchmark_reviewer"],
                executor=InferenceStageExecutorName.SEED_WORKER,
            ),
            InferenceStageConfig(
                name="benchmark_reviewer",
                agent_name=AgentName.BENCHMARK_REVIEWER,
                outputs_per_success=1,
                downstream_stage_names=["engineer_planner"],
                persist_back_to_seed=True,
                executor=InferenceStageExecutorName.SEED_WORKER,
            ),
            InferenceStageConfig(
                name="engineer_planner",
                agent_name=AgentName.ENGINEER_PLANNER,
                outputs_per_success=1,
                downstream_stage_names=["engineer_coder"],
                persist_back_to_seed=True,
                executor=InferenceStageExecutorName.SEED_WORKER,
            ),
            InferenceStageConfig(
                name="engineer_coder",
                agent_name=AgentName.ENGINEER_CODER,
                outputs_per_success=1,
                downstream_stage_names=[],
                executor=InferenceStageExecutorName.PLANNED,
            ),
        ],
    )

    parsed_args = SimpleNamespace(
        author=True,
        stage=None,
        config=ROOT / "inference_config.yaml",
        run_until_stage=None,
        provider="codex",
        family=None,
        task_id=None,
        level=None,
        limit=1,
        seed_workers=1,
        author_retries=None,
        skip_env_up=True,
        queue=False,
        validation_scope=None,
        update_manifests=None,
        validate_only=False,
        persist_results=None,
        dry_run=False,
        resume_token=None,
    )

    selected_stage_calls: list[str] = []
    executed_stage_names: list[str] = []

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._parse_args",
        lambda: parsed_args,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.load_inference_config",
        lambda *_: config,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._prepare_run_dir",
        lambda *_: tmp_path / "run",
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.load_inference_job_state",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._load_compatibility_seed_state",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.write_inference_job_state",
        lambda *_, **__: None,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._write_summary",
        lambda run_dir, summary: run_dir / "summary.json",
    )

    def fake_select_stage_items_for_run(*, stage: InferenceStageConfig, **__: object):
        selected_stage_calls.append(stage.name)
        return (
            [
                SimpleNamespace(
                    item=SimpleNamespace(
                        id=f"{stage.name}:item",
                        complexity_level=0,
                        seed_artifact_dir=None,
                    ),
                    raw_row={},
                    family=None,
                )
            ],
            [f"{stage.name}:item"],
            [],
        )

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._select_stage_items_for_run",
        fake_select_stage_items_for_run,
    )

    def fake_execute_stage_batch(*, stage: InferenceStageConfig, **kwargs: object):
        executed_stage_names.append(stage.name)
        return kwargs["pipeline_job_state"], [], False

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._execute_stage_batch",
        fake_execute_stage_batch,
    )

    assert main() == 0
    assert selected_stage_calls == [
        "benchmark_planner",
        "benchmark_plan_reviewer",
        "benchmark_coder",
        "benchmark_reviewer",
        "engineer_planner",
    ]
    assert executed_stage_names == selected_stage_calls


def test_inference_pipeline_run_until_stage_stops_before_engineer_planner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = load_inference_config(ROOT / "inference_config.yaml")

    parsed_args = SimpleNamespace(
        author=True,
        stage=None,
        config=ROOT / "inference_config.yaml",
        run_until_stage="benchmark_reviewer",
        provider="codex",
        family=None,
        task_id=None,
        level=None,
        limit=1,
        seed_workers=1,
        author_retries=None,
        skip_env_up=True,
        queue=False,
        validation_scope=None,
        update_manifests=None,
        validate_only=False,
        persist_results=None,
        dry_run=False,
        resume_token=None,
    )

    selected_stage_calls: list[str] = []
    executed_stage_names: list[str] = []

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._parse_args",
        lambda: parsed_args,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.load_inference_config",
        lambda *_: config,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._prepare_run_dir",
        lambda *_: tmp_path / "run",
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.load_inference_job_state",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._load_compatibility_seed_state",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.write_inference_job_state",
        lambda *_, **__: None,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._write_summary",
        lambda run_dir, summary: run_dir / "summary.json",
    )

    def fake_select_stage_items_for_run(*, stage: InferenceStageConfig, **__: object):
        selected_stage_calls.append(stage.name)
        return (
            [
                SimpleNamespace(
                    item=SimpleNamespace(
                        id=f"{stage.name}:item",
                        complexity_level=0,
                        seed_artifact_dir=None,
                    ),
                    raw_row={},
                    family=None,
                )
            ],
            [f"{stage.name}:item"],
            [],
        )

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._select_stage_items_for_run",
        fake_select_stage_items_for_run,
    )

    def fake_execute_stage_batch(*, stage: InferenceStageConfig, **kwargs: object):
        executed_stage_names.append(stage.name)
        return kwargs["pipeline_job_state"], [], False

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._execute_stage_batch",
        fake_execute_stage_batch,
    )

    assert main() == 0
    assert selected_stage_calls == [
        "benchmark_planner",
        "benchmark_plan_reviewer",
        "benchmark_coder",
        "benchmark_reviewer",
    ]
    assert executed_stage_names == selected_stage_calls


def test_inference_pipeline_skipped_entry_stage_still_drains_downstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = load_inference_config(ROOT / "inference_config.yaml")

    parsed_args = SimpleNamespace(
        author=True,
        stage=None,
        config=ROOT / "inference_config.yaml",
        run_until_stage="benchmark_reviewer",
        provider="codex",
        family=None,
        task_id=None,
        level=None,
        limit=1,
        seed_workers=1,
        author_retries=None,
        skip_env_up=True,
        queue=False,
        validation_scope=None,
        update_manifests=None,
        validate_only=False,
        persist_results=None,
        dry_run=False,
        resume_token=None,
    )

    selected_stage_calls: list[str] = []
    executed_stage_names: list[str] = []

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._parse_args",
        lambda: parsed_args,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.load_inference_config",
        lambda *_: config,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._prepare_run_dir",
        lambda *_: tmp_path / "run",
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.load_inference_job_state",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._load_compatibility_seed_state",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.write_inference_job_state",
        lambda *_, **__: None,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._write_summary",
        lambda run_dir, summary: run_dir / "summary.json",
    )

    def fake_select_stage_items_for_run(*, stage: InferenceStageConfig, **__: object):
        selected_stage_calls.append(stage.name)
        if stage.name == "benchmark_planner":
            return [], [], ["benchmark_planner:bp-001"]
        return (
            [
                SimpleNamespace(
                    item=SimpleNamespace(
                        id=f"{stage.name}:item",
                        complexity_level=0,
                        seed_artifact_dir=None,
                    ),
                    raw_row={},
                    family=None,
                )
            ],
            [f"{stage.name}:item"],
            [],
        )

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._select_stage_items_for_run",
        fake_select_stage_items_for_run,
    )

    def fake_execute_stage_batch(*, stage: InferenceStageConfig, **kwargs: object):
        executed_stage_names.append(stage.name)
        return kwargs["pipeline_job_state"], [], False

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._execute_stage_batch",
        fake_execute_stage_batch,
    )

    assert main() == 0
    assert selected_stage_calls == [
        "benchmark_planner",
        "benchmark_plan_reviewer",
        "benchmark_coder",
        "benchmark_reviewer",
    ]
    assert executed_stage_names == [
        "benchmark_plan_reviewer",
        "benchmark_coder",
        "benchmark_reviewer",
    ]


def test_inference_pipeline_benchmark_stage_dry_run_writes_summary() -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "dataset/evals/eval_inference_pipeline.py",
            "--author",
            "--stage",
            "benchmark_planner",
            "--dry-run",
            "--task-id",
            "bp-002",
            "--limit",
            "1",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    summary_path = _extract_summary_path(completed.stdout)
    assert summary_path.exists(), summary_path

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["pipeline_name"] == "application_inference"
    assert payload["mode"] == "application"
    assert payload.get("resume_token") is None
    assert payload["next_resume_token"] == "benchmark_planner:bp-002"
    assert payload["selected_job_ids"] == ["benchmark_planner:bp-002"]
    assert payload["completed_job_ids"] == []
    assert payload["failed_job_ids"] == []
    assert payload["queued_job_ids"] == [
        "benchmark_planner:bp-002->benchmark_plan_reviewer#01",
        "benchmark_planner:bp-002->benchmark_plan_reviewer#02",
        "benchmark_planner:bp-002->benchmark_plan_reviewer#03",
    ]
    assert payload["jobs"][0]["status"] == "queued"


def test_inference_pipeline_resume_token_skips_completed_prefix() -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "dataset/evals/eval_inference_pipeline.py",
            "--author",
            "--stage",
            "benchmark_planner",
            "--dry-run",
            "--task-id",
            "bp-001",
            "--task-id",
            "bp-002",
            "--task-id",
            "bp-003",
            "--resume-token",
            "benchmark_planner:bp-001",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    summary_path = _extract_summary_path(completed.stdout)
    assert summary_path.exists(), summary_path

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["resume_token"] == "benchmark_planner:bp-001"
    assert payload["next_resume_token"] == "benchmark_planner:bp-003"
    assert payload["selected_job_ids"] == [
        "benchmark_planner:bp-002",
        "benchmark_planner:bp-003",
    ]
    assert payload["skipped_job_ids"] == ["benchmark_planner:bp-001"]


def test_inference_pipeline_in_progress_states_are_retryable() -> None:
    states = {
        "benchmark_planner:bp-001": InferenceJobState(
            job_id="benchmark_planner:bp-001",
            stage_name="benchmark_planner",
            agent_name=AgentName.BENCHMARK_PLANNER,
            status=InferenceJobStatus.QUEUED,
            recorded_at="2026-04-23T00:00:00+0000",
        ),
        "benchmark_planner:bp-002": InferenceJobState(
            job_id="benchmark_planner:bp-002",
            stage_name="benchmark_planner",
            agent_name=AgentName.BENCHMARK_PLANNER,
            status=InferenceJobStatus.RUNNING,
            recorded_at="2026-04-23T00:00:00+0000",
        ),
        "benchmark_planner:bp-003": InferenceJobState(
            job_id="benchmark_planner:bp-003",
            stage_name="benchmark_planner",
            agent_name=AgentName.BENCHMARK_PLANNER,
            status=InferenceJobStatus.VALIDATED,
            recorded_at="2026-04-23T00:00:00+0000",
        ),
        "benchmark_planner:bp-004": InferenceJobState(
            job_id="benchmark_planner:bp-004",
            stage_name="benchmark_planner",
            agent_name=AgentName.BENCHMARK_PLANNER,
            status=InferenceJobStatus.REVIEWED,
            recorded_at="2026-04-23T00:00:00+0000",
        ),
    }

    skip_ids = _load_resume_state_skip_ids(states)

    assert "benchmark_planner:bp-001" not in skip_ids
    assert "benchmark_planner:bp-002" not in skip_ids
    assert "benchmark_planner:bp-003" in skip_ids
    assert "benchmark_planner:bp-004" in skip_ids


def test_inference_pipeline_validate_only_skips_copy_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = load_inference_config(ROOT / "inference_config.yaml")
    stage = config.stage("benchmark_plan_reviewer")
    selected_items, _ = _load_stage_items(
        stage=stage,
        families=None,
        task_ids={"bpr-002"},
        levels=None,
        limit=1,
    )
    assert selected_items
    selected = selected_items[0]

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "artifact.txt").write_text("artifact", encoding="utf-8")

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.materialize_seed_workspace",
        lambda **_: SimpleNamespace(workspace_dir=workspace_dir, prompt_text="prompt"),
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.launch_cli_exec",
        lambda *_, **__: 0,
    )

    async def _verify_workspace_for_agent(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            success=True,
            errors=[],
            verification_name="verification",
        )

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.verify_workspace_for_agent",
        _verify_workspace_for_agent,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._copy_workspace_bundle",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("copy-back disabled")),
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._refresh_persisted_bundle_artifacts",
        lambda *_, **__: (_ for _ in ()).throw(
            AssertionError("manifest refresh disabled")
        ),
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._load_compatibility_seed_state",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._write_compatibility_seed_state",
        lambda *_, **__: (_ for _ in ()).throw(
            AssertionError("compatibility refresh disabled")
        ),
    )

    result = _run_workspace_job(
        stage=stage,
        item=selected.item,
        raw_row=selected.raw_row,
        provider_name="codex",
        run_dir=tmp_path,
        persist_results=True,
        validate_only=True,
        update_manifests=False,
    )

    assert result.status.value == "validated"
    assert result.copied_back is False
    assert result.review_passed is False
    assert result.workspace_dir == workspace_dir
    assert _workspace_dir_for_item(tmp_path, stage.name, selected.item.id) == (
        tmp_path / "workspaces" / stage.name / selected.item.id
    )


def test_inference_pipeline_non_persisting_run_skips_copy_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = load_inference_config(ROOT / "inference_config.yaml")
    stage = config.stage("benchmark_plan_reviewer")
    selected_items, _ = _load_stage_items(
        stage=stage,
        families=None,
        task_ids={"bpr-002"},
        levels=None,
        limit=1,
    )
    assert selected_items
    selected = selected_items[0]

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "artifact.txt").write_text("artifact", encoding="utf-8")

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.materialize_seed_workspace",
        lambda **_: SimpleNamespace(workspace_dir=workspace_dir, prompt_text="prompt"),
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.launch_cli_exec",
        lambda *_, **__: 0,
    )

    async def _verify_workspace_for_agent(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            success=True,
            errors=[],
            verification_name="verification",
        )

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.verify_workspace_for_agent",
        _verify_workspace_for_agent,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._copy_workspace_bundle",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("copy-back disabled")),
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._refresh_persisted_bundle_artifacts",
        lambda *_, **__: (_ for _ in ()).throw(
            AssertionError("manifest refresh disabled")
        ),
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._load_compatibility_seed_state",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._write_compatibility_seed_state",
        lambda *_, **__: (_ for _ in ()).throw(
            AssertionError("compatibility refresh disabled")
        ),
    )

    result = _run_workspace_job(
        stage=stage,
        item=selected.item,
        raw_row=selected.raw_row,
        provider_name="codex",
        run_dir=tmp_path,
        persist_results=False,
        validate_only=False,
        update_manifests=False,
    )

    assert result.status.value == "reviewed"
    assert result.copied_back is False
    assert result.review_passed is True
    assert result.validation_passed is True


def test_inference_pipeline_benchmark_coder_persisted_bundle_omits_reviews(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = load_inference_config(ROOT / "inference_config.yaml")
    stage = config.stage("benchmark_coder")
    selected_items, _ = _load_stage_items(
        stage=stage,
        families=None,
        task_ids={"bc-002"},
        levels=None,
        limit=1,
    )
    assert selected_items
    selected = selected_items[0]

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for rel_path in workspace_artifacts_for_agent(AgentName.BENCHMARK_CODER):
        path = workspace_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")
    (workspace_dir / "reviews" / "decision.yaml").parent.mkdir(
        parents=True, exist_ok=True
    )
    (workspace_dir / "reviews" / "decision.yaml").write_text(
        "approved: true\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.ROOT",
        tmp_path,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.materialize_seed_workspace",
        lambda **_: SimpleNamespace(workspace_dir=workspace_dir, prompt_text="prompt"),
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.launch_cli_exec",
        lambda *_, **__: 0,
    )

    async def _verify_workspace_for_agent(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            success=True,
            errors=[],
            verification_name="verification",
        )

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline.verify_workspace_for_agent",
        _verify_workspace_for_agent,
    )
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._refresh_persisted_bundle_artifacts",
        lambda *_, **__: None,
    )
    compatibility_state: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._load_compatibility_seed_state",
        lambda *_: dict(compatibility_state),
    )

    def fake_write_compatibility_seed_state(
        _root: Path, states: dict[str, dict[str, object]]
    ) -> Path:
        compatibility_state.clear()
        compatibility_state.update(states)
        return tmp_path / "task_state.json"

    monkeypatch.setattr(
        "dataset.evals.eval_inference_pipeline._write_compatibility_seed_state",
        fake_write_compatibility_seed_state,
    )

    result = _run_workspace_job(
        stage=stage,
        item=selected.item,
        raw_row=selected.raw_row,
        provider_name="codex",
        run_dir=tmp_path,
        persist_results=True,
        validate_only=False,
        update_manifests=False,
    )

    target_dir = (
        tmp_path
        / "dataset"
        / "data"
        / "seed"
        / "artifacts"
        / "engineer_planner"
        / selected.item.id
    )
    assert result.copied_back is True
    assert result.review_passed is True
    assert result.validation_passed is True
    assert (target_dir / "benchmark_plan.md").exists()
    assert (target_dir / "reviews" / "decision.yaml").exists() is False
    assert compatibility_state[selected.item.id]["last_validation_passed"] is True
    assert compatibility_state[selected.item.id]["last_review_passed"] is True
