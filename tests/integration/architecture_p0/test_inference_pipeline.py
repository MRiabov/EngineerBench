from __future__ import annotations

import json
import re
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

from dataset.evals.eval_inference_pipeline import (
    _load_stage_items,
    _run_workspace_job,
    _workspace_dir_for_item,
)
from evals.logic.inference_pipeline import load_inference_config

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
            "bp-001",
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
    assert payload["next_resume_token"] == "benchmark_planner:bp-001"
    assert payload["selected_job_ids"] == ["benchmark_planner:bp-001"]
    assert payload["completed_job_ids"] == []
    assert payload["failed_job_ids"] == []
    assert payload["queued_job_ids"] == [
        "benchmark_planner:bp-001->benchmark_plan_reviewer#01",
        "benchmark_planner:bp-001->benchmark_plan_reviewer#02",
        "benchmark_planner:bp-001->benchmark_plan_reviewer#03",
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
