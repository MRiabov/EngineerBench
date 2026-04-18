from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import structlog
from build123d import Compound

from shared.enums import AgentName
from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    CompoundMetadata,
    PayloadTrajectoryDefinition,
)
from shared.simulation.schemas import SimulatorBackendType

from .contract import (
    annotate_manufactured_parts,
    coarse_payload_trajectory_dict,
    load_benchmark_definition,
    make_planner_constraints,
    payload_extent_mm,
    payload_trajectory_dict,
    scale_benchmark_definition_to_mm,
    synthetic_benchmark_definition,
)
from .geometry import (
    compound_from_specs,
    parts_from_specs,
    validate_geometry,
    validate_route_clearance,
    validate_route_positions,
)
from .models import ContactHit, PartSpec, RoutePoint, ScenarioConfig
from .paths import (
    REPO_ROOT,
    NotebookLogCapture,
    load_benchmark_build_fn,
    payload_scene_name,
    progress_iter,
    prepare_timestamped_run_dir,
)
from .pipeline import (
    backfill_source_solution,
    build_candidate_assembly,
    build_scene_xml,
    capture_contact_cloud,
    choose_batch_width,
    log_verification_failure_diagnostics,
    prune_segment_specs,
    render_debug_plots,
    render_simulation_video_preview,
    render_startup_workspace_preview,
    role_row,
    stage_bundle_root,
    update_dataset_row,
)
from .size_guard import assert_generator_tree_line_limits
from .text_templates import (
    build_engineering_plan_text,
    build_evidence_script_text,
    build_markdown_templates,
    build_solution_script_text,
    build_todo_text,
)


def _active_stack_profile() -> str:
    return os.getenv("PROBLEMOLOGIST_STACK_PROFILE", "integration").strip().lower()


def _default_worker_heavy_url() -> str:
    if _active_stack_profile() == "eval":
        return "http://127.0.0.1:28002"
    return "http://127.0.0.1:18002"


def _render_simulation_video_disabled() -> bool:
    return os.getenv(
        "PROBLEMOLOGIST_TUBE_GUIDED_SYNTHETIC_DISABLE_RENDER", ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def default_route_points() -> list[RoutePoint]:
    return [
        # Keep the prototype aligned with the source ec-002 route trace so the
        # scratch scaffold has a physically plausible entry lane instead of a
        # disconnected waypoint chain.
        RoutePoint(name="build_zone_start", pos_mm=(-280.0, 0.0, 180.0), t_s=0.0),
        RoutePoint(name="left_capture_lane", pos_mm=(-240.0, 0.0, 160.0), t_s=1.5),
        RoutePoint(name="bypass_corner", pos_mm=(-240.0, 110.0, 120.0), t_s=2.4),
        RoutePoint(name="goal_lane_entry", pos_mm=(-40.0, 110.0, 70.0), t_s=3.6),
        RoutePoint(name="goal_approach", pos_mm=(240.0, 110.0, 50.0), t_s=4.8),
        RoutePoint(name="goal_zone_contact", pos_mm=(325.0, 0.0, 40.0), t_s=6.0),
    ]


def generation_route_points() -> list[RoutePoint]:
    return [
        RoutePoint(name="build_zone_start", pos_mm=(-260.0, 0.0, 24.0), t_s=0.0),
        RoutePoint(name="goal_zone_contact", pos_mm=(-220.0, 0.0, 24.0), t_s=6.0),
    ]


def _overwrite_root_starter_files(root: Path, agent_name: AgentName) -> None:
    for rel_path, content in load_seed_starter_template_files(agent_name).items():
        (root / rel_path).write_text(content, encoding="utf-8")


def synthesize(
    config: ScenarioConfig,
    *,
    run_log_root: Path | None = None,
) -> dict[str, Any]:
    from worker_heavy.simulation.verification import verify_with_jitter

    assert_generator_tree_line_limits(
        REPO_ROOT / "dataset" / "synthetic" / "tube_guided_synthetic_rigid_body_corpus"
    )
    if run_log_root is None:
        run_log_root = prepare_timestamped_run_dir(
            REPO_ROOT / "logs" / "tube_guided_synthetic_rigid_body_corpus"
        )
    logger = structlog.get_logger(__name__)
    logger.info(
        "synthesize_start",
        scenario_id=config.scenario_id,
        source_seed_bundle_dir=str(config.source_seed_bundle_dir),
        planner_row_id=config.planner_row_id,
        coder_row_id=config.coder_row_id,
    )
    benchmark_definition = scale_benchmark_definition_to_mm(
        load_benchmark_definition(config.source_seed_bundle_dir)
    )
    benchmark_build = load_benchmark_build_fn(config.source_seed_bundle_dir)
    benchmark_geometry = benchmark_build()
    payload_extent = payload_extent_mm(benchmark_definition)
    tube_radius_mm = (payload_extent / 2.0) + config.clearance_mm
    corridor_inner_extent_mm = payload_extent + 2.0 * config.clearance_mm
    build_zone_margin_mm = (
        max(tube_radius_mm, config.wall_thickness_mm) + config.route_margin_mm
    )
    logger.info(
        "synthesize_geometry_ready",
        payload_extent_mm=payload_extent,
        tube_radius_mm=tube_radius_mm,
        corridor_inner_extent_mm=corridor_inner_extent_mm,
        build_zone_margin_mm=build_zone_margin_mm,
    )
    logger.info(
        "route_spawn_alignment",
        payload_start_position_mm=[
            float(v) for v in benchmark_definition.payload.start_position_mm
        ],
        first_route_point_mm=[float(v) for v in config.route_points[0].pos_mm],
        goal_route_point_mm=[float(v) for v in config.route_points[-1].pos_mm],
    )

    synthetic_benchmark_dict = synthetic_benchmark_definition(
        benchmark_definition,
        route_points=config.route_points,
        envelope_mm=corridor_inner_extent_mm,
        margin_mm=build_zone_margin_mm,
    )
    synthetic_benchmark = BenchmarkDefinition.model_validate(synthetic_benchmark_dict)
    logger.info(
        "synthetic_spawn_alignment",
        payload_start_position_mm=[
            float(v) for v in synthetic_benchmark.payload.start_position_mm
        ],
        first_route_point_mm=[float(v) for v in config.route_points[0].pos_mm],
        goal_route_point_mm=[float(v) for v in config.route_points[-1].pos_mm],
    )
    validate_route_positions(
        route_points=config.route_points,
        payload_start_position_mm=synthetic_benchmark.payload.start_position_mm,
        goal_zone_mm=synthetic_benchmark.objectives.goal_zone_mm,
    )
    payload_body_name = payload_scene_name(synthetic_benchmark.payload.label)
    route_clearance_errors = validate_route_clearance(
        route_points=config.route_points,
        benchmark_definition=synthetic_benchmark,
        pipe_radius_mm=tube_radius_mm,
        clearance_mm=config.clearance_mm,
    )
    if route_clearance_errors:
        raise RuntimeError("; ".join(route_clearance_errors))

    benchmark_script_text = (
        config.source_seed_bundle_dir / "benchmark_script.py"
    ).read_text(encoding="utf-8")
    benchmark_assembly_text = (
        config.source_seed_bundle_dir / "benchmark_assembly_definition.yaml"
    ).read_text(encoding="utf-8")
    benchmark_bundle_reviews = config.source_seed_bundle_dir / "reviews"
    scratch_root = config.scratch_root / config.scenario_id
    scratch_root.mkdir(parents=True, exist_ok=True)
    planner_root = config.staged_planner_root
    coder_root = config.staged_coder_root

    chosen_backend: SimulatorBackendType | None = None
    chosen_batch_width = None
    chosen_seed = None
    chosen_contact_hits: list[ContactHit] = []
    chosen_specs: list[PartSpec] | None = None
    chosen_pruned_specs: list[PartSpec] | None = None
    chosen_scene_path: Path | None = None
    chosen_verify_result = None
    chosen_pruned_result = None
    simulation_video_summary: dict[str, Any] | None = None

    for retry_seed in progress_iter(config.retry_seeds, "retry seeds"):
        try:
            batch_width = choose_batch_width(config)
            logger.info("retry_start", retry_seed=retry_seed, batch_width=batch_width)
            candidate_specs, candidate_compound = build_candidate_assembly(
                route_points=config.route_points,
                tube_radius_mm=tube_radius_mm,
                clearance_mm=config.clearance_mm,
                wall_thickness_mm=config.wall_thickness_mm,
                max_segment_mm=config.max_segment_mm,
                seed=retry_seed,
                material_id=config.material_id,
            )
            validate_geometry(candidate_compound)

            candidate_scratch = scratch_root / f"retry-{retry_seed}"
            candidate_scratch.mkdir(parents=True, exist_ok=True)
            logger.info(
                "candidate_scene_build_start",
                retry_seed=retry_seed,
                output_dir=str(candidate_scratch),
            )
            scene_path = build_scene_xml(
                benchmark_definition=synthetic_benchmark,
                assembly=Compound(children=[benchmark_geometry, candidate_compound]),
                output_dir=candidate_scratch,
                backend_type=config.backend_order[0],
            )

            for backend_type in progress_iter(
                config.backend_order, f"backend {retry_seed}"
            ):
                try:
                    logger.info(
                        "verification_start",
                        retry_seed=retry_seed,
                        backend=backend_type.value,
                        batch_width=batch_width,
                    )
                    verify_result = verify_with_jitter(
                        xml_path=str(scene_path),
                        control_inputs={},
                        jitter_range=tuple(
                            float(v)
                            for v in benchmark_definition.payload.runtime_jitter_mm
                        ),
                        num_scenes=batch_width,
                        duration=8.0,
                        seed=retry_seed,
                        backend_type=backend_type,
                        explicit_target_body_name=payload_body_name,
                    )
                    if verify_result.success_rate < config.success_threshold:
                        log_verification_failure_diagnostics(
                            retry_seed=retry_seed,
                            backend_type=backend_type,
                            verify_result=verify_result,
                            route_points=config.route_points,
                            simulation_bounds_mm=benchmark_definition.simulation_bounds_mm,
                        )
                        logger.info(
                            "verification_failed",
                            retry_seed=retry_seed,
                            backend=backend_type.value,
                            success_rate=float(verify_result.success_rate),
                            threshold=config.success_threshold,
                        )
                        continue

                    contact_hits = capture_contact_cloud(
                        scene_path=scene_path,
                        backend_type=backend_type,
                        benchmark_definition=benchmark_definition,
                        duration_s=config.simulation_video_duration_s,
                        seed=retry_seed,
                    )
                    if not contact_hits:
                        logger.info(
                            "contact_cloud_empty",
                            retry_seed=retry_seed,
                            backend=backend_type.value,
                        )
                        continue

                    pruned_specs = prune_segment_specs(
                        candidate_specs, contact_hits, min_hits=1
                    )
                    pruned_compound = compound_from_specs(
                        pruned_specs, label="synthetic_route_solution"
                    )
                    validate_geometry(pruned_compound)

                    pruned_scene_path = build_scene_xml(
                        benchmark_definition=synthetic_benchmark,
                        assembly=Compound(
                            children=[benchmark_geometry, pruned_compound]
                        ),
                        output_dir=candidate_scratch / "pruned",
                        backend_type=backend_type,
                    )

                    pruned_result = verify_with_jitter(
                        xml_path=str(pruned_scene_path),
                        control_inputs={},
                        jitter_range=tuple(
                            float(v)
                            for v in benchmark_definition.payload.runtime_jitter_mm
                        ),
                        num_scenes=batch_width,
                        duration=8.0,
                        seed=retry_seed,
                        backend_type=backend_type,
                        explicit_target_body_name=payload_body_name,
                    )
                    if pruned_result.success_rate < config.success_threshold:
                        log_verification_failure_diagnostics(
                            retry_seed=retry_seed,
                            backend_type=backend_type,
                            verify_result=pruned_result,
                            route_points=config.route_points,
                            simulation_bounds_mm=benchmark_definition.simulation_bounds_mm,
                        )
                        logger.info(
                            "pruned_verification_failed",
                            retry_seed=retry_seed,
                            backend=backend_type.value,
                            success_rate=float(pruned_result.success_rate),
                            threshold=config.success_threshold,
                        )
                        continue

                    chosen_backend = backend_type
                    chosen_batch_width = batch_width
                    chosen_seed = retry_seed
                    chosen_contact_hits = contact_hits
                    chosen_specs = candidate_specs
                    chosen_pruned_specs = pruned_specs
                    chosen_scene_path = pruned_scene_path
                    chosen_verify_result = verify_result
                    chosen_pruned_result = pruned_result
                    logger.info(
                        "candidate_accepted",
                        retry_seed=retry_seed,
                        backend=backend_type.value,
                        batch_width=batch_width,
                        success_rate_tube=float(verify_result.success_rate),
                        success_rate_pruned=float(pruned_result.success_rate),
                        pruned_part_count=len(pruned_specs),
                    )
                    break
                except Exception:
                    logger.exception(
                        "backend_attempt_failed",
                        retry_seed=retry_seed,
                        backend=backend_type.value,
                    )
                    continue

            if chosen_backend is not None:
                break
        except Exception:
            logger.exception("retry_configuration_failed", retry_seed=retry_seed)
            continue

    if chosen_backend is None or chosen_pruned_specs is None or chosen_specs is None:
        logger.error(
            "no_retry_configuration_survived",
            scenario_id=config.scenario_id,
            retries=list(config.retry_seeds),
        )
        raise RuntimeError(
            "No retry configuration survived the tube and pruned batches"
        )

    pruned_parts = parts_from_specs(chosen_pruned_specs)
    pruned_compound = Compound(children=pruned_parts)
    pruned_compound.label = "synthetic_route_solution"
    pruned_compound.metadata = CompoundMetadata(is_fixed=True)
    validate_geometry(pruned_compound)

    manufactured_part_entries, total_cost, total_weight = annotate_manufactured_parts(
        pruned_parts, config
    )
    planner_constraints = make_planner_constraints(
        benchmark_definition, total_cost=total_cost, total_weight=total_weight
    )
    assembly_definition = {
        "version": "1.0",
        "units": {"length": "mm", "volume": "mm3", "mass": "g", "currency": "USD"},
        "constraints": planner_constraints,
        "manufactured_parts": manufactured_part_entries,
        "coarse_payload_trajectory": coarse_payload_trajectory_dict(
            payload_name=synthetic_benchmark.payload.label,
            route_points=config.route_points,
            first_contacts=[hit.other_body for hit in chosen_contact_hits[:6]],
            terminal_reference_point=config.route_points[-1].name,
            sample_stride_s=0.25,
        ),
        "final_assembly": [
            {"name": spec.name, "config": None} for spec in chosen_pruned_specs
        ],
        "totals": {
            "estimated_unit_cost_usd": total_cost,
            "estimated_weight_g": total_weight,
            "estimate_confidence": "high",
        },
        "dfm_suggestions": [],
    }
    AssemblyDefinition.model_validate(assembly_definition)

    payload_trajectory_yaml = payload_trajectory_dict(
        payload_name=synthetic_benchmark.payload.label,
        route_points=config.route_points,
        first_contacts=[hit.other_body for hit in chosen_contact_hits[:6]],
        terminal_reference_point=config.route_points[-1].name,
        backend=chosen_backend,
        sample_stride_s=0.1,
    )

    PayloadTrajectoryDefinition.model_validate(payload_trajectory_yaml)

    markdown_files = build_markdown_templates()
    planner_plan = build_engineering_plan_text(
        scenario_id=config.scenario_id,
        route_points=config.route_points,
        total_cost=total_cost,
        total_weight=total_weight,
        planner_target_cost=planner_constraints["planner_target_max_unit_cost_usd"],
        planner_target_weight=planner_constraints["planner_target_max_weight_g"],
    )

    markdown_files["engineering_plan.md"] = planner_plan
    markdown_files["todo.md"] = build_todo_text()

    planner_evidence_text = build_evidence_script_text(
        scenario_id=config.scenario_id,
        route_points=config.route_points,
        part_specs=chosen_pruned_specs,
        payload_name=synthetic_benchmark.payload.label,
        split_seed=chosen_seed,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=config.clearance_mm,
        wall_thickness_mm=config.wall_thickness_mm,
        max_segment_mm=config.max_segment_mm,
        material_id=config.material_id,
    )
    solution_script_text = build_solution_script_text(
        scenario_id=config.scenario_id,
        route_points=config.route_points,
        part_specs=chosen_pruned_specs,
        payload_name=synthetic_benchmark.payload.label,
        split_seed=chosen_seed,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=config.clearance_mm,
        wall_thickness_mm=config.wall_thickness_mm,
        max_segment_mm=config.max_segment_mm,
        material_id=config.material_id,
    )

    planner_root = config.staged_planner_root
    coder_root = config.staged_coder_root
    copy_reviews_from = (
        benchmark_bundle_reviews if benchmark_bundle_reviews.exists() else None
    )

    stage_bundle_root(
        root=planner_root,
        benchmark_definition_yaml=synthetic_benchmark_dict,
        benchmark_script_text=benchmark_script_text,
        benchmark_assembly_text=benchmark_assembly_text,
        assembly_definition_yaml=assembly_definition,
        evidence_script_text=planner_evidence_text,
        markdown_files={
            "engineering_plan.md": markdown_files["engineering_plan.md"],
            "todo.md": markdown_files["todo.md"],
            "solution_description.md": markdown_files["solution_description.md"],
        },
        copy_reviews_from=copy_reviews_from,
    )

    stage_bundle_root(
        root=coder_root,
        benchmark_definition_yaml=synthetic_benchmark_dict,
        benchmark_script_text=benchmark_script_text,
        benchmark_assembly_text=benchmark_assembly_text,
        assembly_definition_yaml=assembly_definition,
        evidence_script_text=planner_evidence_text,
        solution_script_text=solution_script_text,
        payload_trajectory_yaml=payload_trajectory_yaml,
        markdown_files={
            "engineering_plan.md": markdown_files["engineering_plan.md"],
            "todo.md": markdown_files["todo.md"],
            "solution_description.md": markdown_files["solution_description.md"],
            "journal.md": markdown_files["journal.md"],
        },
        copy_reviews_from=copy_reviews_from,
    )

    if config.emit_simulation_video and simulation_video_summary is None:
        simulation_video_summary = render_simulation_video_preview(
            backend_type=chosen_backend,
            script_content=solution_script_text,
            session_id=f"{config.scenario_id}-video-{chosen_seed}",
            workspace_root=coder_root,
            artifact_root=run_log_root,
        )

    if config.emit_debug_plots:
        debug_output_dir = run_log_root / "renders" / "debug"
        logger.info("render_debug_plots_start", output_dir=str(debug_output_dir))
        render_debug_plots(
            output_dir=debug_output_dir,
            route_points=config.route_points,
            tube_radius_mm=tube_radius_mm,
            contact_hits=chosen_contact_hits,
            part_specs=chosen_pruned_specs,
        )
        logger.info(
            "render_debug_plots_done",
            output_dir=str(debug_output_dir),
            image_paths=[
                str(debug_output_dir / "route_contacts_3d.png"),
                str(debug_output_dir / "route_projections.png"),
            ],
        )

    startup_render = render_startup_workspace_preview(
        workspace_root=coder_root,
        artifact_root=run_log_root,
        payload_path=True,
    )
    logger.info(
        "startup_render_artifacts",
        success=bool(startup_render.get("success")),
        status_text=startup_render.get("status_text"),
        message=startup_render.get("message"),
        image_path=startup_render.get("image_path"),
        artifact_path=startup_render.get("artifact_path"),
        manifest_path=startup_render.get("manifest_path"),
        artifact_root=startup_render.get("artifact_root"),
        materialized_paths=dict(startup_render.get("materialized_paths") or {}),
    )

    if config.promote_to_dataset:
        logger.info("promote_to_dataset_start")
        dataset_root = REPO_ROOT / "dataset" / "data" / "seed" / "artifacts"
        final_planner_root = dataset_root / "engineer_planner" / config.planner_row_id
        final_coder_root = dataset_root / "engineer_coder" / config.coder_row_id
        if final_planner_root.exists():
            shutil.rmtree(final_planner_root)
        if final_coder_root.exists():
            shutil.rmtree(final_coder_root)
        shutil.copytree(planner_root, final_planner_root)
        shutil.copytree(coder_root, final_coder_root)

        planner_row_path = (
            REPO_ROOT
            / "dataset"
            / "data"
            / "seed"
            / "role_based"
            / "engineer_planner.json"
        )
        coder_row_path = (
            REPO_ROOT
            / "dataset"
            / "data"
            / "seed"
            / "role_based"
            / "engineer_coder.json"
        )
        planner_row = role_row(
            row_id=config.planner_row_id,
            agent=AgentName.ENGINEER_PLANNER,
            bundle_dir=Path("dataset/data/seed/artifacts/engineer_planner")
            / config.planner_row_id,
            scenario_id=config.scenario_id,
            description="Populate the planner bundle by editing the filesystem overlay and preserving the box-decomposed corridor contract.",
        )
        coder_row = role_row(
            row_id=config.coder_row_id,
            agent=AgentName.ENGINEER_CODER,
            bundle_dir=Path("dataset/data/seed/artifacts/engineer_coder")
            / config.coder_row_id,
            scenario_id=config.scenario_id,
            description="Populate the coder bundle by editing the filesystem overlay and preserving the generated payload-trajectory proof.",
        )
        update_dataset_row(planner_row_path, planner_row)
        update_dataset_row(coder_row_path, coder_row)
        logger.info(
            "promote_to_dataset_done",
            planner_row_id=config.planner_row_id,
            coder_row_id=config.coder_row_id,
        )

    if config.backfill_source_solution:
        backfill_source_solution(
            source_seed_bundle_dir=config.source_seed_bundle_dir,
            solved_coder_root=coder_root,
        )

    logger.info(
        "synthesize_done",
        scenario_id=config.scenario_id,
        backend=chosen_backend.value,
        retry_seed=chosen_seed,
        success_rate_tube=float(chosen_verify_result.success_rate),
        success_rate_pruned=float(chosen_pruned_result.success_rate),
    )
    return {
        "scenario_id": config.scenario_id,
        "backend": chosen_backend.value,
        "batch_width": chosen_batch_width,
        "retry_seed": chosen_seed,
        "scene_path": str(chosen_scene_path) if chosen_scene_path else None,
        "planner_root": str(planner_root),
        "coder_root": str(coder_root),
        "startup_render": startup_render,
        "simulation_video_summary": simulation_video_summary,
        "run_log_root": str(run_log_root),
        "total_cost": total_cost,
        "total_weight": total_weight,
        "success_rate_tube": float(chosen_verify_result.success_rate),
        "success_rate_pruned": float(chosen_pruned_result.success_rate),
        "pruned_part_count": len(chosen_pruned_specs),
    }


def main(config: ScenarioConfig | None = None) -> dict[str, Any]:
    if config is None:
        config = ScenarioConfig(
            scenario_id="tube-guided-synthetic-001",
            source_seed_bundle_dir=REPO_ROOT
            / "dataset"
            / "data"
            / "seed"
            / "artifacts"
            / "engineer_coder"
            / "ec-002-low-friction-cube",
            planner_row_id="ep-synth-001",
            coder_row_id="ec-synth-001",
            route_points=default_route_points(),
            scratch_root=REPO_ROOT / "tmp" / "tube_guided_synthetic_corpus",
            promote_to_dataset=False,
            backfill_source_solution=False,
            backend_order=(SimulatorBackendType.MUJOCO,),
        )
    if _render_simulation_video_disabled():
        config.emit_simulation_video = False
    os.environ.setdefault("WORKER_HEAVY_URL", _default_worker_heavy_url())
    run_log_root = prepare_timestamped_run_dir(
        REPO_ROOT / "logs" / "tube_guided_synthetic_rigid_body_corpus"
    )
    log_path = run_log_root / "notebook.log"
    with NotebookLogCapture(log_path):
        logger = structlog.get_logger(__name__)
        logger.info("notebook_log_capture_start", log_path=str(log_path))
        summary = synthesize(config, run_log_root=run_log_root)
        logger.info("notebook_log_capture_done", log_path=str(log_path))
    summary["run_log_root"] = str(run_log_root)
    summary["notebook_log_path"] = str(log_path)
    summary["render_log_root"] = str(run_log_root / "renders")
    return summary


if __name__ == "__main__":
    try:
        summary = main()
        print(json.dumps(summary, indent=2))
    except Exception:
        structlog.get_logger(__name__).exception(
            "tube_guided_synthetic_corpus_main_failed"
        )
        raise
