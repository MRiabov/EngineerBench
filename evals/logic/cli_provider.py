from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from evals.logic.stack_profiles import apply_stack_profile_env
from shared.agents.config import load_agents_config
from shared.enums import AgentName
from shared.git_utils import repo_revision
from shared.runtime.headless import load_headless_opengl_config

ROOT = Path(__file__).resolve().parents[2]

ReasoningEffort = Literal["low", "medium", "high", "xhigh"]
ReasoningEffortArg = ReasoningEffort | None | object
REASONING_EFFORT_UNSET: object = object()
PromptTransport = Literal["none", "stdin", "prompt_flag", "positional"]
ALLOW_HOST_LOOPBACK_ENV = "PROBLEMOLOGIST_CLI_ALLOW_HOST_LOOPBACK"


@dataclass(frozen=True, slots=True)
class CliInvocation:
    argv: list[str]
    prompt_text: str | None = None
    prompt_transport: PromptTransport = "none"
    cwd: Path | None = None
    env_overrides: dict[str, str] = field(default_factory=dict)
    resume_session_id: str | None = None
    output_last_message_path: Path | None = None

    def __post_init__(self) -> None:
        if self.prompt_transport == "none" and self.prompt_text is not None:
            raise ValueError(
                "prompt_text must be omitted when prompt_transport is none"
            )
        if self.prompt_transport != "none" and self.prompt_text is None:
            raise ValueError(
                "prompt_text is required when prompt_transport is not none"
            )


@runtime_checkable
class CliProvider(Protocol):
    provider_name: str
    binary_name: str
    home_dir_name: str
    runtime_root_name: str
    session_prefix: str

    def translate_reasoning_effort(
        self, reasoning_effort: ReasoningEffort | None
    ) -> str | None: ...

    def prepare_home(
        self,
        *,
        codex_home_root: Path,
        workspace_dir: Path,
        source_auth_path: Path | None = None,
        agent_name: AgentName | None = None,
        reasoning_effort: ReasoningEffortArg = REASONING_EFFORT_UNSET,
    ) -> Path: ...

    def build_env(
        self,
        *,
        task_id: str,
        workspace_dir: Path,
        codex_home_root: Path,
        session_id: str | None = None,
        agent_name: AgentName | None = None,
    ) -> dict[str, str]: ...

    def build_exec_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> CliInvocation: ...

    def build_ui_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> CliInvocation: ...

    def build_help_invocation(self) -> CliInvocation: ...

    def build_help_command(self) -> list[str]: ...


def _copy_auth_bundle(source_auth_path: Path, codex_home_dir: Path) -> None:
    if not source_auth_path.exists():
        raise FileNotFoundError(f"CLI auth file not found: {source_auth_path}")
    shutil.copy2(source_auth_path, codex_home_dir / "auth.json")


def _execution_flags(*, yolo: bool) -> list[str]:
    if _allow_host_loopback() or yolo:
        return ["--dangerously-bypass-approvals-and-sandbox"]
    return ["--full-auto"]


def _qwen_execution_flags(*, yolo: bool) -> list[str]:
    flags = ["--chat-recording"]
    if _allow_host_loopback() or yolo:
        flags.append("--yolo")
    else:
        flags.append("--sandbox")
    return flags


def _allow_host_loopback() -> bool:
    return os.getenv(ALLOW_HOST_LOOPBACK_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True, slots=True)
class CodexCliProvider:
    provider_name: str = "codex"
    binary_name: str = "codex"
    home_dir_name: str = ".codex"
    runtime_root_name: str = "codex-runtime"
    session_prefix: str = "local-codex"

    def _default_source_auth_path(self) -> Path:
        return Path.home() / self.home_dir_name / "auth.json"

    def prepare_home(
        self,
        *,
        codex_home_root: Path,
        workspace_dir: Path,
        source_auth_path: Path | None = None,
        agent_name: AgentName | None = None,
        reasoning_effort: ReasoningEffortArg = REASONING_EFFORT_UNSET,
    ) -> Path:
        source_auth_path = source_auth_path or self._default_source_auth_path()

        codex_home_dir = codex_home_root / self.home_dir_name
        codex_home_dir.mkdir(parents=True, exist_ok=True)
        (codex_home_root / ".cache").mkdir(parents=True, exist_ok=True)
        (codex_home_root / ".config").mkdir(parents=True, exist_ok=True)
        (codex_home_root / ".tmp").mkdir(parents=True, exist_ok=True)
        _copy_auth_bundle(source_auth_path, codex_home_dir)

        workspace_path = workspace_dir.expanduser().resolve()
        from evals.logic import codex_workspace as codex_workspace_module

        config_loader = getattr(
            codex_workspace_module, "load_agents_config", load_agents_config
        )
        config = (
            config_loader()
            if agent_name is not None or reasoning_effort is not REASONING_EFFORT_UNSET
            else None
        )
        if config is not None and not config.llm.reasoning_effort_enabled:
            resolved_reasoning_effort = None
        elif reasoning_effort is REASONING_EFFORT_UNSET:
            resolved_reasoning_effort = (
                config.get_reasoning_effort(agent_name)
                if config is not None and agent_name is not None
                else "high"
            )
        else:
            resolved_reasoning_effort = reasoning_effort

        resolved_reasoning_effort = self.translate_reasoning_effort(
            resolved_reasoning_effort
        )

        config_path = codex_home_dir / "config.toml"
        config_lines = [
            'model = "gpt-5.4-mini"',
            'approvals_reviewer = "user"',
            "",
            "[features]",
            "use_legacy_landlock = true",
            "",
            f'[projects."{workspace_path.as_posix()}"]',
            'trust_level = "trusted"',
            "respect_gitignore = false",
            "",
        ]
        if resolved_reasoning_effort is not None:
            config_lines.insert(
                1, f'model_reasoning_effort = "{resolved_reasoning_effort}"'
            )
        config_path.write_text("\n".join(config_lines), encoding="utf-8")
        return codex_home_dir

    def translate_reasoning_effort(
        self, reasoning_effort: ReasoningEffort | None
    ) -> str | None:
        return reasoning_effort

    def build_env(
        self,
        *,
        task_id: str,
        workspace_dir: Path,
        codex_home_root: Path,
        session_id: str | None = None,
        agent_name: AgentName | None = None,
    ) -> dict[str, str]:
        env = dict(os.environ)
        apply_stack_profile_env("eval", env=env, root=ROOT)
        env.pop("DISPLAY", None)
        env.pop("XAUTHORITY", None)
        env.pop("WAYLAND_DISPLAY", None)
        env["PROBLEMOLOGIST_PHYSICS_GL_BACKEND"] = "egl"
        env["PROBLEMOLOGIST_RENDER_GL_BACKEND"] = "osmesa"
        headless_config = load_headless_opengl_config(env)
        headless_config.apply_physics(env)
        env["PROBLEMOLOGIST_RENDER_GL_BACKEND"] = "osmesa"
        env["PYOPENGL_PLATFORM"] = "osmesa"
        env["VTK_DEFAULT_OPENGL_WINDOW"] = "vtkOSOpenGLRenderWindow"
        env["PYVISTA_OFF_SCREEN"] = "true"
        env["PYGLET_HEADLESS"] = "1"
        env.pop("LIBGL_ALWAYS_SOFTWARE", None)
        env["HOME"] = str(codex_home_root)
        env["CODEX_HOME"] = str(codex_home_root / self.home_dir_name)
        env["XDG_CACHE_HOME"] = str(codex_home_root / ".cache")
        env["XDG_CONFIG_HOME"] = str(codex_home_root / ".config")
        env.setdefault("TMPDIR", str(codex_home_root / ".tmp"))
        env.setdefault("TEMP", str(codex_home_root / ".tmp"))
        env.setdefault("TMP", str(codex_home_root / ".tmp"))
        workspace_path = workspace_dir.expanduser().resolve()

        venv_bin = ROOT / ".venv" / "bin"
        if venv_bin.exists():
            current_path = env.get("PATH", "")
            env["PATH"] = (
                f"{venv_bin}{os.pathsep}{current_path}"
                if current_path
                else str(venv_bin)
            )
            env.setdefault("VIRTUAL_ENV", str(ROOT / ".venv"))
            env["PYTHON_BIN"] = str(venv_bin / "python")
        else:
            env.setdefault("PYTHON_BIN", sys.executable)

        env.setdefault("CONTROLLER_URL", "http://localhost:18000")
        env.setdefault("WORKER_LIGHT_URL", "http://localhost:18001")
        env.setdefault(
            "SESSION_ID", session_id or f"{self.session_prefix}-{task_id}-{os.getpid()}"
        )
        env.setdefault("IS_HEAVY_WORKER", "1")
        env.setdefault("PROBLEMOLOGIST_SCRIPT_IMPORT_MODE", "0")
        env.setdefault("CATALOG_DB_PATH", str(ROOT / "parts.db"))
        env.setdefault("PROBLEMOLOGIST_REPO_ROOT", str(ROOT))
        current_revision = repo_revision(ROOT)
        if current_revision:
            env.setdefault("REPO_REVISION", current_revision)
        existing_pythonpath = env.get("PYTHONPATH", "")
        pythonpath_entries = [str(workspace_path), str(ROOT)]
        if existing_pythonpath:
            pythonpath_entries.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(
            entry for entry in pythonpath_entries if entry
        )
        return env

    def _build_exec_argv(
        self,
        *,
        workspace_dir: Path,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> list[str]:
        cmd = [self.binary_name, "exec", "-C", str(workspace_dir)]
        if resume_session_id is not None:
            cmd.extend(["resume", resume_session_id])
        cmd.extend(_execution_flags(yolo=yolo))
        if output_last_message_path is not None:
            output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--output-last-message", str(output_last_message_path)])
        cmd.extend(
            [
                "-c",
                "shell_environment_policy.inherit=all",
                "--skip-git-repo-check",
                "-",
            ]
        )
        return cmd

    def build_exec_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> CliInvocation:
        return CliInvocation(
            argv=self._build_exec_argv(
                workspace_dir=workspace_dir,
                yolo=yolo,
                resume_session_id=resume_session_id,
                output_last_message_path=output_last_message_path,
            ),
            prompt_text=prompt_text,
            prompt_transport="stdin",
            cwd=workspace_dir,
            resume_session_id=resume_session_id,
            output_last_message_path=output_last_message_path,
        )

    def build_exec_command(
        self,
        *,
        workspace_dir: Path,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> list[str]:
        return self._build_exec_argv(
            workspace_dir=workspace_dir,
            yolo=yolo,
            resume_session_id=resume_session_id,
            output_last_message_path=output_last_message_path,
        )

    def _build_ui_argv(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> list[str]:
        return [
            self.binary_name,
            *_execution_flags(yolo=yolo),
            "-c",
            "shell_environment_policy.inherit=all",
            "--cd",
            str(workspace_dir),
            "--no-alt-screen",
            prompt_text,
        ]

    def build_ui_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> CliInvocation:
        return CliInvocation(
            argv=self._build_ui_argv(
                workspace_dir=workspace_dir,
                prompt_text=prompt_text,
                yolo=yolo,
            ),
            prompt_text=prompt_text,
            prompt_transport="positional",
            cwd=workspace_dir,
        )

    def build_ui_command(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> list[str]:
        return self._build_ui_argv(
            workspace_dir=workspace_dir,
            prompt_text=prompt_text,
            yolo=yolo,
        )

    def build_help_invocation(self) -> CliInvocation:
        return CliInvocation(
            argv=self.build_help_command(),
            prompt_transport="none",
        )

    def build_help_command(self) -> list[str]:
        return [self.binary_name, "exec", "--help"]


@dataclass(frozen=True, slots=True)
class QwenCliProvider(CodexCliProvider):
    provider_name: str = "qwen"
    binary_name: str = "qwen"
    home_dir_name: str = ".qwen"
    runtime_root_name: str = "qwen-runtime"
    session_prefix: str = "local-qwen"

    def _default_source_auth_path(self) -> Path:
        return Path.home() / self.home_dir_name / "oauth_creds.json"

    def _copy_qwen_home_state(self, source_home_dir: Path, qwen_home_dir: Path) -> None:
        for filename in (
            "settings.json",
            "oauth_creds.json",
            "installation_id",
            "source.json",
            "output-language.md",
        ):
            source_path = source_home_dir / filename
            if source_path.exists():
                shutil.copy2(source_path, qwen_home_dir / filename)

    def prepare_home(
        self,
        *,
        codex_home_root: Path,
        workspace_dir: Path,
        source_auth_path: Path | None = None,
        agent_name: AgentName | None = None,
        reasoning_effort: ReasoningEffortArg = REASONING_EFFORT_UNSET,
    ) -> Path:
        source_auth_path = source_auth_path or self._default_source_auth_path()
        qwen_home_dir = CodexCliProvider.prepare_home(
            self,
            codex_home_root=codex_home_root,
            workspace_dir=workspace_dir,
            source_auth_path=source_auth_path,
            agent_name=agent_name,
            reasoning_effort=reasoning_effort,
        )
        self._copy_qwen_home_state(source_auth_path.parent, qwen_home_dir)
        return qwen_home_dir

    def build_env(
        self,
        *,
        task_id: str,
        workspace_dir: Path,
        codex_home_root: Path,
        session_id: str | None = None,
        agent_name: AgentName | None = None,
    ) -> dict[str, str]:
        env = CodexCliProvider.build_env(
            self,
            task_id=task_id,
            workspace_dir=workspace_dir,
            codex_home_root=codex_home_root,
            session_id=session_id,
            agent_name=agent_name,
        )
        env["QWEN_HOME"] = env["CODEX_HOME"]
        return env

    def _build_exec_argv(
        self,
        *,
        workspace_dir: Path,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> list[str]:
        cmd = [self.binary_name, *_qwen_execution_flags(yolo=yolo)]
        if resume_session_id is not None:
            cmd.extend(["--resume", resume_session_id])
        if output_last_message_path is not None:
            output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
        return cmd

    def build_exec_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> CliInvocation:
        return CliInvocation(
            argv=self._build_exec_argv(
                workspace_dir=workspace_dir,
                yolo=yolo,
                resume_session_id=resume_session_id,
                output_last_message_path=output_last_message_path,
            )
            + [prompt_text],
            prompt_text=prompt_text,
            prompt_transport="positional",
            cwd=workspace_dir,
            resume_session_id=resume_session_id,
            output_last_message_path=output_last_message_path,
        )

    def build_exec_command(
        self,
        *,
        workspace_dir: Path,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> list[str]:
        return self._build_exec_argv(
            workspace_dir=workspace_dir,
            yolo=yolo,
            resume_session_id=resume_session_id,
            output_last_message_path=output_last_message_path,
        )

    def _build_ui_argv(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> list[str]:
        return [
            self.binary_name,
            *_qwen_execution_flags(yolo=yolo),
            "--prompt-interactive",
            prompt_text,
        ]

    def build_ui_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> CliInvocation:
        return CliInvocation(
            argv=self._build_ui_argv(
                workspace_dir=workspace_dir,
                prompt_text=prompt_text,
                yolo=yolo,
            ),
            prompt_text=prompt_text,
            prompt_transport="prompt_flag",
            cwd=workspace_dir,
        )

    def build_ui_command(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> list[str]:
        return self._build_ui_argv(
            workspace_dir=workspace_dir,
            prompt_text=prompt_text,
            yolo=yolo,
        )

    def build_help_command(self) -> list[str]:
        return [self.binary_name, "--help"]


@dataclass(frozen=True, slots=True)
class PiCliProvider(CodexCliProvider):
    provider_name: str = "pi"
    binary_name: str = "pi"
    home_dir_name: str = ".pi/agent"
    runtime_root_name: str = "pi-runtime"
    session_prefix: str = "local-pi"

    def prepare_home(
        self,
        *,
        codex_home_root: Path,
        workspace_dir: Path,
        source_auth_path: Path | None = None,
        agent_name: AgentName | None = None,
        reasoning_effort: ReasoningEffortArg = REASONING_EFFORT_UNSET,
    ) -> Path:
        source_auth_path = source_auth_path or self._default_source_auth_path()
        pi_home_dir = codex_home_root / self.home_dir_name
        pi_home_dir.mkdir(parents=True, exist_ok=True)
        (codex_home_root / ".cache").mkdir(parents=True, exist_ok=True)
        (codex_home_root / ".config").mkdir(parents=True, exist_ok=True)
        (codex_home_root / ".tmp").mkdir(parents=True, exist_ok=True)
        if source_auth_path.exists():
            _copy_auth_bundle(source_auth_path, pi_home_dir)
        return pi_home_dir

    def build_env(
        self,
        *,
        task_id: str,
        workspace_dir: Path,
        codex_home_root: Path,
        session_id: str | None = None,
        agent_name: AgentName | None = None,
    ) -> dict[str, str]:
        env = CodexCliProvider.build_env(
            self,
            task_id=task_id,
            workspace_dir=workspace_dir,
            codex_home_root=codex_home_root,
            session_id=session_id,
            agent_name=agent_name,
        )
        env["PI_CODING_AGENT_DIR"] = env["CODEX_HOME"]
        return env

    def _build_exec_argv(
        self,
        *,
        workspace_dir: Path,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> list[str]:
        cmd = [self.binary_name, "--print"]
        if resume_session_id is not None:
            cmd.extend(["--resume", resume_session_id])
        if output_last_message_path is not None:
            output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
        return cmd

    def build_exec_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
        resume_session_id: str | None = None,
        output_last_message_path: Path | None = None,
    ) -> CliInvocation:
        return CliInvocation(
            argv=self._build_exec_argv(
                workspace_dir=workspace_dir,
                yolo=yolo,
                resume_session_id=resume_session_id,
                output_last_message_path=output_last_message_path,
            )
            + [prompt_text],
            prompt_text=prompt_text,
            prompt_transport="positional",
            cwd=workspace_dir,
            resume_session_id=resume_session_id,
            output_last_message_path=output_last_message_path,
        )

    def _build_ui_argv(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> list[str]:
        return [self.binary_name, prompt_text]

    def build_ui_invocation(
        self,
        *,
        workspace_dir: Path,
        prompt_text: str,
        yolo: bool,
    ) -> CliInvocation:
        return CliInvocation(
            argv=self._build_ui_argv(
                workspace_dir=workspace_dir,
                prompt_text=prompt_text,
                yolo=yolo,
            ),
            prompt_text=prompt_text,
            prompt_transport="positional",
            cwd=workspace_dir,
        )

    def build_help_command(self) -> list[str]:
        return [self.binary_name, "--help"]


_CLI_PROVIDER_REGISTRY: dict[str, type[CliProvider]] = {
    "codex": CodexCliProvider,
    "pi": PiCliProvider,
    "qwen": QwenCliProvider,
}


def available_cli_providers() -> list[str]:
    return sorted(_CLI_PROVIDER_REGISTRY)


def _resolve_provider_name(provider_name: str | None) -> str:
    resolved = (provider_name or "qwen").strip().lower()
    if resolved not in _CLI_PROVIDER_REGISTRY:
        raise SystemExit(
            "Unknown CLI provider '{provider}'. Available: {available}".format(
                provider=resolved,
                available=", ".join(available_cli_providers()),
            )
        )
    return resolved


def get_cli_provider(provider_name: str | None = None) -> CliProvider:
    return _CLI_PROVIDER_REGISTRY[_resolve_provider_name(provider_name)]()


_DEFAULT_PROVIDER = CodexCliProvider()


def get_default_cli_provider() -> CliProvider:
    return _DEFAULT_PROVIDER
