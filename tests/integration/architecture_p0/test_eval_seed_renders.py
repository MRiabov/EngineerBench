from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.internal import eval_seed_renders
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName


def _write_minimal_benchmark_fixture(artifact_dir: Path, *, agent: AgentName) -> None:
    benchmark_definition = {
        "objectives": {
            "goal_zone_mm": {"min_mm": [0.0, 0.0, 0.0], "max_mm": [5.0, 5.0, 5.0]},
            "forbid_zones": [],
            "build_zone_mm": {
                "min_mm": [-10.0, -10.0, -10.0],
                "max_mm": [10.0, 10.0, 10.0],
            },
        },
        "benchmark_parts": [
            {
                "part_id": "fixture_block",
                "label": "fixture_block",
                "metadata": {"is_fixed": True, "material_id": "hardwood"},
            }
        ],
        "physics": {"backend": "GENESIS", "compute_target": "auto"},
        "simulation_bounds_mm": {
            "min_mm": [-20.0, -20.0, -20.0],
            "max_mm": [20.0, 20.0, 20.0],
        },
        "payload": {
            "label": "benchmark_payload__box",
            "shape": "box",
            "material_id": "abs",
            "static_randomization": {},
            "start_position_mm": [0.0, 0.0, 0.0],
            "runtime_jitter_mm": [0.0, 0.0, 0.0],
        },
        "constraints": {"max_unit_cost": 1.0, "max_weight_g": 1.0},
    }
    (artifact_dir / "benchmark_definition.yaml").write_text(
        yaml.safe_dump(benchmark_definition, sort_keys=False),
        encoding="utf-8",
    )
    (artifact_dir / "benchmark_script.py").write_text(
        "print('benchmark fixture')\n",
        encoding="utf-8",
    )
    manifests_dir = artifact_dir / ".manifests"
    manifests_dir.mkdir(exist_ok=True)
    (manifests_dir / "current_role.json").write_text(
        current_role_manifest_json(agent),
        encoding="utf-8",
    )


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


def test_benchmark_seed_renders_include_payload_preview_bundle(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "benchmark_reviewer" / "br-test"
    artifact_dir.mkdir(parents=True)
    _write_minimal_benchmark_fixture(artifact_dir, agent=AgentName.BENCHMARK_REVIEWER)

    load_component_calls: list[dict[str, object]] = []
    export_calls: list[dict[str, object]] = []
    render_calls: list[dict[str, object]] = []

    def fake_load_preview_component(artifact_dir, definition, role_name):
        load_component_calls.append(
            {
                "artifact_dir": artifact_dir,
                "definition": definition,
                "role_name": role_name,
            }
        )
        return SimpleNamespace(label="benchmark_fixture")

    def fake_export_preview_scene_bundle(
        component, *, objectives, workspace_root, smoke_test_mode=False
    ):
        export_calls.append(
            {
                "component": component,
                "objectives": objectives,
                "workspace_root": workspace_root,
                "smoke_test_mode": smoke_test_mode,
            }
        )
        return "preview-bundle-base64"

    def fake_render_static_preview(**kwargs):
        render_calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            message=None,
            status_text=None,
            artifacts=SimpleNamespace(),
        )

    def fake_materialize_render_artifacts(_artifacts, output_dir):
        benchmark_bundle = output_dir / "renders" / "benchmark_renders"
        benchmark_bundle.mkdir(parents=True, exist_ok=True)
        (benchmark_bundle / "preview.png").write_bytes(b"benchmark")
        return ["renders/benchmark_renders/preview.png"]

    monkeypatch.setattr(
        eval_seed_renders,
        "_load_preview_component",
        fake_load_preview_component,
    )
    monkeypatch.setattr(
        eval_seed_renders,
        "export_preview_scene_bundle",
        fake_export_preview_scene_bundle,
    )
    monkeypatch.setattr(
        eval_seed_renders, "render_static_preview", fake_render_static_preview
    )
    monkeypatch.setattr(
        eval_seed_renders,
        "materialize_render_artifacts",
        fake_materialize_render_artifacts,
    )

    saved_paths = eval_seed_renders.update_seed_artifact_renders(artifact_dir)

    assert saved_paths == ["renders/benchmark_renders/preview.png"]
    assert len(load_component_calls) == 1
    assert load_component_calls[0]["role_name"] == "benchmark_reviewer"
    assert len(export_calls) == 1
    assert export_calls[0]["objectives"].payload.label == "benchmark_payload__box"
    assert export_calls[0]["workspace_root"].name.startswith("seed-render-bundle-")
    assert len(render_calls) == 1
    assert render_calls[0]["bundle_base64"] == "preview-bundle-base64"
    assert render_calls[0]["script_path"] == "benchmark_script.py"
    assert render_calls[0]["script_content"] == "print('benchmark fixture')\n"


def test_engineer_plan_seed_renders_use_planner_evidence_script(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "engineer_coder" / "ec-test"
    artifact_dir.mkdir(parents=True)

    _write_minimal_benchmark_fixture(artifact_dir, agent=AgentName.ENGINEER_CODER)
    (artifact_dir / "solution_plan_evidence_script.py").write_text(
        "print('planner evidence')\n",
        encoding="utf-8",
    )

    render_calls: list[dict[str, object]] = []
    export_calls: list[dict[str, object]] = []

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

    def fake_export_preview_scene_bundle(
        component, *, objectives, workspace_root, smoke_test_mode=False
    ):
        export_calls.append(
            {
                "component": component,
                "objectives": objectives,
                "workspace_root": workspace_root,
                "smoke_test_mode": smoke_test_mode,
            }
        )
        return "preview-bundle-base64"

    def fake_load_preview_component(artifact_dir, definition, role_name):
        return SimpleNamespace(label="benchmark_fixture")

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
        "export_preview_scene_bundle",
        fake_export_preview_scene_bundle,
    )
    monkeypatch.setattr(
        eval_seed_renders,
        "_load_preview_component",
        fake_load_preview_component,
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
    assert len(export_calls) == 1
    assert export_calls[0]["objectives"].payload.label == "benchmark_payload__box"
    assert export_calls[0]["workspace_root"].name.startswith("seed-render-bundle-")
    assert render_calls[0]["script_path"] == "benchmark_script.py"
    assert render_calls[1]["script_path"] == "solution_plan_evidence_script.py"
    assert render_calls[1]["agent_role"] == "engineer_coder"
    assert (artifact_dir / "renders" / "engineer_plan_renders" / "preview.png").exists()
