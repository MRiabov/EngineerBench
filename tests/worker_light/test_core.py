"""Tests for the Worker filesystem and runtime modules.

These tests verify:
- S3 backend file operations
- Read-only restrictions on utils/skills/reviews
- Python runtime execution with timeouts
- Dependency verification
"""

import pytest

from worker_light.runtime.executor import RuntimeConfig, run_python_code


class TestRuntimeExecutor:
    """Tests for the Python runtime executor."""

    def test_run_simple_code(self):
        """Test executing simple Python code."""
        result = run_python_code('print("hello")')

        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert result.stderr == ""
        assert not result.timed_out

    def test_run_code_with_error(self):
        """Test executing code that raises an error."""
        result = run_python_code('raise ValueError("test error")')

        assert result.exit_code != 0
        assert "ValueError" in result.stderr

    def test_run_code_timeout(self):
        """Test that code execution times out properly."""
        config = RuntimeConfig(timeout_seconds=1)
        result = run_python_code(
            "import time; time.sleep(10)",
            config=config,
        )

        assert result.timed_out
        assert result.exit_code == -1

    def test_run_code_with_env(self):
        """Test executing code with custom environment variables."""
        import os

        env = {**os.environ, "TEST_VAR": "test_value"}
        result = run_python_code(
            'import os; print(os.environ.get("TEST_VAR", ""))',
            env=env,
        )

        assert result.exit_code == 0
        assert "test_value" in result.stdout


class TestFilesystemRouter:
    """Tests for the filesystem router read-only restrictions."""

    def test_read_only_utils_check(self):
        """Test that utils path is detected as read-only."""
        from shared.workers.filesystem.router import FilesystemRouter

        # Create a mock router (we don't connect to S3 here)
        # Just test the read-only detection logic
        class MockBackend:
            pass

        # Test the _is_read_only method directly
        router = FilesystemRouter.__new__(FilesystemRouter)
        router.READ_ONLY_PREFIXES = ("/utils/", "/skills/", "/reviews/")

        assert router._is_read_only("/utils/file.py") is True
        assert router._is_read_only("/skills/helper.py") is True
        assert router._is_read_only("/reviews/log.txt") is True
        assert router._is_read_only("/files/workspace.py") is False
        assert router._is_read_only("/hello.txt") is False


class TestDependencyVerification:
    """Tests for CAD dependency verification."""

    def test_build123d_import(self):
        """Test that build123d can be imported."""
        import sys

        config = RuntimeConfig(python_executable=sys.executable)
        result = run_python_code(
            "import build123d; print(build123d.__version__)", config=config
        )
        assert result.exit_code == 0, f"build123d import failed: {result.stderr}"

    @pytest.mark.integration
    @pytest.mark.xdist_group(name="physics_sims")
    def test_mujoco_import(self):
        """Test that mujoco can be imported."""
        import sys

        config = RuntimeConfig(python_executable=sys.executable)
        result = run_python_code(
            "import mujoco; print(mujoco.__version__)", config=config
        )
        assert result.exit_code == 0, f"mujoco import failed: {result.stderr}"
