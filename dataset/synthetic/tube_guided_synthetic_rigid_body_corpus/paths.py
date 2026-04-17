from __future__ import annotations

import json
import runpy
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, TextIO

import yaml


def bootstrap_repo_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve().parent).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "specs" / "desired_architecture.md").exists():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate
    raise FileNotFoundError("Could not locate the repository root")


REPO_ROOT = bootstrap_repo_root()


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "specs" / "desired_architecture.md").exists():
            return candidate
    raise FileNotFoundError("Could not locate the repository root")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            data,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        ),
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def load_benchmark_build_fn(bundle_dir: Path):
    namespace = runpy.run_path(str(bundle_dir / "benchmark_script.py"))
    build_fn = namespace.get("build")
    if build_fn is None:
        raise KeyError(f"{bundle_dir / 'benchmark_script.py'} does not define build()")
    return build_fn


def payload_scene_name(label: str) -> str:
    return f"benchmark_payload__{str(label).strip()}"


def progress_iter(iterable, desc: str):
    try:
        from tqdm.auto import tqdm

        return tqdm(iterable, desc=desc, leave=False)
    except Exception:
        return iterable


class _TeeStream:
    def __init__(self, live_stream: TextIO, log_handle: TextIO):
        self._live_stream = live_stream
        self._log_handle = log_handle

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._live_stream.write(text)
        self._log_handle.write(text)
        self._live_stream.flush()
        self._log_handle.flush()
        return len(text)

    def flush(self) -> None:
        self._live_stream.flush()
        self._log_handle.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._live_stream, "isatty", lambda: False)())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._live_stream, name)


class NotebookLogCapture:
    def __init__(self, path: Path):
        self.path = path
        self._log_handle: TextIO | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.path.open("a", encoding="utf-8")
        self._log_handle.write("=== notebook run start ===\n")
        self._log_handle.flush()
        self._stdout_cm = redirect_stdout(_TeeStream(sys.stdout, self._log_handle))
        self._stderr_cm = redirect_stderr(_TeeStream(sys.stderr, self._log_handle))
        self._stdout_cm.__enter__()
        self._stderr_cm.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stdout_cm.__exit__(exc_type, exc, tb)
        self._stderr_cm.__exit__(exc_type, exc, tb)
        if self._log_handle is not None:
            if exc_type is not None:
                self._log_handle.write(
                    f"=== notebook run failed: {exc_type.__name__}: {exc} ===\n"
                )
            else:
                self._log_handle.write("=== notebook run completed ===\n")
            self._log_handle.flush()
            self._log_handle.close()
            self._log_handle = None
        return False

