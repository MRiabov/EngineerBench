import asyncio
from pathlib import Path

from structlog import get_logger

from controller.clients.backend import RemoteFilesystemBackend
from shared.agent_templates import load_common_template_files
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName

logger = get_logger(__name__)

TEMPLATE_REPOS_ROOT = (
    Path(__file__).resolve().parents[2] / "shared" / "assets" / "template_repos"
)


def _normalize_remote_path(path: str) -> str:
    """Normalize worker paths so '/a/b.md' and 'a/b.md' compare equally."""
    return path.strip().lstrip("/").rstrip("/")


def _extract_entry_path(entry: object) -> str | None:
    """Extract a path string from ls entry payloads (dict or model-like)."""
    if isinstance(entry, dict):
        value = entry.get("path")
        return str(value) if value is not None else None
    value = getattr(entry, "path", None)
    return str(value) if value is not None else None


def _role_template_files(agent_name: AgentName) -> dict[str, str]:
    """Load role-specific starter files that are not common boilerplate."""
    role_mappings: dict[AgentName, dict[str, str]] = {
        AgentName.ENGINEER_PLANNER: {
            "engineer/engineering_plan.md": "engineering_plan.md",
            "engineer/todo.md": "todo.md",
            "engineer/assembly_definition.yaml": "assembly_definition.yaml",
            "engineer/benchmark_plan_evidence_script.py": (
                "benchmark_plan_evidence_script.py"
            ),
            "engineer/solution_plan_evidence_script.py": (
                "solution_plan_evidence_script.py"
            ),
        },
        AgentName.ENGINEER_CODER: {
            "engineer/benchmark_assembly_definition.yaml": (
                "benchmark_assembly_definition.yaml"
            ),
        },
        AgentName.ENGINEER_PLAN_REVIEWER: {
            "engineer/benchmark_assembly_definition.yaml": (
                "benchmark_assembly_definition.yaml"
            ),
        },
        AgentName.ENGINEER_EXECUTION_REVIEWER: {
            "engineer/benchmark_assembly_definition.yaml": (
                "benchmark_assembly_definition.yaml"
            ),
        },
        AgentName.BENCHMARK_PLANNER: {
            "benchmark_generator/benchmark_plan.md": "benchmark_plan.md",
            "benchmark_generator/todo.md": "todo.md",
            "benchmark_generator/benchmark_definition.yaml": "benchmark_definition.yaml",
            "benchmark_generator/benchmark_assembly_definition.yaml": "benchmark_assembly_definition.yaml",
            "benchmark_generator/benchmark_plan_evidence_script.py": (
                "benchmark_plan_evidence_script.py"
            ),
        },
    }

    mapping = role_mappings.get(agent_name)
    if mapping is None:
        return {}

    loaded: dict[str, str] = {}
    for template_path, remote_name in mapping.items():
        source_path = TEMPLATE_REPOS_ROOT / template_path
        if not source_path.is_file():
            raise FileNotFoundError(f"Template file not found: {source_path}")
        loaded[remote_name] = source_path.read_text(encoding="utf-8")
    return loaded


async def _write_template(
    backend: RemoteFilesystemBackend,
    template_name: str,
    template_content: str,
    target_path: str,
) -> None:
    """Write a local template payload to the remote worker."""
    try:
        await backend.awrite(target_path, template_content)
        logger.info("wrote_template", path=template_name, target=target_path)
    except Exception as e:
        logger.error(
            "failed_to_write_template",
            path=template_name,
            target=target_path,
            error=str(e),
            session_id=backend.client.session_id,
        )


def _can_write_template(
    backend: RemoteFilesystemBackend, agent_name: AgentName, target_path: str
) -> bool:
    policy = getattr(getattr(backend, "client", None), "policy", None)
    if policy is None:
        return True

    try:
        return bool(policy.check_permission(agent_name, "write", target_path))
    except Exception:
        return True


async def seed_current_role_manifest(
    backend: RemoteFilesystemBackend,
    agent_name: AgentName,
) -> bool:
    """Refresh the backend-owned current-role manifest for the active workspace."""
    current_role_path = ".manifests/current_role.json"
    worker_client = getattr(backend.client, "client", backend.client)
    try:
        await worker_client.write_file(
            current_role_path,
            current_role_manifest_json(agent_name),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        logger.info(
            "current_role_manifest_seeded",
            agent_name=agent_name,
            path=current_role_path,
        )
        return True
    except Exception as exc:
        logger.warning(
            "current_role_manifest_seed_failed",
            agent_name=agent_name,
            path=current_role_path,
            error=str(exc),
        )
        return False


async def initialize_agent_files(
    backend: RemoteFilesystemBackend, agent_name: AgentName, overwrite: bool = False
) -> None:
    """
    Initializes the file system for a given agent with templates and directories.
    If overwrite=False (default), it skips files that already exist.
    """
    logger.info("initializing_agent_files", agent_name=agent_name)

    # 1. Check existing files to avoid overwriting pre-seeded evaluation data
    existing_files = set()
    try:
        # als_info(".") should list the root directory where these files go
        info = await backend.als_info(".")
        existing_files = {
            normalized
            for item in info
            if (path := _extract_entry_path(item))
            and (normalized := _normalize_remote_path(path))
        }
        logger.info("found_existing_files", count=len(existing_files))
    except Exception as e:
        logger.warning("failed_to_list_existing_files", error=str(e))

    tasks = []

    template_files = load_common_template_files()
    template_files.pop("manufacturing_config.yaml", None)
    template_files.update(_role_template_files(agent_name))
    for remote_name, content in template_files.items():
        if not overwrite and _normalize_remote_path(remote_name) in existing_files:
            logger.info("skipping_existing_file", path=remote_name)
            continue
        if not _can_write_template(backend, agent_name, remote_name):
            logger.info("skipping_disallowed_template", path=remote_name)
            continue
        tasks.append(_write_template(backend, remote_name, content, remote_name))

    if tasks:
        await asyncio.gather(*tasks)

    await seed_current_role_manifest(backend, agent_name)

    # Skills are mounted read-only at /skills on worker side; initialization must not
    # attempt to write there through normal agent permissions.
    available_skills = 0
    if hasattr(backend, "als_info"):
        try:
            entries = await backend.als_info("/skills")
            available_skills = len(
                [entry for entry in entries if entry.get("is_dir", False)]
            )
        except Exception as e:
            logger.warning("failed_to_list_skills_mount", error=str(e))

    logger.info(
        "agent_files_initialized",
        agent_name=agent_name,
        file_count=len(tasks),
        skills_available=available_skills,
    )


async def seed_manufacturing_config(
    backend: RemoteFilesystemBackend,
    *,
    overwrite: bool = False,
    existing_files: set[str] | None = None,
) -> bool:
    """
    Seed the workspace manufacturing config as a system write.

    Planner workspaces need a real pricing source but should not be granted
    normal edit permission over that file.
    """
    manufacturing_config_path = (
        Path(__file__).resolve().parents[2]
        / "worker_heavy"
        / "workbenches"
        / "manufacturing_config.yaml"
    )
    if not manufacturing_config_path.is_file():
        return False
    manufacturing_config_content = manufacturing_config_path.read_text(encoding="utf-8")

    config_path = _normalize_remote_path("manufacturing_config.yaml")
    if existing_files is None:
        existing_files = set()
        try:
            info = await backend.als_info(".")
            existing_files = {
                normalized
                for item in info
                if (path := _extract_entry_path(item))
                and (normalized := _normalize_remote_path(path))
            }
        except Exception:
            existing_files = set()

    if not overwrite and config_path in existing_files:
        return False

    worker_client = getattr(backend.client, "client", backend.client)
    await worker_client.write_file(
        "manufacturing_config.yaml",
        manufacturing_config_content,
        overwrite=True,
        bypass_agent_permissions=True,
    )
    return True
