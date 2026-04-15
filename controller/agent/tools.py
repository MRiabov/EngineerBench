import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path

import yaml

from controller.middleware.remote_fs import EditOp, RemoteFilesystemMiddleware
from controller.observability.middleware_helper import broadcast_file_update
from controller.observability.tracing import record_worker_events
from shared.enums import AgentName
from shared.git_utils import repo_revision
from shared.models.schemas import PlannerSubmissionResult
from shared.observability.schemas import ToolInvocationEvent
from shared.script_contracts import (
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    authored_script_path_for_agent,
    plan_path_for_agent,
)
from shared.workers.schema import (
    PlanReviewManifest,
    PreviewRenderingType,
)


def _derived_episode_id(session_id: str) -> str:
    try:
        return str(uuid.UUID(session_id))
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))


def _workspace_environment_version(content: str) -> str | None:
    try:
        data = yaml.safe_load(content) or {}
    except Exception:
        return None
    version = data.get("version")
    if version is None:
        return None
    version_text = str(version).strip()
    return version_text or None


def _tool_name(tool: Callable) -> str:
    return getattr(tool, "name", getattr(tool, "__name__", str(tool)))


def _runtime_skill_script_path(*relative_parts: str) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    skill_root = repo_root / ".agents" / "skills"
    if skill_root.exists():
        return skill_root.joinpath(*relative_parts)
    return repo_root.joinpath(*relative_parts)


async def run_validate_and_price_script(
    fs: RemoteFilesystemMiddleware,
) -> dict[str, object]:
    """Run the canonical planner pricing script and return a structured result."""
    validator_path = _runtime_skill_script_path(
        "manufacturing-knowledge",
        "scripts",
        "validate_and_price.py",
    )
    response = await fs.run_command(f"python {validator_path}")
    return {
        "ok": response.exit_code == 0 and not response.timed_out,
        "stdout": response.stdout,
        "stderr": response.stderr,
        "exit_code": response.exit_code,
        "timed_out": response.timed_out,
    }


def filter_tools_for_agent(
    fs: RemoteFilesystemMiddleware, tools: list[Callable]
) -> list[Callable]:
    """Filter tool list using per-agent allowlist from config/agents_config.yaml."""
    allowed = fs.policy.get_allowed_tools(fs.agent_role)
    if allowed is None:
        return tools
    return [tool for tool in tools if _tool_name(tool) in allowed]


def get_common_tools(fs: RemoteFilesystemMiddleware, session_id: str) -> list[Callable]:
    """
    Get the set of common tools available to all agents (Engineer, Benchmark, etc.).
    Includes filesystem operations plus render and verification helpers.
    """

    default_script_path = authored_script_path_for_agent(fs.agent_role)

    async def list_files(path: str = "/"):
        """List files in the workspace (filesystem)."""
        return await fs.list_files(path)

    async def read_file(path: str):
        """Read a file's content from the workspace."""
        return await fs.read_file(path)

    async def inspect_media(path: str):
        """Inspect an image/video artifact from the workspace."""
        return await fs.inspect_media(path)

    async def write_file(path: str, content: str, overwrite: bool = False):
        """Write content to a file in the workspace."""
        return await fs.write_file(path, content, overwrite=overwrite)

    async def edit_file(path: str, old_string: str, new_string: str):
        """Edit a file by replacing old_string with new_string."""
        return await fs.edit_file(
            path, [EditOp(old_string=old_string, new_string=new_string)]
        )

    async def grep(pattern: str, path: str | None = None, glob: str | None = None):
        """Search for a pattern in files."""
        return await fs.grep(pattern, path, glob)

    async def execute_command(command: str):
        """Execute a shell command in the workspace runtime."""
        # Record the command execution event
        await record_worker_events(
            episode_id=session_id,
            events=[
                ToolInvocationEvent(
                    tool_name="run_command",
                    arguments={"command": command},
                )
            ],
        )
        return await fs.run_command(command)

    async def inspect_topology(
        target_id: str, script_path: str = default_script_path
    ) -> dict:
        """
        Inspect geometric properties of a selected feature (face, edge, part).
        Returns center, normal, area, and bounding box.
        """
        return await fs.inspect_topology(target_id, script_path)

    async def render_cad(
        script_path: str = default_script_path,
        orbit_pitch: float | list[float] = 45,
        orbit_yaw: float | list[float] = 45,
        rgb: bool | None = None,
        depth: bool | None = None,
        segmentation: bool | None = None,
        payload_path: bool = False,
        rendering_type: PreviewRenderingType | str | None = None,
        smoke_test_mode: bool | None = None,
    ):
        """Render live CAD preview evidence."""
        return await fs.render_cad(
            script_path,
            orbit_pitch=orbit_pitch,
            orbit_yaw=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            rendering_type=rendering_type,
            smoke_test_mode=smoke_test_mode,
        )

    async def verify(
        script_path: str = default_script_path,
        jitter_range: tuple[float, float, float] | None = None,
        num_scenes: int | None = None,
        duration: float | None = None,
        seed: int | None = None,
        smoke_test_mode: bool | None = None,
    ):
        """Run runtime-randomization verification for the current solution."""
        return await fs.verify(
            script_path,
            jitter_range=jitter_range,
            num_scenes=num_scenes,
            duration=duration,
            seed=seed,
            smoke_test_mode=smoke_test_mode,
        )

    tools = [
        list_files,
        read_file,
        inspect_media,
        write_file,
        edit_file,
        grep,
        execute_command,
        inspect_topology,
        render_cad,
        verify,
    ]
    return filter_tools_for_agent(fs, tools)


def get_engineer_tools(
    fs: RemoteFilesystemMiddleware, session_id: str
) -> list[Callable]:
    """
    Get the tools for the Engineer agent.
    """
    return get_common_tools(fs, session_id)


def get_engineer_planner_tools(
    fs: RemoteFilesystemMiddleware,
    session_id: str,
    planner_node_type: AgentName = AgentName.ENGINEER_PLANNER,
) -> list[Callable]:
    """
    Planner-specific toolset for engineer planners.

    Includes explicit `submit_engineering_plan()` so planner completion is an intentional action.
    """
    common_tools = get_common_tools(fs, session_id)

    async def validate_costing_and_price() -> dict:
        """
        Run the planner pricing/validation script against assembly_definition.yaml.
        Use this tool instead of browsing `/scripts` or validator source files.

        Returns:
            {"ok": bool, "stdout": str, "stderr": str, "exit_code": int, "timed_out": bool}
        """
        from worker_heavy.utils.dfm import load_planner_manufacturing_config_from_text

        manufacturing_config_text = await fs.client.read_file_optional(
            "manufacturing_config.yaml", bypass_agent_permissions=True
        )
        if manufacturing_config_text is None:
            return {
                "ok": False,
                "stdout": "",
                "stderr": (
                    "manufacturing_config.yaml missing; planner handoff requires a "
                    "workspace pricing source"
                ),
                "exit_code": 1,
                "timed_out": False,
            }

        try:
            load_planner_manufacturing_config_from_text(manufacturing_config_text)
        except Exception as exc:
            return {
                "ok": False,
                "stdout": "",
                "stderr": (
                    f"manufacturing_config.yaml invalid for planner handoff: {exc}"
                ),
                "exit_code": 1,
                "timed_out": False,
            }

        return await run_validate_and_price_script(fs)

    async def submit_engineering_plan() -> dict:
        """
        Validate planner artifacts and explicitly submit the planning handoff.

        Returns:
            {"ok": bool, "status": "submitted"|"rejected", "errors": [...], "node_type": "..."}
        """
        from worker_heavy.utils.dfm import load_planner_manufacturing_config_from_text
        from worker_heavy.utils.file_validation import (
            validate_benchmark_definition_yaml,
            validate_exact_planner_cost_contract,
            validate_node_output,
        )

        plan_path = plan_path_for_agent(planner_node_type).as_posix()
        required_files = [
            plan_path,
            "todo.md",
            "benchmark_definition.yaml",
            "assembly_definition.yaml",
            SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
        ]
        artifacts: dict[str, str] = {}
        missing_files: list[str] = []

        for rel_path in required_files:
            content = await fs.client.read_file_optional(
                rel_path, bypass_agent_permissions=True
            )
            if content is None:
                missing_files.append(rel_path)
                continue
            if not content.strip():
                missing_files.append(rel_path)
                continue
            artifacts[rel_path] = content

        if missing_files:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[f"Missing required file: {p}" for p in missing_files],
                node_type=planner_node_type,
            )
            return result.model_dump(mode="json")

        custom_config_text = await fs.client.read_file_optional(
            "manufacturing_config.yaml", bypass_agent_permissions=True
        )
        if custom_config_text is None:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[
                    "manufacturing_config.yaml missing; planner handoff requires a "
                    "workspace pricing source"
                ],
                node_type=planner_node_type,
            )
            return result.model_dump(mode="json")

        try:
            manufacturing_config = load_planner_manufacturing_config_from_text(
                custom_config_text
            )
        except Exception as exc:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[
                    f"manufacturing_config.yaml invalid for planner handoff: {exc}"
                ],
                node_type=planner_node_type,
            )
            return result.model_dump(mode="json")

        artifacts["manufacturing_config.yaml"] = custom_config_text

        pricing_result = await run_validate_and_price_script(fs)
        if not pricing_result["ok"]:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[
                    "validate_costing_and_price failed: "
                    + (
                        str(pricing_result["stderr"]).strip()
                        or str(pricing_result["stdout"]).strip()
                        or "pricing script returned a non-zero exit status"
                    )
                ],
                node_type=planner_node_type,
            )
            return result.model_dump(mode="json")

        assembly_definition_text = await fs.read_file_optional(
            "assembly_definition.yaml"
        )
        if assembly_definition_text is None:
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=["Missing required file: assembly_definition.yaml"],
                node_type=planner_node_type,
            )
            return result.model_dump(mode="json")

        artifacts["assembly_definition.yaml"] = assembly_definition_text

        is_valid, errors = validate_node_output(
            AgentName.ENGINEER_PLANNER,
            artifacts,
            manufacturing_config=manufacturing_config,
        )
        if is_valid:
            benchmark_is_valid, benchmark_result = validate_benchmark_definition_yaml(
                artifacts["benchmark_definition.yaml"],
                session_id=fs.client.session_id,
            )
            if not benchmark_is_valid:
                is_valid = False
                errors.extend(
                    [f"benchmark_definition.yaml: {msg}" for msg in benchmark_result]
                )
            assembly_definition = yaml.safe_load(artifacts["assembly_definition.yaml"])
            from shared.models.schemas import AssemblyDefinition

            assembly_model = AssemblyDefinition.model_validate(
                assembly_definition or {}
            )
            cost_errors = validate_exact_planner_cost_contract(
                assembly_definition=assembly_model,
                manufacturing_config=manufacturing_config,
            )
            if cost_errors:
                is_valid = False
                errors.extend([f"pricing_contract: {msg}" for msg in cost_errors])

        if is_valid:
            artifact_hashes = {
                rel_path: hashlib.sha256(content.encode("utf-8")).hexdigest()
                for rel_path, content in artifacts.items()
            }
            manifest = PlanReviewManifest(
                status="ready_for_review",
                reviewer_stage=AgentName.ENGINEER_PLAN_REVIEWER,
                session_id=fs.client.session_id,
                planner_node_type=planner_node_type,
                episode_id=fs.episode_id,
                worker_session_id=fs.client.session_id,
                benchmark_revision=repo_revision(Path(__file__).resolve().parents[2]),
                environment_version=_workspace_environment_version(
                    artifacts["assembly_definition.yaml"]
                ),
                artifact_hashes=artifact_hashes,
            )
            manifest_json = json.dumps(manifest.model_dump(mode="json"), indent=2)
            success = await fs.client.write_file(
                ".manifests/engineering_plan_review_manifest.json",
                manifest_json,
                overwrite=True,
                bypass_agent_permissions=True,
            )
            if success:
                await broadcast_file_update(
                    fs.episode_id,
                    ".manifests/engineering_plan_review_manifest.json",
                    manifest_json,
                )
        result = PlannerSubmissionResult(
            ok=is_valid,
            status="submitted" if is_valid else "rejected",
            errors=errors,
            node_type=planner_node_type,
        )
        return result.model_dump(mode="json")

    planner_common_tools = [
        tool for tool in common_tools if _tool_name(tool) != "execute_command"
    ]
    return filter_tools_for_agent(
        fs,
        [
            *planner_common_tools,
            validate_costing_and_price,
            submit_engineering_plan,
        ],
    )
