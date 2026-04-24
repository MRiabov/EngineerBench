"""SandboxFilesystemBackend implementation for S3-backed file operations.

This module provides a filesystem abstraction that maps virtual paths
to S3 storage with session-based isolation.
"""

import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, StrictBool, StrictInt, StrictStr

from shared.backend.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)
from shared.backend.protocol import (
    FileInfo as ProtocolFileInfo,
)
from shared.backend.utils import (
    check_empty_content,
    format_content_with_line_numbers,
    perform_string_replacement,
)

logger = structlog.get_logger(__name__)

_INTEGRATION_SESSION_RE = re.compile(
    r"\b(INT-(?:NEG-\d+|\d+))\b",
    re.IGNORECASE,
)


class FileInfo(BaseModel):
    """Information about a file or directory."""

    path: StrictStr
    name: StrictStr
    is_dir: StrictBool
    size: StrictInt | None = None


@runtime_checkable
class SessionManager(Protocol):
    """Protocol for session management."""

    def get_session_id(self) -> str:
        """Return the current session ID."""
        ...


@dataclass
class SimpleSessionManager:
    """Simple session manager with a fixed session ID."""

    session_id: str

    def get_session_id(self) -> str:
        """Return the session ID."""
        return self.session_id


class BaseFilesystemBackend(BackendProtocol, ABC):
    """Base class for filesystem backends with shared logic."""

    @abstractmethod
    def _read_raw(self, virtual_path: str) -> str:
        """Read raw file content."""
        ...

    @abstractmethod
    def _write_raw(self, virtual_path: str, content: str) -> None:
        """Write raw file content."""
        ...

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content with line numbers."""
        try:
            content = self._read_raw(file_path)
            empty_msg = check_empty_content(content)
            if empty_msg:
                return empty_msg

            lines = content.splitlines()
            start_idx = offset
            end_idx = min(start_idx + limit, len(lines))

            if start_idx >= len(lines):
                return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

            selected_lines = lines[start_idx:end_idx]
            return format_content_with_line_numbers(
                selected_lines, start_line=start_idx + 1
            )
        except FileNotFoundError:
            return f"Error: File '{file_path}' not found"
        except Exception as e:
            return f"Error reading file '{file_path}': {e!s}"

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Perform exact string replacements."""
        try:
            content = self._read_raw(file_path)
            result = perform_string_replacement(
                content, old_string, new_string, replace_all
            )
            if isinstance(result, str):
                return EditResult(error=result)

            new_content, occurrences = result
            self._write_raw(file_path, new_content)

            return EditResult(
                path=file_path, files_update=None, occurrences=int(occurrences)
            )
        except FileNotFoundError:
            return EditResult(error=f"Error: File '{file_path}' not found")
        except Exception as e:
            return EditResult(error=f"Error editing file '{file_path}': {e!s}")

    def ls(self, path: str = "/") -> list[FileInfo]:
        """List contents of a directory (Legacy)."""
        infos = self.ls_info(path)
        return [
            FileInfo(
                path=i.path,
                name=i.path.rstrip("/").split("/")[-1] or "/",
                is_dir=i.is_dir,
                size=i.size,
            )
            for i in infos
        ]

    def _grep_in_content(
        self, content: str, pattern: str, virtual_path: str
    ) -> list[GrepMatch]:
        regex = re.compile(re.escape(pattern))
        matches: list[GrepMatch] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            if regex.search(line):
                matches.append(GrepMatch(path=virtual_path, line=line_num, text=line))
        return matches


# Global registry to keep TemporaryDirectory objects alive for the duration of the worker process.
# This ensures that session directories persist across multiple requests but are cleaned up on exit.
_SESSION_DIR_REGISTRY: dict[str, tempfile.TemporaryDirectory] = {}


def _normalize_session_id(session_id: str) -> str:
    return session_id


def get_session_root(session_id: str) -> Path:
    """Get or create a temporary directory for a session."""
    canonical_session_id = _normalize_session_id(session_id)
    if canonical_session_id not in _SESSION_DIR_REGISTRY:
        # Create a new unique temporary directory.
        # The prefix helps identify the session during debugging.
        td = tempfile.TemporaryDirectory(prefix=f"pb-sess-{canonical_session_id}-")
        _SESSION_DIR_REGISTRY[canonical_session_id] = td
        logger.info(
            "session_directory_created",
            session_id=canonical_session_id,
            path=td.name,
        )

    return Path(_SESSION_DIR_REGISTRY[canonical_session_id].name)


class LocalFilesystemBackend(BaseFilesystemBackend):
    """Local-disk backed filesystem with session-based isolation."""

    def __init__(
        self,
        root: Path,
        session_id: str,
    ) -> None:
        self.root = root
        self.session_id = session_id
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(
        cls,
        session_id: str,
        base_dir: Path | None = None,
    ) -> "LocalFilesystemBackend":
        if base_dir is not None:
            root = base_dir / session_id
        else:
            root = get_session_root(session_id)
        backend = cls(root=root, session_id=session_id)

        # Seed the session-local catalog database from the repository snapshot.
        # Session workspaces start empty, but validation and pricing code expects
        # a usable `parts.db` inside the workspace root.
        try:
            repo_root = Path(__file__).resolve().parents[3]
            source_db = repo_root / "parts.db"
            target_db = backend.root / "parts.db"
            if source_db.exists() and (
                not target_db.exists() or target_db.stat().st_size == 0
            ):
                target_db.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_db, target_db)
        except Exception as e:
            logger.warning("catalog_db_seed_failed", error=str(e))
        return backend

    def _resolve(self, virtual_path: str) -> Path:
        normalized = virtual_path
        # Common LLM convention: treat /workspace as session root.
        if normalized in {"/workspace", "workspace"}:
            normalized = "/"
        elif normalized.startswith("/workspace/"):
            normalized = "/" + normalized[len("/workspace/") :]
        elif normalized.startswith("workspace/"):
            normalized = normalized[len("workspace/") :]

        rel = normalized.lstrip("/")
        root = self.root.resolve()
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PermissionError(f"Path traversal attempted: {virtual_path}") from exc
        return path

    def _virtual(self, local_path: Path) -> str:
        try:
            rel = local_path.relative_to(self.root)
            return "/" + str(rel)
        except ValueError:
            return "/" + local_path.name

    def _read_raw(self, virtual_path: str) -> str:
        local_path = self._resolve(virtual_path)
        return local_path.read_text(encoding="utf-8")

    def _write_raw(self, virtual_path: str, content: str) -> None:
        local_path = self._resolve(virtual_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")

    def ls_info(self, path: str) -> list[ProtocolFileInfo]:
        local_path = self._resolve(path)
        logger.debug(
            "ls_info_start",
            path=path,
            local_path=str(local_path),
            exists=local_path.exists(),
            is_dir=local_path.is_dir(),
        )
        if not local_path.exists():
            return []
        results = []
        if local_path.is_dir():
            entries = list(local_path.iterdir())
            logger.debug(
                "ls_info_entries", count=len(entries), names=[e.name for e in entries]
            )
            for entry in entries:
                is_dir = entry.is_dir()
                virt = self._virtual(entry)
                if is_dir and not virt.endswith("/"):
                    virt += "/"
                info = ProtocolFileInfo(
                    path=virt,
                    is_dir=is_dir,
                    size=entry.stat().st_size if not is_dir else 0,
                    modified_at=datetime.fromtimestamp(
                        entry.stat().st_mtime
                    ).isoformat(),
                )
                results.append(info)
        else:
            results.append(
                ProtocolFileInfo(
                    path=self._virtual(local_path),
                    is_dir=False,
                    size=local_path.stat().st_size,
                    modified_at=datetime.fromtimestamp(
                        local_path.stat().st_mtime
                    ).isoformat(),
                )
            )
        results.sort(key=lambda x: x.path)
        return results

    def write(
        self, file_path: str, content: str, overwrite: bool = False
    ) -> WriteResult:
        local_path = self._resolve(file_path)
        if local_path.exists() and not overwrite:
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. Use 'overwrite=True' if you intend to overwrite it."
            )
        try:
            self._write_raw(file_path, content)
            return WriteResult(path=file_path, files_update=None)
        except Exception as e:
            return WriteResult(error=f"Error writing file '{file_path}': {e!s}")

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        base_virt = path or "/"
        try:
            files = self.glob_info(glob or "**/*", path=base_virt)
            matches: list[GrepMatch] = []
            for f_info in files:
                if f_info.is_dir:
                    continue
                try:
                    content = self._read_raw(f_info.path)
                    matches.extend(self._grep_in_content(content, pattern, f_info.path))
                except Exception:
                    continue
            return matches
        except Exception as e:
            return f"Error during grep: {e!s}"

    def glob_info(self, pattern: str, path: str = "/") -> list[ProtocolFileInfo]:
        """Find files matching a glob pattern."""
        local_base = self._resolve(path)
        if not local_base.exists() or not local_base.is_dir():
            return []

        results = []
        p = pattern.lstrip("/")

        try:
            if "**" in p:
                matched = local_base.rglob(p.replace("**/", ""))
            else:
                matched = local_base.glob(p)

            for entry in matched:
                is_dir = entry.is_dir()
                virt = self._virtual(entry)
                if is_dir and not virt.endswith("/"):
                    virt += "/"

                results.append(
                    ProtocolFileInfo(
                        path=virt,
                        is_dir=is_dir,
                        size=entry.stat().st_size if not is_dir else 0,
                        modified_at=datetime.fromtimestamp(
                            entry.stat().st_mtime
                        ).isoformat(),
                    )
                )
            results.sort(key=lambda x: x.path)
            return results
        except Exception as e:
            logger.warning("glob_failed", error=str(e))
            return []

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files."""
        responses = []
        for path, content in files:
            try:
                local_p = self._resolve(path)
                local_p.parent.mkdir(parents=True, exist_ok=True)
                local_p.write_bytes(content)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception as e:
                responses.append(FileUploadResponse(path=path, error=str(e)))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files."""
        responses = []
        for path in paths:
            try:
                local_p = self._resolve(path)
                content = local_p.read_bytes()
                responses.append(
                    FileDownloadResponse(path=path, content=content, error=None)
                )
            except FileNotFoundError:
                responses.append(
                    FileDownloadResponse(path=path, error="file_not_found")
                )
            except Exception as e:
                responses.append(FileDownloadResponse(path=path, error=str(e)))
        return responses

    # --- Legacy methods ---

    def exists(self, path: str) -> bool:
        """Check if a path exists."""
        try:
            local_path = self._resolve(path)
            return local_path.exists()
        except:
            return False

    def delete(self, path: str) -> None:
        """Delete a file or directory."""
        local_path = self._resolve(path)
        if not local_path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        if local_path.is_dir():
            shutil.rmtree(local_path)
        else:
            local_path.unlink()
