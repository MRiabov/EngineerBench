from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from shared.agent_templates import load_seed_starter_template_files
from shared.current_role import parse_current_role_manifest
from shared.enums import AgentName

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "dataset" / "evals" / "materialize_seed_authoring_workspace.py"


def _run_bootstrapper(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_stdout_paths(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        values[key] = value
    return values


@pytest.mark.integration_p0
@pytest.mark.parametrize(
    "agent_name",
    [
        AgentName.BENCHMARK_PLANNER,
        AgentName.ENGINEER_CODER,
    ],
)
def test_seed_authoring_workspace_bootstrapper_materializes_starter_files(
    tmp_path: Path, agent_name: AgentName
) -> None:
    output_dir = tmp_path / agent_name.value
    completed = _run_bootstrapper(
        "--agent",
        agent_name.value,
        "--task-id",
        f"{agent_name.value}-seed-authoring",
        "--output-dir",
        str(output_dir),
    )
    assert completed.returncode == 0, completed.stderr

    stdout_paths = _parse_stdout_paths(completed.stdout)
    workspace_dir = Path(stdout_paths["workspace"])
    prompt_path = Path(stdout_paths["prompt"])

    assert workspace_dir == output_dir.resolve()
    assert prompt_path == workspace_dir / "prompt.md"
    assert prompt_path.exists()

    manifest_path = workspace_dir / ".manifests" / "current_role.json"
    manifest = parse_current_role_manifest(manifest_path.read_text(encoding="utf-8"))
    assert manifest.agent_name == agent_name

    expected_paths = set(load_seed_starter_template_files(agent_name))
    for rel_path in expected_paths:
        assert (workspace_dir / rel_path).exists(), rel_path

    assert (workspace_dir / ".agents" / "skills").exists()
    assert (workspace_dir / ".admin" / "clear_env.py").exists()


@pytest.mark.integration_p0
def test_seed_authoring_workspace_bootstrapper_uses_seed_authoring_temp_root() -> None:
    completed = _run_bootstrapper(
        "--agent",
        AgentName.ENGINEER_CODER.value,
        "--task-id",
        "engineer-coder-seed-authoring",
    )
    assert completed.returncode == 0, completed.stderr

    stdout_paths = _parse_stdout_paths(completed.stdout)
    workspace_dir = Path(stdout_paths["workspace"])
    assert workspace_dir.as_posix().startswith(
        "/tmp/problemologist-evals/seed_authoring/"
    )
    assert workspace_dir.exists()

    manifest_path = workspace_dir / ".manifests" / "current_role.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["agent_name"] == AgentName.ENGINEER_CODER.value


@pytest.mark.integration_p0
def test_seed_authoring_workspace_bootstrapper_rejects_agents_without_starter_files() -> (
    None
):
    completed = _run_bootstrapper(
        "--agent",
        AgentName.SKILL_AGENT.value,
    )
    assert completed.returncode != 0
    assert "does not have a seed starter set" in completed.stderr
