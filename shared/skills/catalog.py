from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.enums import AgentName

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / ".agents" / "skills"
SKILLS_CONFIG_PATH = ROOT / "config" / "skills_config.yaml"
SKILL_OVERLAY_ENV = "PROBLEMOLOGIST_SKILL_OVERLAY_ROOT"


class SkillProjectionPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    is_for_worker_agents: bool = True
    project_to_agents: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("project_to_agents", mode="before")
    @classmethod
    def _normalize_project_to_agents(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("project_to_agents must be a sequence of strings")
        normalized: list[str] = []
        for agent_name in value:
            normalized_name = str(agent_name).strip()
            if not normalized_name:
                continue
            normalized.append(AgentName(normalized_name).value)
        return tuple(normalized)


def _normalize_skill_root(root: Path | None) -> Path:
    if root is None:
        return SKILL_ROOT
    return root.expanduser().resolve()


def _skill_description(skill_path: Path) -> str:
    content = skill_path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError(f"Skill file missing YAML frontmatter: {skill_path}")
    frontmatter_end = content.find("\n---\n", 4)
    if frontmatter_end == -1:
        raise ValueError(f"Skill file frontmatter not terminated: {skill_path}")
    frontmatter = yaml.safe_load(content[4:frontmatter_end]) or {}
    description = str(frontmatter.get("description", "")).strip()
    if not description:
        raise ValueError(f"Skill file missing description: {skill_path}")
    return description


def load_skills_projection_config(
    *, config_path: Path | None = None
) -> dict[str, SkillProjectionPolicy]:
    """Load worker projection policy keyed by skill directory name."""

    path = (config_path or SKILLS_CONFIG_PATH).expanduser().resolve()
    if not path.exists():
        return {}

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Skill projection config must be a mapping: {path}")

    policies: dict[str, SkillProjectionPolicy] = {}
    for skill_name, policy in raw.items():
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise ValueError(f"Invalid skill projection key in {path}: {skill_name!r}")
        normalized_name = skill_name.strip()
        if policy is None:
            policies[normalized_name] = SkillProjectionPolicy()
        elif isinstance(policy, dict):
            policies[normalized_name] = SkillProjectionPolicy.model_validate(policy)
        elif isinstance(policy, bool):
            policies[normalized_name] = SkillProjectionPolicy(
                is_for_worker_agents=policy
            )
        else:
            raise ValueError(
                f"Invalid skill projection policy for {normalized_name} in {path}"
            )
    return policies


def skill_is_for_worker_agents(
    skill_name: str, *, config_path: Path | None = None
) -> bool:
    """Return whether a skill should be projected into worker-facing runtimes."""

    policy = load_skills_projection_config(config_path=config_path).get(skill_name)
    if policy is None:
        return True
    return bool(policy.is_for_worker_agents or policy.project_to_agents)


def skill_is_projected_to_agent(
    skill_name: str,
    agent_name: str,
    *,
    config_path: Path | None = None,
) -> bool:
    """Return whether a skill should be copied into a specific agent workspace."""

    policy = load_skills_projection_config(config_path=config_path).get(skill_name)
    if policy is None:
        return True
    normalized_agent_name = str(agent_name).strip()
    if policy.project_to_agents:
        return normalized_agent_name in policy.project_to_agents
    return bool(policy.is_for_worker_agents)


def _iter_skill_catalog_entries_from_roots(
    canonical_root: str, overlay_root: str | None
) -> tuple[tuple[str, str], ...]:
    roots: list[Path] = []
    if overlay_root:
        overlay_path = Path(overlay_root).expanduser().resolve()
        if overlay_path.exists():
            roots.append(overlay_path)
    canonical_path = Path(canonical_root).expanduser().resolve()
    if canonical_path.exists():
        roots.append(canonical_path)

    entries: list[tuple[str, str]] = []
    seen_skill_names: set[str] = set()
    for skill_root in roots:
        for skill_path in sorted(skill_root.glob("*/SKILL.md")):
            if not skill_path.is_file():
                continue
            skill_name = skill_path.parent.name
            if skill_name in seen_skill_names:
                continue
            entries.append((skill_name, _skill_description(skill_path)))
            seen_skill_names.add(skill_name)
    return tuple(entries)


def iter_skill_catalog_entries(
    *,
    overlay_root: Path | None = None,
    canonical_root: Path | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return active skill names and descriptions from `SKILL.md` files.

    When an overlay root is present, it is resolved first and takes precedence
    over the checked-in canonical skill tree.
    """

    overlay_root_value = overlay_root
    if overlay_root_value is None:
        env_overlay_root = os.getenv(SKILL_OVERLAY_ENV)
        if env_overlay_root:
            overlay_root_value = Path(env_overlay_root)

    return _iter_skill_catalog_entries_from_roots(
        str(_normalize_skill_root(canonical_root)),
        str(_normalize_skill_root(overlay_root_value)) if overlay_root_value else None,
    )


def resolve_skill_file(
    skill_name: str,
    *,
    overlay_root: Path | None = None,
    canonical_root: Path | None = None,
) -> Path | None:
    """Resolve a skill file from the active overlay first, then canonical."""

    roots: list[Path] = []
    overlay_root_value = overlay_root
    if overlay_root_value is None:
        env_overlay_root = os.getenv(SKILL_OVERLAY_ENV)
        if env_overlay_root:
            overlay_root_value = Path(env_overlay_root)
    if overlay_root_value is not None:
        roots.append(_normalize_skill_root(overlay_root_value))
    roots.append(_normalize_skill_root(canonical_root))

    for skill_root in roots:
        candidate = skill_root / skill_name / "SKILL.md"
        if candidate.is_file():
            return candidate
    return None


def resolve_skill_tree_root(
    *,
    overlay_root: Path | None = None,
    canonical_root: Path | None = None,
) -> Path:
    """Return the active skill-tree root, preferring the overlay if present."""

    overlay_root_value = overlay_root
    if overlay_root_value is None:
        env_overlay_root = os.getenv(SKILL_OVERLAY_ENV)
        if env_overlay_root:
            overlay_root_value = Path(env_overlay_root)

    if overlay_root_value is not None:
        overlay_path = _normalize_skill_root(overlay_root_value)
        if overlay_path.exists():
            return overlay_path

    canonical_path = _normalize_skill_root(canonical_root)
    if canonical_path.exists():
        return canonical_path

    return canonical_path


def build_skill_catalog_lines(
    *,
    overlay_root: Path | None = None,
    canonical_root: Path | None = None,
) -> tuple[str, ...]:
    lines = ["Available skills you can read:"]
    active_overlay_root = overlay_root
    if active_overlay_root is None:
        env_overlay_root = os.getenv(SKILL_OVERLAY_ENV)
        if env_overlay_root:
            active_overlay_root = Path(env_overlay_root)
    if active_overlay_root is not None:
        lines.append(
            f"- session overlay first: `{_normalize_skill_root(active_overlay_root)}`"
        )
    for skill_name, description in iter_skill_catalog_entries(
        overlay_root=active_overlay_root,
        canonical_root=canonical_root,
    ):
        display_path = f".agents/skills/{skill_name}/SKILL.md"
        lines.append(f"- `{display_path}`: {description}")
    return tuple(lines)
