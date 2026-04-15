from __future__ import annotations

from pathlib import Path

from shared.enums import AgentName

AGENT_TEMPLATES_ROOT = Path(__file__).resolve().parent
COMMON_TEMPLATES_ROOT = AGENT_TEMPLATES_ROOT / "common"
CODEX_TEMPLATES_ROOT = AGENT_TEMPLATES_ROOT / "codex"
TEMPLATE_REPOS_ROOT = (
    Path(__file__).resolve().parents[2] / "shared" / "assets" / "template_repos"
)
ROLE_TEMPLATE_FILES: dict[AgentName, tuple[str, ...]] = {
    AgentName.BENCHMARK_PLANNER: (
        "benchmark_plan.md",
        "todo.md",
        "benchmark_definition.yaml",
        "benchmark_assembly_definition.yaml",
        "benchmark_plan_evidence_script.py",
    ),
    AgentName.ENGINEER_PLANNER: (
        "engineering_plan.md",
        "todo.md",
        "assembly_definition.yaml",
        "benchmark_plan_evidence_script.py",
        "solution_plan_evidence_script.py",
    ),
}


def _load_template_tree(template_root: Path) -> dict[str, str]:
    if not template_root.exists():
        raise FileNotFoundError(f"Template directory not found: {template_root}")
    if not template_root.is_dir():
        raise ValueError(f"Template path must be a directory: {template_root}")

    merged: dict[str, str] = {}
    for src_path in sorted(p for p in template_root.rglob("*") if p.is_file()):
        if "__pycache__" in src_path.parts or src_path.suffix in {".pyc", ".pyo"}:
            continue
        rel_path = src_path.relative_to(template_root).as_posix()
        merged[rel_path] = src_path.read_text(encoding="utf-8")
    return merged


def resolve_template_path(template_file: str | Path) -> Path:
    """Resolve a template-relative path safely inside shared/agent_templates."""
    candidate = Path(template_file)
    resolved = (
        candidate if candidate.is_absolute() else AGENT_TEMPLATES_ROOT / candidate
    ).resolve()
    root = AGENT_TEMPLATES_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Template path escapes shared/agent_templates: {template_file}"
        ) from exc

    if not resolved.is_file():
        raise FileNotFoundError(f"Template file not found: {template_file}")
    return resolved


def load_template_text(template_file: str | Path) -> str:
    """Read template text from shared/agent_templates."""
    content = resolve_template_path(template_file).read_text(encoding="utf-8")
    resolved = Path(template_file)
    if resolved.as_posix().endswith("common/solution_script.py"):
        return _render_registry_tied_solution_script(content)
    return content


def load_common_template_files() -> dict[str, str]:
    """Load the shared boilerplate starter files."""
    return _load_template_tree(COMMON_TEMPLATES_ROOT)


def load_template_repo_files(template_repo: str | Path) -> dict[str, str]:
    """Load a starter template repo under shared/assets/template_repos."""
    repo_root = TEMPLATE_REPOS_ROOT / Path(template_repo)
    return _load_template_tree(repo_root)


def load_role_template_files(agent_name: AgentName) -> dict[str, str]:
    """Load the role-specific starter files for a planner workspace."""
    role_template_map: dict[AgentName, str] = {
        AgentName.BENCHMARK_PLANNER: "benchmark_generator",
        AgentName.ENGINEER_PLANNER: "engineer",
    }
    template_repo = role_template_map.get(agent_name)
    file_names = ROLE_TEMPLATE_FILES.get(agent_name)
    if template_repo is None or file_names is None:
        return {}

    repo_root = TEMPLATE_REPOS_ROOT / template_repo
    if not repo_root.exists():
        raise FileNotFoundError(f"Template directory not found: {repo_root}")
    if not repo_root.is_dir():
        raise ValueError(f"Template path must be a directory: {repo_root}")

    loaded: dict[str, str] = {}
    for rel_path in file_names:
        src_path = repo_root / rel_path
        if not src_path.is_file():
            raise FileNotFoundError(f"Template file not found: {src_path}")
        loaded[rel_path] = src_path.read_text(encoding="utf-8")
    return loaded


def load_codex_template_files() -> dict[str, str]:
    """Load Codex-only helper scripts copied into debug workspaces."""
    return _load_template_tree(CODEX_TEMPLATES_ROOT)


def _render_registry_tied_solution_script(content: str) -> str:
    """Return the starter script unchanged."""
    return content
