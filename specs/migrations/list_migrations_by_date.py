#!/usr/bin/env python3
"""List migration docs sorted by last git edit time.

The script reads machine-readable YAML frontmatter when present and falls back
to legacy body detection only for older docs that have not been updated yet.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

import yaml

ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("benchmark_planner", re.compile(r"\bbenchmark[\s_-]*planner\b", re.IGNORECASE)),
    (
        "benchmark_plan_reviewer",
        re.compile(r"\bbenchmark[\s_-]*plan[\s_-]*reviewer\b", re.IGNORECASE),
    ),
    ("benchmark_coder", re.compile(r"\bbenchmark[\s_-]*coder\b", re.IGNORECASE)),
    ("benchmark_reviewer", re.compile(r"\bbenchmark[\s_-]*reviewer\b", re.IGNORECASE)),
    ("engineer_planner", re.compile(r"\bengineer[\s_-]*planner\b", re.IGNORECASE)),
    (
        "engineer_plan_reviewer",
        re.compile(r"\bengineer[\s_-]*plan[\s_-]*reviewer\b", re.IGNORECASE),
    ),
    ("engineer_coder", re.compile(r"\bengineer[\s_-]*coder\b", re.IGNORECASE)),
    (
        "engineer_execution_reviewer",
        re.compile(r"\bengineer[\s_-]*execution[\s_-]*reviewer\b", re.IGNORECASE),
    ),
    (
        "electronics_planner",
        re.compile(r"\belectronics[\s_-]*planner\b", re.IGNORECASE),
    ),
    (
        "electronics_reviewer",
        re.compile(r"\belectronics[\s_-]*reviewer\b", re.IGNORECASE),
    ),
]


@dataclass(frozen=True)
class MigrationRecord:
    path: Path
    edited_at: datetime
    agents: tuple[str, ...]


def split_markdown_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    frontmatter_end = text.find("\n---\n", 4)
    if frontmatter_end == -1:
        return {}, text
    raw_frontmatter = text[4:frontmatter_end]
    frontmatter = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError("Migration frontmatter must be a mapping")
    body = text[frontmatter_end + len("\n---\n") :]
    return frontmatter, body


def repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip())


def git_last_edit_timestamp(root: Path, path: Path) -> datetime | None:
    relative = path.relative_to(root)
    completed = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%ct", "--", str(relative)],
        check=False,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC).astimezone()


def parse_bound(value: str, *, is_since: bool) -> datetime:
    raw = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        if len(raw) == 10:
            parsed = datetime.combine(parsed.date(), time.min)
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    if len(raw) == 10:
        parsed = parsed.replace(
            hour=0 if is_since else 23,
            minute=0 if is_since else 59,
            second=0 if is_since else 59,
            microsecond=0 if is_since else 999999,
        )
    return parsed.astimezone()


def normalize_agent_token(token: str) -> str | None:
    cleaned = re.sub(r"[^a-z0-9]+", "_", token.strip().lower()).strip("_")
    return cleaned or None


def split_agent_list(raw: str) -> tuple[str, ...]:
    parts = re.split(r",|;|/|\band\b", raw, flags=re.IGNORECASE)
    normalized: list[str] = []
    for part in parts:
        token = normalize_agent_token(part)
        if token and token not in normalized:
            normalized.append(token)
    return tuple(normalized)


def normalize_frontmatter_agents(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return split_agent_list(value)
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            token = normalize_agent_token(item)
            if token and token not in normalized:
                normalized.append(token)
        return tuple(normalized)
    raise ValueError("Migration frontmatter agents_affected must be a list or string")


def detect_agents(text: str) -> tuple[str, ...]:
    frontmatter, body = split_markdown_frontmatter(text)
    agents = normalize_frontmatter_agents(frontmatter.get("agents_affected"))
    if agents:
        return agents

    found: list[str] = []
    for role, pattern in ROLE_PATTERNS:
        if pattern.search(body):
            found.append(role)
    return tuple(found)


def list_migration_docs(root: Path) -> Iterable[Path]:
    migrations_dir = root / "specs" / "migrations"
    for path in sorted(migrations_dir.rglob("*.md")):
        if path.name == "migrations-README.md":
            continue
        yield path


def load_records(root: Path) -> list[MigrationRecord]:
    records: list[MigrationRecord] = []
    for path in list_migration_docs(root):
        edited_at = git_last_edit_timestamp(root, path)
        if edited_at is None:
            continue
        text = path.read_text(encoding="utf-8")
        records.append(
            MigrationRecord(
                path=path.relative_to(root),
                edited_at=edited_at,
                agents=detect_agents(text),
            )
        )
    return records


def filter_records(
    records: Iterable[MigrationRecord],
    *,
    since: datetime | None,
    until: datetime | None,
) -> list[MigrationRecord]:
    filtered: list[MigrationRecord] = []
    for record in records:
        if since is not None and record.edited_at < since:
            continue
        if until is not None and record.edited_at > until:
            continue
        filtered.append(record)
    return filtered


def format_record(record: MigrationRecord) -> str:
    agents = ", ".join(record.agents) if record.agents else "[]"
    if record.agents:
        agents = f"[{agents}]"
    return f"{record.edited_at:%d-%m-%Y %H:%M} - {record.path.as_posix()}, agents affected: {agents}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List migration docs sorted by last git edit time.",
    )
    parser.add_argument(
        "--since",
        help="Only include docs edited on or after this ISO date or datetime.",
    )
    parser.add_argument(
        "--until",
        help="Only include docs edited on or before this ISO date or datetime.",
    )
    parser.add_argument(
        "--ascending",
        action="store_true",
        help="Sort oldest-first instead of newest-first.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = repo_root()

    since = parse_bound(args.since, is_since=True) if args.since else None
    until = parse_bound(args.until, is_since=False) if args.until else None

    records = filter_records(load_records(root), since=since, until=until)
    records.sort(
        key=lambda record: (record.edited_at, record.path.as_posix()),
        reverse=not args.ascending,
    )

    print("edited:")
    for record in records:
        print(format_record(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
