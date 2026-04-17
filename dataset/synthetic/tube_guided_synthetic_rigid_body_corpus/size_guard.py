from __future__ import annotations

from pathlib import Path


def assert_generator_tree_line_limits(
    root: Path, *, max_lines: int = 800
) -> None:
    oversize: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > max_lines:
            oversize.append(f"{path}: {line_count}")
    if oversize:
        raise RuntimeError(
            "Generator tree exceeds the file-size cap of "
            f"{max_lines} lines: {', '.join(oversize)}"
        )

