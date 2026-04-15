from pathlib import Path

import pytest

from shared.agent_templates import (
    load_common_template_files,
    load_role_template_files,
    load_template_text,
)
from shared.current_role import parse_current_role_manifest
from shared.enums import AgentName
from tests.integration.agent.helpers import load_integration_mock_scenarios


@pytest.mark.integration_p0
def test_common_agent_templates_load_from_shared_templates():
    templates = load_common_template_files()
    assert set(templates) == {
        ".admin/clear_env.py",
        "journal.md",
        "manufacturing_config.yaml",
        "solution_script.py",
        "todo.md",
    }

    shared_root = Path("shared/agent_templates/common")
    assert templates[".admin/clear_env.py"] == (
        shared_root / ".admin/clear_env.py"
    ).read_text(encoding="utf-8")
    assert templates["solution_script.py"] == (
        shared_root / "solution_script.py"
    ).read_text(encoding="utf-8")
    assert templates["todo.md"] == (shared_root / "todo.md").read_text(encoding="utf-8")
    assert templates["journal.md"] == (shared_root / "journal.md").read_text(
        encoding="utf-8"
    )
    assert (
        load_template_text("common/solution_script.py")
        == templates["solution_script.py"]
    )


@pytest.mark.integration_p0
def test_planner_agent_templates_include_retained_evidence_scripts():
    benchmark_templates = load_role_template_files(AgentName.BENCHMARK_PLANNER)
    engineer_templates = load_role_template_files(AgentName.ENGINEER_PLANNER)

    assert set(benchmark_templates) == {
        "benchmark_plan.md",
        "todo.md",
        "benchmark_definition.yaml",
        "benchmark_assembly_definition.yaml",
        "benchmark_plan_evidence_script.py",
    }
    assert set(engineer_templates) == {
        "engineering_plan.md",
        "todo.md",
        "assembly_definition.yaml",
        "benchmark_plan_evidence_script.py",
        "solution_plan_evidence_script.py",
    }


@pytest.mark.integration_p0
def test_template_file_expands_from_shared_agent_templates(tmp_path: Path):
    scenario_dir = tmp_path / "mock_responses"
    scenario_dir.mkdir()
    (scenario_dir / "INT-999.yaml").write_text(
        (
            "transcript:\n"
            "- node: engineer_coder\n"
            "  steps:\n"
            "  - tool_name: write_file\n"
            "    tool_args:\n"
            "      path: solution_script.py\n"
            "      overwrite: true\n"
            "      template_file: common/solution_script.py\n"
            "    expected_observation: success\n"
        ),
        encoding="utf-8",
    )

    scenarios = load_integration_mock_scenarios(scenario_dir)
    step = scenarios["INT-999"]["transcript"][0]["steps"][0]
    assert step["tool_args"]["content"] == (
        Path("shared/agent_templates/common/solution_script.py").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.integration_p0
def test_mock_response_entry_dirs_include_current_role_manifest():
    mock_root = Path("tests/integration/mock_responses")
    entry_dirs = sorted(p for p in mock_root.rglob("entry_*") if p.is_dir())
    assert entry_dirs, "Expected integration mock-response entry directories."

    for entry_dir in entry_dirs:
        role_dir = entry_dir.parent
        agent_name = AgentName(role_dir.name)
        manifest_path = entry_dir / ".manifests" / "current_role.json"
        assert manifest_path.is_file(), f"Missing manifest in {entry_dir}"

        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = parse_current_role_manifest(manifest_text)
        assert manifest.agent_name == agent_name, (
            f"{manifest_path} does not match node role {agent_name.value}"
        )
