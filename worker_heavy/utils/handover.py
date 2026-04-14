import os
import uuid
from hashlib import sha256
from pathlib import Path

import structlog
from build123d import Compound, export_step

from shared.current_role import current_role_agent_name
from shared.enums import AgentName
from shared.git_utils import repo_revision
from shared.models.schemas import BenchmarkDefinition
from shared.models.simulation import SimulationResult
from shared.script_contracts import BENCHMARK_SCRIPT_PATH, plan_path_for_reviewer_stage
from shared.workers.loader import load_component_from_script
from shared.workers.schema import (
    LEGACY_REVIEWER_STAGE_ALIASES,
    BenchmarkAttachmentPolicySummary,
    RenderManifest,
    ReviewManifest,
    ValidationResultRecord,
)
from worker_heavy.utils.dfm import (
    resolve_requested_quantity,
    validate_and_price_assembly,
)
from worker_heavy.utils.file_validation import (
    _assembly_script_expected_identity_pairs,
    _assembly_script_expected_tokens,
    _benchmark_script_expected_identity_pairs,
    _benchmark_script_expected_tokens,
    validate_component_inventory_exactness,
    validate_declared_planner_cost_contract,
    validate_environment_attachment_contract,
    validate_planner_handoff_cross_contract,
)
from worker_heavy.utils.rendering import prerender_24_views
from worker_heavy.utils.validation import (
    validate_benchmark_submission_simulation_bounds,
)
from worker_heavy.workbenches.config import load_required_merged_config

logger = structlog.get_logger(__name__)


def _normalize_reviewer_stage(reviewer_stage: AgentName | str) -> AgentName:
    reviewer_stage_value = (
        reviewer_stage.value
        if isinstance(reviewer_stage, AgentName)
        else str(reviewer_stage).strip()
    )
    legacy_stage = LEGACY_REVIEWER_STAGE_ALIASES.get(reviewer_stage_value)
    if legacy_stage is not None:
        return legacy_stage
    return AgentName(reviewer_stage_value)


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _goal_reached(summary: str) -> bool:
    s = (summary or "").lower()
    return "goal achieved" in s or "green zone" in s or "goal zone" in s


def _benchmark_attachment_policy_summary(
    benchmark_definition: BenchmarkDefinition | None,
) -> list[BenchmarkAttachmentPolicySummary]:
    if benchmark_definition is None:
        return []
    summary: list[BenchmarkAttachmentPolicySummary] = []
    for benchmark_part in benchmark_definition.benchmark_parts:
        metadata = benchmark_part.metadata
        if (
            not metadata.allows_engineer_interaction
            and metadata.attachment_policy is None
        ):
            continue
        summary.append(
            BenchmarkAttachmentPolicySummary(
                part_id=benchmark_part.part_id,
                label=benchmark_part.label,
                allows_engineer_interaction=metadata.allows_engineer_interaction,
                attachment_policy=metadata.attachment_policy,
            )
        )
    return summary


def _is_static_preview_render(path: str) -> bool:
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg"}


def _normalize_render_path(path: str) -> str:
    normalized = str(Path(path))
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _resolve_workspace_path(cwd: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return cwd / path


def _compose_final_submission_component(
    cwd: Path,
    component: Compound,
    *,
    normalized_stage: AgentName,
) -> Compound:
    if normalized_stage == AgentName.BENCHMARK_REVIEWER:
        return component

    benchmark_script_path = cwd / BENCHMARK_SCRIPT_PATH
    if not benchmark_script_path.exists():
        raise ValueError(
            f"{BENCHMARK_SCRIPT_PATH} is missing (required for final submission renders)"
        )

    benchmark_component = load_component_from_script(
        benchmark_script_path,
        session_root=cwd,
    )

    def _leaf_labels(part: Compound) -> set[str]:
        labels: set[str] = set()

        def _visit(node: Compound) -> None:
            children = list(getattr(node, "children", []) or [])
            if not children:
                label = str(getattr(node, "label", "") or "").strip()
                if label:
                    labels.add(label)
                return
            for child in children:
                _visit(child)

        _visit(part)
        return labels

    def _filter_component(part: Compound, excluded_labels: set[str]) -> Compound | None:
        children = list(getattr(part, "children", []) or [])
        if not children:
            label = str(getattr(part, "label", "") or "").strip()
            if label and label in excluded_labels:
                return None
            return part

        kept_children = []
        for child in children:
            filtered = _filter_component(child, excluded_labels)
            if filtered is not None:
                kept_children.append(filtered)
        if not kept_children:
            return None

        rebuilt = Compound(children=kept_children)
        rebuilt = rebuilt.located(part.location)
        label = getattr(part, "label", None)
        if label:
            rebuilt.label = str(label)
        metadata = getattr(part, "metadata", None)
        if metadata is not None:
            rebuilt.metadata = metadata
        return rebuilt

    benchmark_leaves = _filter_component(benchmark_component, _leaf_labels(component))
    combined_children = [
        child for child in (benchmark_leaves, component) if child is not None
    ]
    combined_component = Compound(children=combined_children)
    combined_label = getattr(benchmark_component, "label", None) or getattr(
        component, "label", None
    )
    if combined_label:
        combined_component.label = str(combined_label)
    return combined_component


def _derived_episode_id(session_id: str | None) -> str | None:
    if not session_id:
        return None
    try:
        return str(uuid.UUID(session_id))
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))


def _validate_render_manifest_bundle(
    *, renders_dir: Path, render_paths: list[str]
) -> None:
    expected_render_paths = {
        _normalize_render_path(path)
        for path in render_paths
        if _is_static_preview_render(path)
    }
    if not expected_render_paths:
        return

    bundle_roots = {
        renders_dir.parent / Path(path.lstrip("/")).parent
        for path in expected_render_paths
    }
    manifest_path = None
    for candidate_root in sorted(bundle_roots):
        candidate_manifest = candidate_root / "render_manifest.json"
        if candidate_manifest.exists():
            manifest_path = candidate_manifest
            break
    if manifest_path is None:
        missing_render_files = sorted(
            path
            for path in expected_render_paths
            if not (renders_dir.parent / path.lstrip("/")).exists()
        )
        if missing_render_files:
            raise ValueError(
                f"latest render bundle is missing render files: {missing_render_files}"
            )
        raise ValueError(
            "bundle-local render_manifest.json missing for latest render bundle"
        )

    try:
        render_manifest = RenderManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise ValueError(
            f"bundle-local render_manifest.json is invalid: {exc}"
        ) from exc

    if not render_manifest.revision:
        raise ValueError("bundle-local render_manifest.json revision missing")
    current_revision = _latest_git_revision(renders_dir.parent)
    if not current_revision:
        raise ValueError(
            "Unable to determine current repository git revision for latest "
            "render bundle validation."
        )
    if render_manifest.revision.strip().lower() != current_revision:
        raise ValueError(
            "bundle-local render_manifest.json is out of sync with the latest preview "
            "bundle: revision mismatch: "
            f"manifest={render_manifest.revision.strip().lower()} "
            f"latest={current_revision}"
        )

    details: list[str] = []
    actual_render_paths = {
        _normalize_render_path(path)
        for path in render_manifest.artifacts.keys()
        if _is_static_preview_render(path)
    }
    if actual_render_paths == expected_render_paths:
        preview_paths = {
            _normalize_render_path(path)
            for path in render_manifest.preview_evidence_paths
            if _is_static_preview_render(path)
        }
        if preview_paths == expected_render_paths:
            return
        details.append(
            "preview evidence paths mismatch: "
            f"manifest={sorted(preview_paths)} expected={sorted(expected_render_paths)}"
        )

    missing = sorted(expected_render_paths - actual_render_paths)
    unexpected = sorted(actual_render_paths - expected_render_paths)
    if missing:
        details.append(f"missing entries: {missing}")
    if unexpected:
        details.append(f"unexpected entries: {unexpected}")

    if details:
        raise ValueError(
            "bundle-local render_manifest.json is out of sync with the latest preview "
            "bundle: " + "; ".join(details)
        )


def _latest_git_revision(cwd: Path) -> str | None:
    return repo_revision(cwd) or repo_revision(Path(__file__).resolve().parents[2])


def _resolve_submission_assembly_definition(
    cwd: Path, reviewer_stage: AgentName
) -> tuple[Path, str]:
    """Pick the stage-correct assembly definition artifact for review handover."""
    if reviewer_stage == AgentName.BENCHMARK_REVIEWER:
        rel_path = "benchmark_assembly_definition.yaml"
    else:
        rel_path = "assembly_definition.yaml"
    return cwd / rel_path, rel_path


def _planner_role_for_reviewer_stage(reviewer_stage: AgentName) -> AgentName:
    if reviewer_stage == AgentName.BENCHMARK_REVIEWER:
        return AgentName.BENCHMARK_PLANNER
    return AgentName.ENGINEER_PLANNER


def _expected_submission_stage_for_current_role(
    current_role: AgentName,
) -> AgentName | None:
    if current_role in {
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_REVIEWER,
    }:
        return AgentName.BENCHMARK_REVIEWER
    if current_role in {
        AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }:
        return AgentName.ENGINEER_EXECUTION_REVIEWER
    return None


def submit_for_review(
    component: Compound,
    cwd: Path = Path(),
    session_id: str | None = None,
    reviewer_stage: AgentName = AgentName.ENGINEER_EXECUTION_REVIEWER,
    episode_id: str | None = None,
    script_path: str | Path = "script.py",
):
    """
    Standardized handover from Coder to Reviewer.
    Logic:
    - Persist temporary assets to the /renders/ folder.
    - Trigger a LangGraph event or update shared state for the Reviewer node.
    """
    logger.info(
        "handover_started", cwd=str(cwd), files=os.listdir(cwd), session_id=session_id
    )
    normalized_stage = _normalize_reviewer_stage(reviewer_stage)
    allowed_stages = {
        AgentName.BENCHMARK_REVIEWER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }
    if normalized_stage not in allowed_stages:
        raise ValueError(f"Unsupported reviewer_stage: {reviewer_stage}")

    current_role = current_role_agent_name(cwd)
    expected_stage = _expected_submission_stage_for_current_role(current_role)
    if expected_stage is None:
        raise ValueError(
            "Current-role manifest names an unsupported submission role: "
            f"{current_role.value}"
        )
    if expected_stage != normalized_stage:
        raise ValueError(
            "Current-role manifest mismatch for submission: "
            f"expected reviewer_stage={expected_stage}, found {normalized_stage} "
            f"for current_role={current_role.value}"
        )

    renders_dir = cwd / os.getenv("RENDERS_DIR", "renders")
    manifests_dir = cwd / ".manifests"

    # 1. Validate mandatory base files (INT-005)

    plan_artifact_name = plan_path_for_reviewer_stage(normalized_stage).as_posix()
    legacy_plan_artifact_name = "plan.md"

    # benchmark_plan.md / engineering_plan.md
    plan_path = cwd / plan_artifact_name
    plan_content: str | None = None
    if not plan_path.exists():
        plan_path = cwd / legacy_plan_artifact_name
    if plan_path.exists():
        from .file_validation import validate_plan_md_structure

        plan_content = plan_path.read_text(encoding="utf-8")
        plan_type = (
            "benchmark"
            if normalized_stage == AgentName.BENCHMARK_REVIEWER
            else "engineering"
        )
        is_valid, errors = validate_plan_md_structure(
            plan_content, plan_type=plan_type, session_id=session_id
        )
        if not is_valid:
            logger.warning(
                "plan_md_invalid",
                plan_type=plan_type,
                violations=errors,
                session_id=session_id,
            )
            raise ValueError(f"{plan_artifact_name} invalid: {errors}")
    else:
        logger.warning("plan_md_missing", session_id=session_id)
        raise ValueError(f"{plan_artifact_name} is missing (required for submission)")

    # todo.md
    todo_path = cwd / "todo.md"
    if todo_path.exists():
        from shared.workers.markdown_validator import validate_todo_md

        todo_content = todo_path.read_text(encoding="utf-8")
        todo_result = validate_todo_md(todo_content, require_completion=True)
        if not todo_result.is_valid:
            logger.warning(
                "todo_md_invalid",
                violations=todo_result.violations,
                session_id=session_id,
            )
            raise ValueError(f"todo.md invalid: {todo_result.violations}")
    else:
        logger.warning("todo_md_missing", session_id=session_id)
        raise ValueError("todo.md is missing (required for submission)")

    # benchmark_definition.yaml
    objectives_path = cwd / "benchmark_definition.yaml"
    benchmark_definition = None
    if objectives_path.exists():
        from .file_validation import validate_benchmark_definition_yaml

        objectives_content = objectives_path.read_text(encoding="utf-8")
        is_valid, result = validate_benchmark_definition_yaml(
            objectives_content, session_id=session_id
        )
        if not is_valid:
            logger.warning(
                "benchmark_definition_yaml_invalid",
                errors=result,
                session_id=session_id,
            )
            raise ValueError(f"benchmark_definition.yaml invalid: {result}")
        benchmark_definition = result

        # INT-015: Verify immutability
        from .file_validation import validate_immutability

        is_immutable, error_msg = validate_immutability(
            objectives_path, session_id=session_id
        )
        if not is_immutable:
            logger.warning("benchmark_definition_yaml_modified", session_id=session_id)
            raise ValueError(f"benchmark_definition.yaml violation: {error_msg}")
    else:
        logger.warning("benchmark_definition_yaml_missing", session_id=session_id)
        raise ValueError(
            "benchmark_definition.yaml is missing (required for submission)"
        )

    # Stage-specific assembly_definition artifact
    cost_path, assembly_definition_name = _resolve_submission_assembly_definition(
        cwd, normalized_stage
    )
    if cost_path.exists():
        from .file_validation import validate_assembly_definition_yaml

        cost_content = cost_path.read_text(encoding="utf-8")
        custom_config_path = cwd / "manufacturing_config.yaml"
        is_valid, estimation = validate_assembly_definition_yaml(
            cost_content,
            session_id=session_id,
            manufacturing_config=load_required_merged_config(custom_config_path),
            exact_weight=cost_path.name == "assembly_definition.yaml",
        )
        if not is_valid:
            logger.warning(
                f"{cost_path.stem}_yaml_invalid",
                errors=estimation,
                session_id=session_id,
            )
            raise ValueError(f"{assembly_definition_name} invalid: {estimation}")
    else:
        logger.warning(f"{cost_path.stem}_yaml_missing", session_id=session_id)
        raise ValueError(
            f"{assembly_definition_name} is missing (required for submission)"
        )

    # 2. Verify prior validation (INT-018) for current script revision
    script_path = _resolve_workspace_path(cwd, str(script_path))
    if not script_path.exists():
        logger.warning("script_missing_for_handover", session_id=session_id)
        raise ValueError(f"{script_path.name} is missing (required for submission)")
    script_mtime = script_path.stat().st_mtime
    script_sha256 = _sha256_file(script_path)

    # 3. Perform DFM + Geometry Checks (INT-019)
    renders_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    custom_config_path = cwd / "manufacturing_config.yaml"
    dfm_config = load_required_merged_config(custom_config_path)

    objectives_raw = objectives_path.read_text()
    is_valid, objectives_result = validate_benchmark_definition_yaml(
        objectives_raw,
        session_id=session_id,
    )
    if not is_valid:
        raise ValueError(
            "benchmark_definition.yaml invalid: " + "; ".join(objectives_result)
        )
    objectives_model = objectives_result
    simulation_bounds_error = validate_benchmark_submission_simulation_bounds(
        objectives_model
    )
    if simulation_bounds_error:
        logger.warning(
            "benchmark_simulation_bounds_invalid",
            error=simulation_bounds_error,
            session_id=session_id,
        )
        raise ValueError(simulation_bounds_error)
    requested_quantity = resolve_requested_quantity(
        benchmark_definition=objectives_model
    )
    attachment_errors = validate_environment_attachment_contract(
        benchmark_definition=objectives_model,
        assembly_definition=estimation,
    )
    if attachment_errors:
        logger.warning(
            "environment_attachment_contract_invalid",
            errors=attachment_errors,
            session_id=session_id,
        )
        raise ValueError(
            "Attachment contract violation: " + "; ".join(attachment_errors)
        )
    cost_errors = validate_declared_planner_cost_contract(
        assembly_definition=estimation,
        manufacturing_config=dfm_config,
    )
    if cost_errors:
        logger.warning(
            "planner_cost_contract_invalid",
            errors=cost_errors,
            session_id=session_id,
        )
        raise ValueError("Pricing contract violation: " + "; ".join(cost_errors))

    validation_results_path = cwd / "validation_results.json"
    if not validation_results_path.exists():
        logger.warning("prior_validation_missing", session_id=session_id)
        raise ValueError(
            "Prior validation missing. Call /benchmark/validate or /engineering/validate before submission."
        )
    validation_record = ValidationResultRecord.model_validate_json(
        validation_results_path.read_text(encoding="utf-8")
    )
    if not validation_record.success:
        logger.warning("prior_validation_failed", session_id=session_id)
        raise ValueError(
            "Prior validation failed. Fix validation errors before submission."
        )
    if validation_record.script_sha256 != script_sha256:
        logger.warning(
            "prior_validation_stale_for_script",
            session_id=session_id,
            validation_script_sha256=validation_record.script_sha256,
            current_script_sha256=script_sha256,
        )
        raise ValueError(
            "Prior validation is stale for current script revision. Re-run validate."
        )

    component_inventory_tokens = (
        _benchmark_script_expected_tokens(
            benchmark_definition=objectives_model,
            assembly_definition=estimation,
        )
        if normalized_stage == AgentName.BENCHMARK_REVIEWER
        else _assembly_script_expected_tokens(estimation)
    )
    component_inventory_pairs = (
        _benchmark_script_expected_identity_pairs(
            benchmark_definition=objectives_model,
            assembly_definition=estimation,
        )
        if normalized_stage == AgentName.BENCHMARK_REVIEWER
        else _assembly_script_expected_identity_pairs(estimation)
    )
    inventory_errors = validate_component_inventory_exactness(
        component=component,
        expected_tokens=component_inventory_tokens,
        artifact_name=script_path.name,
        expected_identity_pairs=component_inventory_pairs,
    )
    if inventory_errors:
        logger.warning(
            "submission_inventory_exactness_failed",
            violations=inventory_errors,
            session_id=session_id,
        )
        raise ValueError(
            "Submission rejected (Inventory exactness): " + "; ".join(inventory_errors)
        )

    build_zone = objectives_model.objectives.build_zone
    constraints = objectives_model.constraints

    manufactured_labels = {part.part_name for part in estimation.manufactured_parts}
    if normalized_stage != AgentName.BENCHMARK_REVIEWER:
        from shared.workers.workbench_models import ManufacturingMethod

        method = (
            estimation.manufactured_parts[0].manufacturing_method
            if estimation.manufactured_parts
            else ManufacturingMethod.CNC
        )
        validation_result = validate_and_price_assembly(
            component,
            dfm_config,
            assembly_definition=estimation,
            part_labels=manufactured_labels or None,
            build_zone=build_zone,
            session_id=session_id,
            quantity=requested_quantity,
            default_method=method,
        )

        if not validation_result.is_manufacturable:
            logger.warning(
                "submission_dfm_failed",
                violations=validation_result.violations,
                session_id=session_id,
            )
            raise ValueError(
                f"Submission rejected (DFM): {validation_result.violations}"
            )
        if constraints:
            if (
                constraints.max_unit_cost
                and validation_result.unit_cost > constraints.max_unit_cost
            ):
                msg = (
                    f"Unit cost at requested quantity {requested_quantity} "
                    f"(${validation_result.unit_cost:.2f}) exceeds limit "
                    f"${constraints.max_unit_cost:.2f}"
                )
                logger.warning(
                    "submission_cost_limit_exceeded",
                    cost=validation_result.unit_cost,
                    limit=constraints.max_unit_cost,
                    session_id=session_id,
                )
                raise ValueError(f"Submission rejected (Cost): {msg}")

            weight_g = validation_result.weight_g
            if constraints.max_weight_g and weight_g > constraints.max_weight_g:
                msg = (
                    f"Weight at requested quantity {requested_quantity} "
                    f"({weight_g:.1f}g) exceeds limit "
                    f"{constraints.max_weight_g:.1f}g"
                )
                logger.warning(
                    "submission_weight_limit_exceeded",
                    weight=weight_g,
                    limit=constraints.max_weight_g,
                    session_id=session_id,
                )
                raise ValueError(f"Submission rejected (Weight): {msg}")

    planner_node_type = (
        AgentName.BENCHMARK_PLANNER
        if normalized_stage == AgentName.BENCHMARK_REVIEWER
        else AgentName.ENGINEER_PLANNER
    )

    cross_contract_errors = validate_planner_handoff_cross_contract(
        benchmark_definition=objectives_model,
        assembly_definition=estimation,
        manufacturing_config=dfm_config,
        planner_node_type=planner_node_type,
        plan_text=plan_content,
    )
    if cross_contract_errors:
        logger.warning(
            "planner_handoff_cross_contract_invalid",
            errors=cross_contract_errors,
            session_id=session_id,
        )
        raise ValueError(
            "benchmark_assembly_definition.yaml invalid: "
            + "; ".join(cross_contract_errors)
        )

    # 3b. Verify prior simulation for current script revision and objective success.
    simulation_results_path = cwd / "simulation_result.json"
    if not simulation_results_path.exists():
        logger.warning("prior_simulation_missing", session_id=session_id)
        raise ValueError(
            "Prior simulation missing. Call /benchmark/simulate or /engineering/simulate first."
        )
    simulation_result = SimulationResult.model_validate_json(
        simulation_results_path.read_text(encoding="utf-8")
    )
    if not simulation_result.success:
        logger.warning(
            "prior_simulation_failed",
            summary=simulation_result.summary,
            session_id=session_id,
        )
        raise ValueError(
            "Prior simulation failed. Submission requires a successful simulation."
        )
    if normalized_stage != AgentName.BENCHMARK_REVIEWER and not _goal_reached(
        simulation_result.summary
    ):
        logger.warning(
            "goal_not_reached_in_simulation",
            summary=simulation_result.summary,
            session_id=session_id,
        )
        raise ValueError(
            "Simulation did not report goal completion (green/goal zone reached)."
        )
    if simulation_results_path.stat().st_mtime < script_mtime:
        logger.warning("prior_simulation_stale_for_script", session_id=session_id)
        raise ValueError(
            "Prior simulation is stale for current script revision. Re-run simulate."
        )

    resolved_session_id = session_id or os.getenv("SESSION_ID", "default")
    resolved_episode_id = (
        episode_id
        or os.getenv("EPISODE_ID")
        or _derived_episode_id(resolved_session_id)
    )

    # 4. Persist artifacts
    render_paths: list[str] = []
    for raw_render_path in simulation_result.render_paths:
        src_path = _resolve_workspace_path(cwd, raw_render_path)
        if not src_path.exists() or not src_path.is_file():
            logger.warning(
                "submission_render_missing",
                render_path=str(src_path),
                session_id=session_id,
            )
            continue
        render_rel_path = Path(raw_render_path)
        if render_rel_path.is_absolute():
            try:
                render_rel_path = render_rel_path.relative_to(cwd)
            except ValueError:
                render_rel_path = Path("renders") / src_path.name
        dest_path = cwd / render_rel_path
        if src_path.resolve() != dest_path.resolve():
            import shutil

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src_path, dest_path)
        render_paths.append(str(render_rel_path))

    import shutil

    persistent_bundle_subdir = (
        "benchmark_renders"
        if normalized_stage == AgentName.BENCHMARK_REVIEWER
        else "final_solution_submission_renders"
    )
    persistent_bundle_dir = renders_dir / persistent_bundle_subdir
    render_component = _compose_final_submission_component(
        cwd,
        component,
        normalized_stage=normalized_stage,
    )
    # Commit the substantive submission snapshot before generating the final
    # persisted bundle so the render manifest and review manifest can share the
    # same latest revision.
    from shared.git_utils import commit_submission_attempt as _commit_submission

    _commit_submission(cwd, "handover: persist submission artifacts")

    revision = _latest_git_revision(cwd)
    if not revision:
        raise ValueError(
            "Unable to determine current repository git revision for review manifest."
        )
    persistent_bundle_render_paths = prerender_24_views(
        render_component,
        output_dir=str(persistent_bundle_dir),
        workspace_root=cwd,
        objectives=benchmark_definition,
        session_id=resolved_session_id,
        smoke_test_mode=os.getenv("SMOKE_TEST_MODE") == "1",
        revision=revision,
        environment_version=estimation.version,
    )
    render_paths = persistent_bundle_render_paths

    cad_path = persistent_bundle_dir / "model.step"
    export_step(render_component, str(cad_path))
    if normalized_stage in {
        AgentName.BENCHMARK_REVIEWER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }:
        cad_path_value = None
    else:
        cad_path_value = str(cad_path) if cad_path.exists() else None

    shutil.copy(objectives_path, persistent_bundle_dir / "benchmark_definition.yaml")
    rendered_assembly_definition_path = persistent_bundle_dir / assembly_definition_name
    shutil.copy(cost_path, rendered_assembly_definition_path)

    _validate_render_manifest_bundle(renders_dir=renders_dir, render_paths=render_paths)
    logger.info(
        "render_manifest_bundle_validated",
        count=len(render_paths),
        session_id=session_id,
    )

    logger.info("renders_persisted", count=len(render_paths), session_id=session_id)

    # 5. Create reviewer-stage manifest
    stage_to_manifest = {
        AgentName.BENCHMARK_REVIEWER: "benchmark_review_manifest.json",
        AgentName.ENGINEER_EXECUTION_REVIEWER: "engineering_execution_handoff_manifest.json",
    }
    manifest_name = stage_to_manifest[normalized_stage]
    manifest_path = manifests_dir / manifest_name
    manifest = ReviewManifest(
        status="ready_for_review",
        reviewer_stage=normalized_stage,
        timestamp=os.getenv("TIMESTAMP"),
        session_id=resolved_session_id,
        revision=revision,
        episode_id=resolved_episode_id,
        worker_session_id=resolved_session_id,
        benchmark_episode_id=(
            resolved_episode_id
            if normalized_stage == AgentName.BENCHMARK_REVIEWER
            else None
        ),
        benchmark_worker_session_id=(
            resolved_session_id
            if normalized_stage == AgentName.BENCHMARK_REVIEWER
            else None
        ),
        benchmark_revision=(
            revision if normalized_stage == AgentName.BENCHMARK_REVIEWER else None
        ),
        solution_revision=revision,
        environment_version=estimation.version,
        preview_evidence_paths=render_paths,
        script_path=str(script_path.relative_to(cwd)),
        script_sha256=script_sha256,
        validation_success=validation_record.success,
        validation_timestamp=validation_record.timestamp,
        simulation_success=simulation_result.success,
        simulation_summary=simulation_result.summary,
        simulation_timestamp=simulation_results_path.stat().st_mtime,
        motion_evidence_verified=(
            simulation_result.success
            if normalized_stage == AgentName.BENCHMARK_REVIEWER
            else None
        ),
        goal_reached=(
            None
            if normalized_stage == AgentName.BENCHMARK_REVIEWER
            else _goal_reached(simulation_result.summary)
        ),
        renders=render_paths,
        benchmark_attachment_policy_summary=_benchmark_attachment_policy_summary(
            benchmark_definition
        ),
        mjcf_path=(
            None
            if normalized_stage
            in {
                AgentName.BENCHMARK_REVIEWER,
                AgentName.ENGINEER_EXECUTION_REVIEWER,
            }
            else (
                str(renders_dir / "scene.xml")
                if (renders_dir / "scene.xml").exists()
                else None
            )
        ),
        cad_path=cad_path_value,
        objectives_path=(
            None
            if normalized_stage
            in {
                AgentName.BENCHMARK_REVIEWER,
                AgentName.ENGINEER_EXECUTION_REVIEWER,
            }
            else str(renders_dir / "benchmark_definition.yaml")
        ),
        assembly_definition_path=(
            None
            if normalized_stage
            in {
                AgentName.BENCHMARK_REVIEWER,
                AgentName.ENGINEER_EXECUTION_REVIEWER,
            }
            else str(rendered_assembly_definition_path)
        ),
    )

    manifest_json = manifest.model_dump_json(indent=2, exclude_none=True)
    with manifest_path.open("w", encoding="utf-8") as f:
        f.write(manifest_json)

    # Mirror manifest to renders folder for artifact surfacing.
    synced_manifest_path = renders_dir / manifest_name
    with synced_manifest_path.open("w", encoding="utf-8") as f:
        f.write(manifest_json)

    logger.info(
        "handover_complete",
        manifest=str(manifest_path),
        synced_manifest=str(synced_manifest_path),
        revision=revision,
        session_id=session_id,
    )
    return True
