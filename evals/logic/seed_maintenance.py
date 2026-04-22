from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from shared.agent_templates import load_seed_starter_template_files
from shared.enums import AgentName
from shared.git_utils import repo_revision

_PLAN_REVIEW_MANIFEST_NAMES = {
    "benchmark_plan_review_manifest.json",
    "engineering_plan_review_manifest.json",
}

_SEED_REVIEW_MANIFEST_NAMES = {
    ".manifests/benchmark_review_manifest.json",
    ".manifests/engineering_execution_handoff_manifest.json",
}


def refresh_plan_review_manifest_hashes(
    artifact_dir: Path, *, fix: bool = False
) -> list[Path]:
    """Refresh deterministic artifact hashes in seeded plan-review manifests."""

    updated_manifests: list[Path] = []

    for manifest_path in sorted(artifact_dir.rglob("*.json")):
        if manifest_path.name not in _PLAN_REVIEW_MANIFEST_NAMES:
            continue

        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            continue

        artifact_hashes = manifest.get("artifact_hashes")
        if not isinstance(artifact_hashes, dict) or not artifact_hashes:
            continue

        updated_hashes = dict(artifact_hashes)
        changed = False
        for rel_path, expected_hash in artifact_hashes.items():
            file_path = artifact_dir / rel_path
            if not file_path.exists():
                continue

            actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                updated_hashes[rel_path] = actual_hash
                changed = True

        if not changed:
            continue

        updated_manifests.append(manifest_path)
        if fix:
            manifest["artifact_hashes"] = updated_hashes
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
            )

    return updated_manifests


def refresh_render_manifest_revisions(
    artifact_dir: Path, *, fix: bool = False
) -> list[Path]:
    """Refresh deterministic revision fields in seeded render manifests."""

    updated_manifests: list[Path] = []
    current_revision = repo_revision(Path(__file__).resolve().parents[2])
    if current_revision is None:
        return updated_manifests

    for manifest_path in sorted(artifact_dir.rglob("render_manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            continue

        if not isinstance(manifest, dict):
            continue

        revision = str(manifest.get("revision") or "").strip().lower()
        if revision == current_revision:
            continue

        updated_manifests.append(manifest_path)
        if fix:
            manifest["revision"] = current_revision
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
            )

    return updated_manifests


def refresh_seed_review_manifest_revisions(
    artifact_dir: Path, *, fix: bool = False
) -> list[Path]:
    """Refresh deterministic revision fields in seeded review manifests."""

    updated_manifests: list[Path] = []
    current_revision = repo_revision(Path(__file__).resolve().parents[2])
    if current_revision is None:
        return updated_manifests

    for manifest_path in sorted(artifact_dir.rglob("*.json")):
        if (
            manifest_path.relative_to(artifact_dir).as_posix()
            not in _SEED_REVIEW_MANIFEST_NAMES
        ):
            continue

        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            continue

        if not isinstance(manifest, dict):
            continue

        revision = str(manifest.get("revision") or "").strip().lower()
        if revision == current_revision:
            continue

        updated_manifests.append(manifest_path)
        if fix:
            manifest["revision"] = current_revision
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
            )

    return updated_manifests


def refresh_validation_results_script_hashes(
    artifact_dir: Path, *, fix: bool = False
) -> list[Path]:
    """Refresh deterministic script hashes in seeded validation results."""

    updated_results: list[Path] = []

    for result_path in sorted(artifact_dir.rglob("validation_results.json")):
        try:
            result = json.loads(result_path.read_text())
        except Exception:
            continue

        if not isinstance(result, dict):
            continue

        script_rel_path = str(result.get("script_path") or "").strip()
        if not script_rel_path:
            for candidate in (
                "benchmark_script.py",
                "solution_script.py",
                "script.py",
            ):
                if (result_path.parent / candidate).exists():
                    script_rel_path = candidate
                    break
        if not script_rel_path:
            continue
        script_path = (result_path.parent / script_rel_path).resolve()
        if not script_path.exists():
            continue

        actual_hash = hashlib.sha256(script_path.read_bytes()).hexdigest()
        script_sha256 = str(result.get("script_sha256") or "").strip().lower()
        if script_sha256 == actual_hash:
            continue

        updated_results.append(result_path)
        if fix:
            result["script_sha256"] = actual_hash
            result_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n"
            )

    return updated_results


def refresh_seed_artifact_manifests(
    artifact_dir: Path, *, fix: bool = False
) -> list[Path]:
    """Refresh all deterministic manifest-like seed artifacts in one pass."""

    updated_paths: list[Path] = []
    for updater in (
        refresh_seed_review_manifest_revisions,
        refresh_render_manifest_revisions,
        refresh_validation_results_script_hashes,
        refresh_plan_review_manifest_hashes,
    ):
        updated_paths.extend(updater(artifact_dir, fix=fix))
    return updated_paths


def refresh_seed_starter_template_files(
    artifact_dir: Path,
    agent_name: AgentName,
    *,
    fix: bool = False,
    refresh_manifests: bool = True,
) -> list[Path]:
    """Refresh the editable starter subset for a seeded agent workspace."""

    starter_files = load_seed_starter_template_files(agent_name)
    if not starter_files:
        return []

    updated_paths: list[Path] = []
    starter_changed = False

    for rel_path, content in sorted(starter_files.items()):
        file_path = artifact_dir / rel_path
        current = file_path.read_text(encoding="utf-8") if file_path.exists() else None
        if current == content:
            continue

        starter_changed = True
        updated_paths.append(file_path)
        if fix:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

    if refresh_manifests and starter_changed:
        updated_paths.extend(refresh_seed_artifact_manifests(artifact_dir, fix=fix))

    return updated_paths


@lru_cache(maxsize=8)
def _seed_artifact_dirs(seed_artifacts_root: str) -> tuple[str, ...]:
    root = Path(seed_artifacts_root)
    if not root.exists():
        return ()

    artifact_dirs: list[str] = []
    for group_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for artifact_dir in sorted(p for p in group_dir.iterdir() if p.is_dir()):
            artifact_dirs.append(str(artifact_dir))
    return tuple(artifact_dirs)


def refresh_repo_seed_artifact_manifests(
    repo_root: Path, *, fix: bool = False
) -> list[Path]:
    """Refresh deterministic manifest-like seed artifacts across the repository."""

    updated_paths: list[Path] = []
    seed_artifacts_root = repo_root / "dataset" / "data" / "seed" / "artifacts"
    for artifact_dir_str in _seed_artifact_dirs(str(seed_artifacts_root)):
        updated_paths.extend(
            refresh_seed_artifact_manifests(Path(artifact_dir_str), fix=fix)
        )
    return updated_paths
