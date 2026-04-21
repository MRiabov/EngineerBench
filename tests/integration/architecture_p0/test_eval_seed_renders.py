from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.internal import eval_seed_renders
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName


@pytest.mark.parametrize(
    ("agent", "expected_bundles"),
    [
        (AgentName.BENCHMARK_PLANNER, []),
        (AgentName.BENCHMARK_PLAN_REVIEWER, ["benchmark_renders"]),
        (AgentName.BENCHMARK_CODER, ["benchmark_renders"]),
        (AgentName.BENCHMARK_REVIEWER, ["benchmark_renders"]),
        (AgentName.ENGINEER_PLANNER, ["benchmark_renders"]),
        (
            AgentName.ENGINEER_PLAN_REVIEWER,
            ["benchmark_renders", "engineer_plan_renders"],
        ),
        (
            AgentName.ENGINEER_CODER,
            ["benchmark_renders", "engineer_plan_renders"],
        ),
        (
            AgentName.ENGINEER_EXECUTION_REVIEWER,
            [
                "benchmark_renders",
                "engineer_plan_renders",
                "final_solution_submission_renders",
            ],
        ),
    ],
)
def test_seed_render_bundle_prefixes_cover_all_roles(agent, expected_bundles):
    assert eval_seed_renders._seed_render_bundle_names(agent.value) == expected_bundles


def test_seed_render_bundle_prefixes_match_visual_inspection_config():
    cfg = yaml.safe_load(Path("config/agents_config.yaml").read_text(encoding="utf-8"))
    agents = cfg["agents"]

    expected_bundles_by_agent = {
        AgentName.BENCHMARK_PLANNER: [],
        AgentName.BENCHMARK_PLAN_REVIEWER: ["benchmark_renders"],
        AgentName.BENCHMARK_CODER: ["benchmark_renders"],
        AgentName.BENCHMARK_REVIEWER: ["benchmark_renders"],
        AgentName.ENGINEER_PLANNER: ["benchmark_renders"],
        AgentName.ENGINEER_PLAN_REVIEWER: [
            "benchmark_renders",
            "engineer_plan_renders",
        ],
        AgentName.ENGINEER_CODER: [
            "benchmark_renders",
            "engineer_plan_renders",
        ],
        AgentName.ENGINEER_EXECUTION_REVIEWER: [
            "benchmark_renders",
            "engineer_plan_renders",
            "final_solution_submission_renders",
        ],
    }

    for agent, expected_bundles in expected_bundles_by_agent.items():
        assert eval_seed_renders._seed_render_bundle_names(agent.value) == (
            expected_bundles
        )
        assert (
            agents[agent.value]["visual_inspection"]["entry_expects_render_buckets"]
            == expected_bundles
        )


def test_engineer_plan_seed_renders_use_planner_evidence_script(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "engineer_coder" / "ec-test"
    artifact_dir.mkdir(parents=True)

    (artifact_dir / "solution_plan_evidence_script.py").write_text(
        "print('planner evidence')\n",
        encoding="utf-8",
    )
    manifests_dir = artifact_dir / ".manifests"
    manifests_dir.mkdir()
    (manifests_dir / "current_role.json").write_text(
        current_role_manifest_json(AgentName.ENGINEER_CODER),
        encoding="utf-8",
    )

    render_calls: list[dict[str, object]] = []

    def fake_render_static_preview(**kwargs):
        render_calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            message=None,
            status_text=None,
            artifacts=SimpleNamespace(),
        )

    def fake_bundle_workspace_base64(_workspace_root):
        return "bundle-base64"

    def fake_materialize_render_artifacts(_artifacts, output_dir):
        benchmark_bundle = output_dir / "renders" / "benchmark_renders"
        benchmark_bundle.mkdir(parents=True, exist_ok=True)
        (benchmark_bundle / "preview.png").write_bytes(b"benchmark")

        engineer_bundle = output_dir / "renders" / "engineer_plan_renders"
        engineer_bundle.mkdir(parents=True, exist_ok=True)
        (engineer_bundle / "preview.png").write_bytes(b"engineer")

        return [
            "renders/benchmark_renders/preview.png",
            "renders/engineer_plan_renders/preview.png",
        ]

    def fake_normalize_render_manifest(
        *,
        render_paths,
        workspace_root,
        episode_id,
        worker_session_id,
        bundle_path,
        source_script_sha256,
    ):
        return SimpleNamespace(model_dump_json=lambda indent=2: "{}")

    monkeypatch.setattr(
        eval_seed_renders, "render_static_preview", fake_render_static_preview
    )
    monkeypatch.setattr(
        eval_seed_renders, "bundle_workspace_base64", fake_bundle_workspace_base64
    )
    monkeypatch.setattr(
        eval_seed_renders,
        "materialize_render_artifacts",
        fake_materialize_render_artifacts,
    )
    monkeypatch.setattr(
        eval_seed_renders, "normalize_render_manifest", fake_normalize_render_manifest
    )

    saved_paths = eval_seed_renders.update_seed_artifact_renders(artifact_dir)

    assert saved_paths
    assert render_calls[0]["script_path"] == "benchmark_script.py"
    assert render_calls[1]["script_path"] == "solution_plan_evidence_script.py"
    assert render_calls[1]["agent_role"] == "engineer_coder"
    assert (artifact_dir / "renders" / "engineer_plan_renders" / "preview.png").exists()
