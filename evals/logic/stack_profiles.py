from __future__ import annotations

import argparse
import os
import shlex
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path

STACK_PROFILE_INTEGRATION = "integration"
STACK_PROFILE_EVAL = "eval"
DEFAULT_STACK_PROFILE_NAME = STACK_PROFILE_INTEGRATION


@dataclass(frozen=True, slots=True)
class StackProfile:
    name: str
    compose_project_name: str
    controller_host_port: int
    worker_light_host_port: int
    worker_heavy_host_port: int
    worker_renderer_host_port: int
    postgres_host_port: int
    minio_host_port: int
    minio_console_host_port: int
    frontend_host_port: int
    start_frontend: bool
    create_root_log_symlinks: bool
    default_log_dir: Path
    default_archive_dir: Path
    default_worker_sessions_dir: Path

    def host_url_env(self) -> dict[str, str]:
        controller_url = f"http://127.0.0.1:{self.controller_host_port}"
        worker_light_url = f"http://127.0.0.1:{self.worker_light_host_port}"
        worker_heavy_url = f"http://127.0.0.1:{self.worker_heavy_host_port}"
        worker_renderer_url = f"http://127.0.0.1:{self.worker_renderer_host_port}"
        frontend_url = f"http://127.0.0.1:{self.frontend_host_port}"
        s3_endpoint = f"http://127.0.0.1:{self.minio_host_port}"
        postgres_url = f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{self.postgres_host_port}/postgres"
        return {
            "CONTROLLER_URL": controller_url,
            "WORKER_URL": worker_light_url,
            "WORKER_LIGHT_URL": worker_light_url,
            "WORKER_HEAVY_URL": worker_heavy_url,
            "WORKER_RENDERER_URL": worker_renderer_url,
            "FRONTEND_URL": frontend_url,
            "S3_ENDPOINT": s3_endpoint,
            "S3_ENDPOINT_URL": s3_endpoint,
            "POSTGRES_URL": postgres_url,
            "DATABASE_URL": postgres_url,
        }

    def compose_host_port_env(self) -> dict[str, str]:
        return {
            "CONTROLLER_HOST_PORT": str(self.controller_host_port),
            "WORKER_LIGHT_HOST_PORT": str(self.worker_light_host_port),
            "WORKER_HEAVY_HOST_PORT": str(self.worker_heavy_host_port),
            "WORKER_RENDERER_HOST_PORT": str(self.worker_renderer_host_port),
            "POSTGRES_HOST_PORT": str(self.postgres_host_port),
            "MINIO_HOST_PORT": str(self.minio_host_port),
            "MINIO_CONSOLE_HOST_PORT": str(self.minio_console_host_port),
            "FRONTEND_HOST_PORT": str(self.frontend_host_port),
        }

    def profile_env(self, *, root: Path) -> dict[str, str]:
        repo_root = root.expanduser().resolve()
        stack_state_dir = repo_root / "logs" / "stacks" / self.name
        env = {
            "PROBLEMOLOGIST_STACK_PROFILE": self.name,
            "COMPOSE_PROJECT_NAME": self.compose_project_name,
            "PROBLEMOLOGIST_RENDER_PARALLEL_MODALITIES": "false",
            "IS_INTEGRATION_TEST": "true"
            if self.name == STACK_PROFILE_INTEGRATION
            else "false",
            "STACK_STATE_DIR": str(stack_state_dir),
            "STACK_PID_DIR": str(stack_state_dir / "pids"),
            "STACK_DEFAULT_LOG_DIR": str(repo_root / self.default_log_dir),
            "STACK_DEFAULT_ARCHIVE_DIR": str(repo_root / self.default_archive_dir),
            "STACK_DEFAULT_WORKER_SESSIONS_DIR": str(self.default_worker_sessions_dir),
            "STACK_START_FRONTEND": "1" if self.start_frontend else "0",
            "STACK_CREATE_ROOT_LOG_SYMLINKS": (
                "1" if self.create_root_log_symlinks else "0"
            ),
            "S3_ACCESS_KEY": "minioadmin",
            "S3_SECRET_KEY": "minioadmin",
            "AWS_ACCESS_KEY_ID": "minioadmin",
            "AWS_SECRET_ACCESS_KEY": "minioadmin",
            "ASSET_S3_BUCKET": "problemologist",
            "BACKUP_S3_BUCKET": "problemologist-backup",
        }
        env.update(self.compose_host_port_env())
        env.update(self.host_url_env())
        return env

    def shell_exports(self, *, root: Path) -> str:
        lines: list[str] = []
        for key, value in self.profile_env(root=root).items():
            lines.append(f"export {key}={shlex.quote(value)}")
        return "\n".join(lines)


STACK_PROFILES: dict[str, StackProfile] = {
    STACK_PROFILE_INTEGRATION: StackProfile(
        name=STACK_PROFILE_INTEGRATION,
        compose_project_name="problemologist-integration",
        controller_host_port=18000,
        worker_light_host_port=18001,
        worker_heavy_host_port=18002,
        worker_renderer_host_port=18003,
        postgres_host_port=15432,
        minio_host_port=19000,
        minio_console_host_port=19001,
        frontend_host_port=15173,
        start_frontend=True,
        create_root_log_symlinks=True,
        default_log_dir=Path("logs/manual_run"),
        default_archive_dir=Path("logs/archives"),
        default_worker_sessions_dir=Path("/tmp/pb-sessions-integration"),
    ),
    STACK_PROFILE_EVAL: StackProfile(
        name=STACK_PROFILE_EVAL,
        compose_project_name="problemologist-eval",
        controller_host_port=28000,
        worker_light_host_port=28001,
        worker_heavy_host_port=28002,
        worker_renderer_host_port=28003,
        postgres_host_port=25432,
        minio_host_port=29000,
        minio_console_host_port=29001,
        frontend_host_port=25173,
        start_frontend=False,
        create_root_log_symlinks=False,
        default_log_dir=Path("logs/stacks/eval/manual_run"),
        default_archive_dir=Path("logs/stacks/eval/archives"),
        default_worker_sessions_dir=Path("/tmp/pb-sessions-eval"),
    ),
}


def resolve_stack_profile(profile_name: str | None = None) -> StackProfile:
    candidate = profile_name or os.getenv("PROBLEMOLOGIST_STACK_PROFILE", "")
    normalized = candidate.strip().lower() if candidate else DEFAULT_STACK_PROFILE_NAME
    try:
        return STACK_PROFILES[normalized]
    except KeyError as exc:
        allowed = ", ".join(sorted(STACK_PROFILES))
        raise ValueError(
            f"Unknown stack profile '{candidate}'. Expected one of: {allowed}"
        ) from exc


def apply_stack_profile_env(
    profile_name: str | None = None,
    *,
    env: MutableMapping[str, str] | None = None,
    root: Path | None = None,
) -> StackProfile:
    profile = resolve_stack_profile(profile_name)
    target_env: MutableMapping[str, str] = env if env is not None else os.environ
    repo_root = (root or Path.cwd()).expanduser().resolve()
    target_env.update(profile.profile_env(root=repo_root))
    return profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render stack profile exports.")
    parser.add_argument(
        "--profile",
        default=None,
        help="Stack profile to render. Defaults to PROBLEMOLOGIST_STACK_PROFILE or integration.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root used for relative log/archive paths. Defaults to the current directory.",
    )
    parser.add_argument(
        "--format",
        choices=("shell",),
        default="shell",
        help="Output format for exports.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root else Path.cwd().resolve()
    profile = resolve_stack_profile(args.profile)
    if args.format == "shell":
        print(profile.shell_exports(root=root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
