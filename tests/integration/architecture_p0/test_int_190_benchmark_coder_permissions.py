from pathlib import Path

import pytest
import yaml

from shared.workers.filesystem.policy import FilesystemPolicy


@pytest.mark.integration
@pytest.mark.integration_p0
@pytest.mark.int_id("INT-190")
def test_int_190_benchmark_coder_filesystem_scope_matches_workspace_contract():
    cfg = yaml.safe_load(Path("config/agents_config.yaml").read_text(encoding="utf-8"))
    role_cfg = cfg["agents"]["benchmark_coder"]["filesystem_permissions"]

    read_allow = set(role_cfg["read"]["allow"])
    write_allow = set(role_cfg["write"]["allow"])

    assert "**/*.py" in read_allow
    assert "**/*.py" in write_allow

    for required in {
        ".agents/skills/**",
        "utils/**",
        "benchmark_plan.md",
        "todo.md",
        "journal.md",
        "benchmark_definition.yaml",
        "benchmark_assembly_definition.yaml",
        "benchmark_script.py",
        "validation_results.json",
        "simulation_result.json",
        "scene.json",
        "renders/**",
    }:
        assert required in read_allow, f"benchmark_coder missing read scope {required}"

    assert "benchmark_script.py" in write_allow
    assert "script.py" not in read_allow
    assert "script.py" not in write_allow

    engineer_role_cfg = cfg["agents"]["engineer_coder"]["filesystem_permissions"]
    engineer_read_allow = set(engineer_role_cfg["read"]["allow"])
    engineer_write_allow = set(engineer_role_cfg["write"]["allow"])
    assert "solution_script.py" in engineer_read_allow
    assert "benchmark_script.py" in engineer_read_allow
    assert "solution_script.py" in engineer_write_allow
    assert "script.py" not in engineer_read_allow
    assert "script.py" not in engineer_write_allow

    for required in {"/", "."}:
        assert required in read_allow, (
            f"benchmark_coder missing workspace-root orientation scope {required}"
        )

    for forbidden in {"config/**", "shared", "shared/**"}:
        assert forbidden not in read_allow, (
            "benchmark_coder must stay within workspace artifacts and skills, "
            f"not repo-wide scope: found {forbidden}"
        )


@pytest.mark.integration
@pytest.mark.integration_p0
@pytest.mark.int_id("INT-190")
def test_int_190_unit_eval_allowlists_are_explicit_and_reviewer_driven():
    cfg = yaml.safe_load(Path("config/agents_config.yaml").read_text(encoding="utf-8"))
    agents = cfg["agents"]

    benchmark_coder_allowlist = set(
        agents["benchmark_coder"]["allowed_during_unit_eval"]
    )
    assert benchmark_coder_allowlist == {
        "benchmark_coder",
        "benchmark_reviewer",
    }

    engineer_coder_allowlist = set(agents["engineer_coder"]["allowed_during_unit_eval"])
    assert engineer_coder_allowlist == {
        "engineer_coder",
        "engineer_execution_reviewer",
    }

    benchmark_planner_allowlist = set(
        agents["benchmark_planner"]["allowed_during_unit_eval"]
    )
    assert benchmark_planner_allowlist == {
        "benchmark_planner",
        "benchmark_plan_reviewer",
    }

    engineer_planner_allowlist = set(
        agents["engineer_planner"]["allowed_during_unit_eval"]
    )
    assert engineer_planner_allowlist == {
        "engineer_planner",
        "engineer_plan_reviewer",
    }
    assert agents["engineer_planner"]["visual_inspection"]["required"] is True
    assert agents["engineer_planner"]["visual_inspection"][
        "entry_expects_render_buckets"
    ] == ["benchmark_renders"]
    assert (
        agents["benchmark_planner"]["visual_inspection"]["entry_expects_render_buckets"]
        == []
    )

    expected_visual_buckets = {
        "benchmark_planner": [],
        "benchmark_plan_reviewer": ["benchmark_renders"],
        "benchmark_coder": ["benchmark_renders"],
        "benchmark_reviewer": ["benchmark_renders"],
        "engineer_plan_reviewer": [
            "benchmark_renders",
            "engineer_plan_renders",
        ],
        "engineer_coder": [
            "benchmark_renders",
            "engineer_plan_renders",
        ],
        "engineer_execution_reviewer": [
            "benchmark_renders",
            "engineer_plan_renders",
            "final_solution_submission_renders",
        ],
    }
    for role, expected_buckets in expected_visual_buckets.items():
        assert agents[role]["visual_inspection"]["entry_expects_render_buckets"] == (
            expected_buckets
        )

    engineer_execution_reviewer_allowlist = set(
        agents["engineer_execution_reviewer"]["allowed_during_unit_eval"]
    )
    assert engineer_execution_reviewer_allowlist == {
        "engineer_coder",
        "engineer_execution_reviewer",
    }


@pytest.mark.integration
@pytest.mark.integration_p0
@pytest.mark.int_id("INT-190")
def test_int_190_agent_execution_timeouts_are_role_specific():
    cfg = yaml.safe_load(Path("config/agents_config.yaml").read_text(encoding="utf-8"))
    execution_agents = cfg["execution"]["agents"]

    assert execution_agents["engineer_coder"]["timeout_seconds"] == 1000
    assert execution_agents["benchmark_coder"]["timeout_seconds"] == 450
    assert execution_agents["engineer_plan_reviewer"]["timeout_seconds"] == 90
    assert execution_agents["benchmark_reviewer"]["timeout_seconds"] == 90
    assert execution_agents["engineer_execution_reviewer"]["timeout_seconds"] == 90


@pytest.mark.integration
@pytest.mark.integration_p0
@pytest.mark.int_id("INT-190")
def test_int_190_benchmark_solvability_threshold_is_configurable():
    cfg = yaml.safe_load(Path("config/agents_config.yaml").read_text(encoding="utf-8"))

    assert cfg["benchmark_solvability"]["minimum_payload_to_goal_angle_deg"] == 25.0


@pytest.mark.integration
@pytest.mark.integration_p0
@pytest.mark.int_id("INT-190")
@pytest.mark.parametrize(
    ("render_buckets", "expected_message"),
    [
        (None, "entry_expects_render_buckets"),
        (["benchmark_renders", "  "], "blank entries"),
    ],
)
def test_int_190_render_bucket_expectations_are_fail_closed(
    tmp_path: Path,
    render_buckets,
    expected_message: str,
):
    cfg = yaml.safe_load(Path("config/agents_config.yaml").read_text(encoding="utf-8"))
    cfg["agents"]["benchmark_coder"]["visual_inspection"][
        "entry_expects_render_buckets"
    ] = render_buckets
    config_path = tmp_path / "agents_config.yaml"
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_message):
        FilesystemPolicy(config_path=config_path)


@pytest.mark.integration
@pytest.mark.integration_p0
@pytest.mark.int_id("INT-190")
def test_int_190_bug_report_mode_gates_workspace_root_bug_report_write(
    tmp_path: Path,
):
    cfg = yaml.safe_load(Path("config/agents_config.yaml").read_text(encoding="utf-8"))
    cfg.setdefault("bug_reports", {})["enabled"] = False
    disabled_config_path = tmp_path / "agents_config.disabled.yaml"
    disabled_config_path.write_text(
        yaml.safe_dump(cfg, sort_keys=False),
        encoding="utf-8",
    )
    disabled_policy = FilesystemPolicy(config_path=disabled_config_path)
    assert (
        disabled_policy.check_permission("benchmark_coder", "write", "bug_report.md")
        is False
    )

    cfg.setdefault("bug_reports", {})["enabled"] = True
    enabled_config_path = tmp_path / "agents_config.yaml"
    enabled_config_path.write_text(
        yaml.safe_dump(cfg, sort_keys=False),
        encoding="utf-8",
    )
    enabled_policy = FilesystemPolicy(config_path=enabled_config_path)

    assert enabled_policy.check_permission("benchmark_coder", "write", "bug_report.md")
    assert enabled_policy.check_permission(
        "engineer_execution_reviewer", "write", "bug_report.md"
    )
    assert not enabled_policy.check_permission(
        "benchmark_coder", "write", "notes/bug_report.md"
    )
