#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BACKUP_ROOT = "refs/codex/pre-commit-backups"
LATEST_REF = f"{BACKUP_ROOT}/latest"
HISTORY_PREFIX = f"{BACKUP_ROOT}/history/"
MAX_BACKUPS = 200
COMMITTER_NAME = "Codex Pre-commit Backup"
COMMITTER_EMAIL = "codex@local"


def run_git(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def has_changes(repo_root: Path) -> bool:
    status = run_git(
        [
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            "--ignore-submodules=dirty",
        ],
        cwd=repo_root,
    )
    return bool(status)


def create_snapshot(repo_root: Path) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    with tempfile.NamedTemporaryFile(
        prefix="precommit-backup-index-", delete=False
    ) as tmp:
        index_path = tmp.name

    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = index_path
    env["GIT_AUTHOR_NAME"] = COMMITTER_NAME
    env["GIT_AUTHOR_EMAIL"] = COMMITTER_EMAIL
    env["GIT_COMMITTER_NAME"] = COMMITTER_NAME
    env["GIT_COMMITTER_EMAIL"] = COMMITTER_EMAIL
    env["GIT_AUTHOR_DATE"] = now.isoformat()
    env["GIT_COMMITTER_DATE"] = now.isoformat()

    try:
        run_git(["read-tree", "--empty"], cwd=repo_root, env=env)
        run_git(["add", "-A", "--", "."], cwd=repo_root, env=env)
        tree = run_git(["write-tree"], cwd=repo_root, env=env)

        commit_args = ["commit-tree", tree, "-m", f"pre-commit backup {stamp}"]
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=repo_root,
            text=True,
            capture_output=True,
        )
        if head.returncode == 0 and head.stdout.strip():
            commit_args[2:2] = ["-p", head.stdout.strip()]

        commit = run_git(commit_args, cwd=repo_root, env=env)
        history_ref = f"{HISTORY_PREFIX}{stamp}-{commit[:12]}"
        run_git(
            [
                "update-ref",
                "--create-reflog",
                "-m",
                f"pre-commit backup {stamp}",
                history_ref,
                commit,
            ],
            cwd=repo_root,
            env=env,
        )
        run_git(
            [
                "update-ref",
                "--create-reflog",
                "-m",
                f"pre-commit backup {stamp}",
                LATEST_REF,
                commit,
            ],
            cwd=repo_root,
            env=env,
        )
        history_refs = run_git(
            [
                "for-each-ref",
                "--format=%(refname)",
                "--sort=refname",
                HISTORY_PREFIX,
            ],
            cwd=repo_root,
            env=env,
        ).splitlines()
        excess = len(history_refs) - MAX_BACKUPS
        if excess > 0:
            for refname in history_refs[:excess]:
                run_git(
                    ["update-ref", "-d", refname],
                    cwd=repo_root,
                    env=env,
                )
        return commit, history_ref
    finally:
        try:
            Path(index_path).unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    repo_root = Path(run_git(["rev-parse", "--show-toplevel"], cwd=Path.cwd()))

    if not has_changes(repo_root):
        return 0

    commit, history_ref = create_snapshot(repo_root)
    print(
        "pre-commit backup saved to "
        f"{LATEST_REF} and {history_ref} ({commit[:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
