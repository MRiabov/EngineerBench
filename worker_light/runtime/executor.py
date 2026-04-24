"""Shell-command runtime executor for session-isolated command execution."""

import asyncio
import contextlib
import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import structlog
from pydantic import BaseModel, StrictBool, StrictInt, StrictStr

from shared.git_utils import repo_revision

logger = structlog.get_logger(__name__)

# Default execution timeout in seconds
DEFAULT_TIMEOUT_SECONDS = 30


class ExecutionResult(BaseModel):
    """Result of a shell command execution."""

    stdout: StrictStr
    stderr: StrictStr
    exit_code: StrictInt
    timed_out: StrictBool = False


class RuntimeConfig(BaseModel):
    """Configuration for the session runtime executor."""

    timeout_seconds: StrictInt = DEFAULT_TIMEOUT_SECONDS
    shell_executable: StrictStr = "/bin/bash"
    working_directory: StrictStr | None = None


@contextlib.contextmanager
def _prepared_execution(
    env: dict[str, str] | None = None,
) -> Generator[dict[str, str], None, None]:
    """Prepare a shell environment rooted in the project virtualenv."""
    actual_env = os.environ.copy()
    if env:
        actual_env.update(env)

    # Resolve project root and set PYTHONPATH
    project_root = Path(__file__).resolve().parents[2]
    worker_package_parent = str(project_root)
    current_pythonpath = actual_env.get("PYTHONPATH", "")

    if current_pythonpath:
        actual_env["PYTHONPATH"] = f"{worker_package_parent}:{current_pythonpath}"
    else:
        actual_env["PYTHONPATH"] = worker_package_parent

    python_bin = str(Path(sys.executable).resolve().parent)
    current_path = actual_env.get("PATH", "")
    if current_path:
        actual_env["PATH"] = f"{python_bin}:{current_path}"
    else:
        actual_env["PATH"] = python_bin

    repo_root = Path(__file__).resolve().parents[2]
    current_revision = repo_revision(repo_root)
    if current_revision:
        actual_env.setdefault("REPO_REVISION", current_revision)

    actual_env.setdefault("PYTHONEXECUTABLE", sys.executable)
    if sys.prefix != sys.base_prefix:
        actual_env.setdefault("VIRTUAL_ENV", sys.prefix)

    yield actual_env


def run_command(
    command: str,
    env: dict[str, str] | None = None,
    config: RuntimeConfig | None = None,
    session_id: str | None = None,
) -> ExecutionResult:
    """Execute a shell command in a subprocess."""
    if config is None:
        config = RuntimeConfig()

    logger.debug(
        "runtime_execute",
        command_length=len(command),
        timeout=config.timeout_seconds,
        session_id=session_id,
    )

    with _prepared_execution(env) as actual_env:
        try:
            cmd = [config.shell_executable, "-lc", command]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
                env=actual_env,
                cwd=config.working_directory,
            )

            logger.info(
                "runtime_execute_complete",
                exit_code=result.returncode,
                stdout_length=len(result.stdout),
                stderr_length=len(result.stderr),
            )

            return ExecutionResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                timed_out=False,
            )

        except subprocess.TimeoutExpired:
            logger.warning("runtime_execute_timeout", timeout=config.timeout_seconds)
            return ExecutionResult(
                stdout="",
                stderr=f"Execution timed out after {config.timeout_seconds} seconds",
                exit_code=-1,
                timed_out=True,
            )
        except Exception as e:
            logger.error("runtime_execute_error", error=str(e), session_id=session_id)
            return ExecutionResult(
                stdout="",
                stderr=str(e),
                exit_code=-1,
                timed_out=False,
            )


async def run_command_async(
    command: str,
    env: dict[str, str] | None = None,
    config: RuntimeConfig | None = None,
    session_id: str | None = None,
) -> ExecutionResult:
    """Execute a shell command asynchronously in a subprocess."""
    if config is None:
        config = RuntimeConfig()

    logger.debug(
        "runtime_execute_async",
        command_length=len(command),
        timeout=config.timeout_seconds,
        session_id=session_id,
    )

    with _prepared_execution(env) as actual_env:
        try:
            process = await asyncio.create_subprocess_exec(
                config.shell_executable,
                "-lc",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=actual_env,
                cwd=config.working_directory,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=config.timeout_seconds,
                )

                exit_code = process.returncode or 0

                logger.info(
                    "runtime_execute_async_complete",
                    exit_code=exit_code,
                    stdout_length=len(stdout),
                    stderr_length=len(stderr),
                )

                return ExecutionResult(
                    stdout=stdout.decode("utf-8"),
                    stderr=stderr.decode("utf-8"),
                    exit_code=exit_code,
                    timed_out=False,
                )

            except TimeoutError:
                process.kill()
                await process.wait()

                logger.warning(
                    "runtime_execute_async_timeout",
                    timeout=config.timeout_seconds,
                )

                return ExecutionResult(
                    stdout="",
                    stderr=(
                        f"Execution timed out after {config.timeout_seconds} seconds"
                    ),
                    exit_code=-1,
                    timed_out=True,
                )

        except Exception as e:
            logger.error(
                "runtime_execute_async_error", error=str(e), session_id=session_id
            )
            return ExecutionResult(
                stdout="",
                stderr=str(e),
                exit_code=-1,
                timed_out=False,
            )


def run_python_code(
    code: str,
    env: dict[str, str] | None = None,
    config: RuntimeConfig | None = None,
    session_id: str | None = None,
) -> ExecutionResult:
    """Legacy compatibility wrapper for callers still using the old name."""
    return run_command(code, env=env, config=config, session_id=session_id)


async def run_python_code_async(
    code: str,
    env: dict[str, str] | None = None,
    config: RuntimeConfig | None = None,
    session_id: str | None = None,
) -> ExecutionResult:
    """Legacy compatibility wrapper for callers still using the old name."""
    return await run_command_async(code, env=env, config=config, session_id=session_id)
