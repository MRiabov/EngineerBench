from pathlib import Path

import numpy as np
import structlog
from build123d import Compound, Part

from shared.agents import get_video_render_resolution
from shared.config.simulation import simulation_settings
from shared.enums import FailureReason, SimulationConfidence
from shared.models.schemas import (
    BenchmarkDefinition,
    PayloadTrajectoryDefinition,
)
from shared.models.simulation import (
    SimulationFailure,
    SimulationMetrics,
    SimulationRenderProvenance,
)
from shared.observability.events import emit_event
from shared.observability.schemas import SimulationBackendSelectedEvent
from shared.simulation.backends import SimulationScene
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.workers.schema import RenderBundleObjectPoseRecord
from shared.workers.workbench_models import ManufacturingMethod
from worker_heavy.simulation.evaluator import SuccessEvaluator
from worker_heavy.simulation.factory import get_physics_backend
from worker_heavy.simulation.frame_stream import SimulationFrameStreamPublisher
from worker_heavy.simulation.media import MediaRecorder
from worker_heavy.simulation.metrics import MetricCollector
from worker_heavy.simulation.naming import moved_object_scene_name
from worker_heavy.simulation.object_pose import write_object_pose_parquet
from worker_heavy.simulation.payload_trajectory_monitor import (
    PayloadTrajectoryMonitor,
)
from worker_heavy.utils.dfm import (
    resolve_requested_quantity,
    validate_and_price_assembly,
)
from worker_heavy.workbenches.config import load_config, load_merged_config

logger = structlog.get_logger(__name__)


class SimulationLoop:
    def __init__(
        self,
        xml_path: str | Path,
        component: Part | Compound | None = None,
        max_simulation_time: float = simulation_settings.max_simulation_time_seconds,
        backend_type: SimulatorBackendType | None = None,
        objectives: BenchmarkDefinition | None = None,
        payload_trajectory_definition: PayloadTrajectoryDefinition | None = None,
        smoke_test_mode: bool | None = None,
        session_id: str | None = None,
        particle_budget: int | None = None,
        manufactured_part_labels: set[str] | None = None,
        require_goal_completion: bool = True,
        benchmark_payload_observation_window_s: float | None = 1.5,
    ):
        from worker_heavy.config import settings

        resolved_backend_type = backend_type or get_default_simulator_backend()
        if smoke_test_mode is None:
            smoke_test_mode = settings.smoke_test_mode
        self.backend = get_physics_backend(
            resolved_backend_type,
            session_id=session_id,
            smoke_test_mode=smoke_test_mode,
            particle_budget=particle_budget,
        )
        self.smoke_test_mode = smoke_test_mode
        self.backend_type = resolved_backend_type
        self.session_id = session_id
        self.require_goal_completion = require_goal_completion
        self.benchmark_payload_observation_window_s = (
            float(benchmark_payload_observation_window_s)
            if benchmark_payload_observation_window_s is not None
            else None
        )
        self.benchmark_payload_body_name: str | None = None
        self._benchmark_payload_out_of_bounds_recorded = False
        # Propagate smoke test mode to backend for optimization (in case of cache hit)
        if hasattr(self.backend, "smoke_test_mode"):
            self.backend.smoke_test_mode = smoke_test_mode
        if hasattr(self.backend, "particle_budget"):
            self.backend.particle_budget = particle_budget

        self.particle_budget = particle_budget or (5000 if smoke_test_mode else 100000)
        self.render_provenance: SimulationRenderProvenance | None = None
        self.render_object_store_key: str | None = None

        try:
            # Emit backend selection event (WP2)
            emit_event(
                SimulationBackendSelectedEvent(
                    backend=resolved_backend_type.value
                    if hasattr(resolved_backend_type, "value")
                    else resolved_backend_type,
                    compute_target=objectives.physics.compute_target
                    if objectives
                    else "auto",
                )
            )
            scene_config = {"particle_budget": self.particle_budget}
            if objectives and objectives.simulation_bounds:
                scene_config["simulation_bounds"] = (
                    objectives.simulation_bounds.model_dump()
                )

            scene = SimulationScene(
                scene_path=str(xml_path),
                config=scene_config,
            )
            self.backend.load_scene(scene)

            self.component = component
            self.objectives = objectives
            self.requested_quantity = resolve_requested_quantity(
                benchmark_definition=self.objectives
            )
            self.validation_report = None
            self.manufactured_part_labels = manufactured_part_labels or set()

            if self.component:
                # WP2: Load custom configuration from working directory if present
                working_dir = Path(xml_path).parent
                custom_config_path = working_dir / "manufacturing_config.yaml"
                if custom_config_path.exists():
                    self.config = load_merged_config(custom_config_path)
                    logger.info(
                        "loop_loaded_custom_config",
                        path=str(custom_config_path),
                        materials=list(self.config.cnc.materials.keys())
                        if self.config.cnc
                        else [],
                    )
                else:
                    self.config = load_config()
                    logger.info(
                        "loop_loaded_default_config",
                        materials=list(self.config.materials.keys()),
                    )

                if self.manufactured_part_labels:
                    mfg_method = ManufacturingMethod.CNC
                    if self.manufactured_part_labels:
                        for child in getattr(self.component, "children", []) or [
                            self.component
                        ]:
                            if (
                                getattr(child, "label", None)
                                in self.manufactured_part_labels
                            ):
                                meta = getattr(child, "metadata", None)
                                if meta and getattr(meta, "manufacturing_method", None):
                                    mfg_method = meta.manufacturing_method
                                    break
                    self.validation_report = validate_and_price_assembly(
                        self.component,
                        self.config,
                        part_labels=self.manufactured_part_labels,
                        default_method=mfg_method,
                        quantity=self.requested_quantity,
                    )
                else:
                    self.validation_report = None

                # Build material lookup
                self.material_lookup = {}
                self.fixed_body_names = set()
                children = getattr(self.component, "children", [])
                if not children:
                    children = [self.component]
                for child in children:
                    label = getattr(child, "label", None)
                    if label:
                        metadata = getattr(child, "metadata", None)
                        material_id = getattr(metadata, "material_id", None)
                        if not material_id and getattr(metadata, "cots_id", None):
                            material_id = "cots-generic"
                        self.material_lookup[label] = material_id
                        if getattr(metadata, "is_fixed", False):
                            self.fixed_body_names.add(label)
            else:
                self.config = None
                self.material_lookup = {}
                self.fixed_body_names = set()

            self.fixed_body_prefixes = tuple(
                f"{label}_" for label in sorted(self.fixed_body_names)
            )

            # Cache zone names for forbidden zones
            self.forbidden_sites = []
            self.goal_sites = []
            for name in self.backend.get_all_site_names():
                if name and name.startswith("zone_forbid"):
                    self.forbidden_sites.append(name)
                elif name and name.startswith("zone_goal"):
                    self.goal_sites.append(name)

            logger.info(
                "SimulationLoop_init",
                goal_sites=self.goal_sites,
                forbidden_sites=self.forbidden_sites,
            )

            if self.objectives and self.objectives.payload:
                self.benchmark_payload_body_name = self._identify_target_body()

            # Configurable timeout (capped at hard limit)
            self.max_simulation_time = min(
                max_simulation_time, simulation_settings.max_simulation_time_seconds
            )

            # Performance optimizations: cache backend info
            self.actuator_names = self.backend.get_all_actuator_names()
            self.body_names = [
                b
                for b in self.backend.get_all_body_names()
                if b not in ["world", "0"] and not b.startswith("zone_")
            ]

            # Cache actuator limits for monitoring
            self._monitor_names = []
            self._monitor_limits = []
            for name in self.actuator_names:
                try:
                    state = self.backend.get_actuator_state(name)
                    # Only monitor if there is a non-zero force range
                    if (
                        state.forcerange
                        and len(state.forcerange) >= 2
                        and state.forcerange[1] > state.forcerange[0]
                    ):
                        self._monitor_names.append(name)
                        self._monitor_limits.append(state.forcerange[1])
                    elif self.backend_type != SimulatorBackendType.MUJOCO:
                        # Default for other backends (e.g. Genesis)
                        self._monitor_names.append(name)
                        self._monitor_limits.append(1000.0)
                except Exception:
                    pass

            self.actuator_clamp_duration = {}

            self.metric_collector = MetricCollector()
            self.payload_trajectory_monitor = None
            self.payload_trajectory_monitor_init_error = None
            self.success_evaluator = SuccessEvaluator(
                max_simulation_time=self.max_simulation_time,
                simulation_bounds=self.objectives.simulation_bounds
                if self.objectives
                else None,
                session_id=session_id,
            )
            if payload_trajectory_definition is not None:
                try:
                    self.payload_trajectory_monitor = PayloadTrajectoryMonitor(
                        payload_definition=payload_trajectory_definition,
                        backend=self.backend,
                        backend_type=self.backend_type,
                        goal_sites=list(self.goal_sites),
                        target_body_name=self._identify_target_body(),
                        session_id=session_id,
                    )
                except Exception as exc:
                    self.payload_trajectory_monitor_init_error = str(exc)
                    logger.warning(
                        "payload_trajectory_monitor_init_failed",
                        error=str(exc),
                        session_id=session_id,
                    )

            # Reset metrics
            self.reset_metrics()
        except Exception as e:
            import traceback

            logger.error(
                "SimulationLoop_init_failed",
                error=str(e),
                traceback=traceback.format_exc(),
                session_id=session_id,
            )
            raise

    def reset_metrics(self):
        self.metric_collector.reset()
        self.success = False
        self.fail_reason = None
        self.actuator_clamp_duration = {}
        if getattr(self, "payload_trajectory_monitor", None) is not None:
            self.payload_trajectory_monitor.reset()

    def step(
        self,
        control_inputs: dict[str, float],
        duration: float = 10.0,
        dynamic_controllers: dict[str, callable] | None = None,
        video_path: Path | None = None,
        frame_stream_publisher: SimulationFrameStreamPublisher | None = None,
        reset_metrics: bool = True,
    ) -> SimulationMetrics:
        """Runs the simulation for the specified duration."""
        if reset_metrics:
            self.reset_metrics()
        object_pose_records: list[RenderBundleObjectPoseRecord] = []

        # 1. Pre-simulation validation
        metrics = self._perform_pre_simulation_validation()
        if metrics:
            return metrics

        # 2. Setup recorders
        media_recorder = MediaRecorder(
            video_path,
            backend_type=self.backend_type,
            session_id=self.session_id,
            render_resolution=get_video_render_resolution(),
            frame_stream_publisher=frame_stream_publisher,
        )

        # 3. Apply initial controls
        self._apply_gated_controls(control_inputs)
        initial_frame_index = media_recorder.update(0.0, self.backend)
        if initial_frame_index is not None:
            object_pose_records.extend(
                self.backend.export_object_pose_records(
                    body_names=self.body_names,
                    frame_index=initial_frame_index,
                )
            )

        # 4. Determine timestep and steps
        dt = self._get_simulation_timestep()
        steps = int(duration / dt)
        current_time = 0.0

        # 5. Find target body
        target_body_name = self._identify_target_body()
        logger.info("SimulationLoop_step_start", target_body_name=target_body_name)

        # 6. Main simulation loop
        for step_idx in range(steps):
            self.current_step_idx = step_idx

            if self._step_internal(
                step_idx,
                steps,
                dt,
                control_inputs,
                dynamic_controllers,
                target_body_name,
            ):
                current_time = self.backend.get_state()["time"]
                break

            # Video recording
            current_time = self.backend.get_state()["time"]
            captured_frame_index = media_recorder.update(current_time, self.backend)
            if captured_frame_index is not None:
                object_pose_records.extend(
                    self.backend.export_object_pose_records(
                        body_names=self.body_names,
                        frame_index=captured_frame_index,
                    )
                )

        # 7. Finalization
        self.render_provenance = media_recorder.render_provenance
        self.render_object_store_key = media_recorder.save()
        if (
            media_recorder.video_path is not None
            and media_recorder.video_path.exists()
            and object_pose_records
        ):
            try:
                write_object_pose_parquet(
                    media_recorder.video_path.parent,
                    object_pose_records,
                    source_path=media_recorder.video_path.name,
                    session_id=self.session_id,
                )
            except Exception as exc:
                logger.warning(
                    "object_pose_export_skipped",
                    error=str(exc),
                    session_id=self.session_id,
                )
        return self._build_simulation_metrics(current_time)

    def _step_internal(
        self,
        step_idx: int,
        steps: int,
        dt: float,
        control_inputs: dict[str, float],
        dynamic_controllers: dict[str, callable] | None,
        target_body_name: str | None,
    ) -> bool:
        """Internal step logic for the simulation loop. Returns True if simulation should stop."""
        # Apply dynamic controllers
        if dynamic_controllers:
            current_time = self.backend.get_state()["time"]
            self._apply_gated_controls({}, current_time, dynamic_controllers)

        # Step backend
        res = self.backend.step(dt)
        current_time = res.time

        # Check failures and update metrics
        check_interval = 1
        if step_idx % check_interval == 0 or step_idx == steps - 1:
            if self._check_simulation_failure(
                res, current_time, dt * check_interval, target_body_name
            ):
                return True

        return False

    def check_goal_with_vertices(self, body_name: str) -> bool:
        """Check if any vertices of body_name are inside any of the goal sites."""
        return any(
            self.backend.check_collision(body_name, goal_site)
            for goal_site in self.goal_sites
        )

    def _check_forbidden_collision(self) -> str | None:
        """Check for collisions with forbidden zones. Returns the name of the colliding body."""
        for b in self.body_names:
            for z in self.forbidden_sites:
                if self.backend.check_collision(b, z):
                    return b
        return None

    def _benchmark_payload_out_of_bounds_grace_applies(
        self, body_name: str, current_time: float
    ) -> bool:
        if self.require_goal_completion:
            return False
        if self.benchmark_payload_body_name is None:
            return False
        if not self.objectives or not self.objectives.payload:
            return False
        if body_name != self.benchmark_payload_body_name:
            return False
        if self.benchmark_payload_observation_window_s is None:
            return False
        return current_time >= self.benchmark_payload_observation_window_s

    def _record_benchmark_payload_out_of_bounds_evidence(
        self, body_name: str, current_time: float
    ) -> None:
        if self._benchmark_payload_out_of_bounds_recorded:
            return

        payload_label = (
            str(self.objectives.payload.label).strip()
            if self.objectives and self.objectives.payload
            else body_name
        )
        self.metric_collector.add_event(
            "benchmark_payload_out_of_bounds_after_window",
            {
                "body": body_name,
                "payload_label": payload_label,
                "time_s": current_time,
                "observation_window_s": self.benchmark_payload_observation_window_s,
                "bounds": (
                    self.objectives.simulation_bounds.model_dump()
                    if self.objectives and self.objectives.simulation_bounds
                    else None
                ),
            },
        )
        logger.info(
            "benchmark_payload_out_of_bounds_after_window_recorded",
            body=body_name,
            payload_label=payload_label,
            time_s=current_time,
            observation_window_s=self.benchmark_payload_observation_window_s,
        )
        self._benchmark_payload_out_of_bounds_recorded = True

    def _perform_pre_simulation_validation(self) -> SimulationMetrics | None:
        """Check validation status before starting simulation."""
        if self.validation_report and not getattr(
            self.validation_report, "is_manufacturable", False
        ):
            violations = getattr(self.validation_report, "violations", None) or [
                "unknown error"
            ]
            msg = f"validation_failed: {', '.join(map(str, violations))}"
            self.fail_reason = SimulationFailure(
                reason=FailureReason.VALIDATION_FAILED, detail=msg
            )
            return SimulationMetrics(
                total_time=0.0,
                total_energy=0.0,
                max_velocity=0.0,
                success=False,
                fail_reason=str(self.fail_reason),
                fail_mode=self.fail_reason.reason,
                failure=self.fail_reason,
            )

        if self.payload_trajectory_monitor_init_error:
            self.fail_reason = SimulationFailure(
                reason=FailureReason.VALIDATION_FAILED,
                detail=self.payload_trajectory_monitor_init_error,
            )
            return SimulationMetrics(
                total_time=0.0,
                total_energy=0.0,
                max_velocity=0.0,
                success=False,
                fail_reason=str(self.fail_reason),
                fail_mode=self.fail_reason.reason,
                failure=self.fail_reason,
                payload_trajectory_monitor=(
                    self.payload_trajectory_monitor.state
                    if self.payload_trajectory_monitor is not None
                    else None
                ),
                confidence=SimulationConfidence.HIGH,
            )

        return None

    def _get_simulation_timestep(self) -> float:
        """Determine appropriate dt for the backend."""
        if hasattr(self.backend, "timestep"):
            return self.backend.timestep
        if hasattr(self.backend, "model") and hasattr(self.backend.model, "opt"):
            return self.backend.model.opt.timestep
        if self.smoke_test_mode and self.backend_type == SimulatorBackendType.GENESIS:
            return 0.05
        return simulation_settings.simulation_step_s

    def _apply_gated_controls(
        self,
        control_inputs: dict[str, float],
        current_time: float | None = None,
        dynamic_controllers: dict[str, callable] | None = None,
    ):
        """Apply controls to the backend."""
        ctrls = {}
        if dynamic_controllers and current_time is not None:
            for name, controller in dynamic_controllers.items():
                val = controller(current_time)
                ctrls[name] = val
        else:
            for name, val in control_inputs.items():
                ctrls[name] = val
        self.backend.apply_control(ctrls)

    def _check_simulation_failure(
        self, res, current_time: float, dt_interval: float, target_body_name: str | None
    ) -> bool:
        """Aggregate failure checks from backends and evaluators."""
        # 1. Update Metrics
        actuator_states = {
            n: self.backend.get_actuator_state(n) for n in self.actuator_names
        }
        energy = sum(
            abs(state.ctrl * state.velocity) for state in actuator_states.values()
        )

        target_vel = 0.0
        if target_body_name:
            state = self.backend.get_body_state(target_body_name)
            target_vel = np.linalg.norm(state.vel)

        self.metric_collector.update(dt_interval, energy, target_vel)

        # 2. Backend failure checks
        if not res.success:
            self.fail_reason = self._resolve_backend_failure(res)
            return True

        # 3. Payload trajectory monitor checks
        if getattr(self, "payload_trajectory_monitor", None) is not None:
            monitor_failure = self.payload_trajectory_monitor.check(current_time)
            if monitor_failure:
                self.fail_reason = monitor_failure
                return True

        # 4. SuccessEvaluator checks
        for bname in self.body_names:
            bstate = self.backend.get_body_state(bname)
            eval_fail_reason = self.success_evaluator.check_failure(
                current_time, bstate.pos, bstate.vel
            )
            if eval_fail_reason:
                if eval_fail_reason == FailureReason.OUT_OF_BOUNDS and (
                    bname in self.fixed_body_names
                    or bname.startswith(self.fixed_body_prefixes)
                ):
                    continue
                if self._benchmark_payload_out_of_bounds_grace_applies(
                    bname, current_time
                ):
                    self._record_benchmark_payload_out_of_bounds_evidence(
                        bname, current_time
                    )
                    continue
                if eval_fail_reason == FailureReason.OUT_OF_BOUNDS:
                    logger.warning(
                        "out_of_bounds_detected",
                        body=bname,
                        pos=bstate.pos,
                        bounds=self.objectives.simulation_bounds.model_dump()
                        if self.objectives and self.objectives.simulation_bounds
                        else None,
                    )
                self.fail_reason = SimulationFailure(
                    reason=eval_fail_reason, detail=bname
                )
                return True

        # 5. Collision checks
        if self.forbidden_sites:
            colliding_body = self._check_forbidden_collision()
            if colliding_body:
                self.fail_reason = SimulationFailure(
                    reason=FailureReason.FORBID_ZONE_HIT, detail=colliding_body
                )
                return True

        # 6. Goal reached
        if target_body_name and self.check_goal_with_vertices(target_body_name):
            self.success = True
            return True

        return False

    def _resolve_backend_failure(self, res) -> SimulationFailure:
        """Translate backend failure into SimulationFailure."""
        logger.info("DEBUG_backend_failure", reason=res.failure_reason)
        if res.failure:
            return res.failure

        # Default fallback: assume instability.
        return SimulationFailure(reason=FailureReason.PHYSICS_INSTABILITY)

    def _identify_target_body(self) -> str | None:
        """Identify the primary target body for objective tracking."""
        all_bodies = self.backend.get_all_body_names()

        # Priority 1: Check objectives for payload label
        if self.objectives and self.objectives.payload:
            label = str(self.objectives.payload.label).strip()
            namespaced_label = moved_object_scene_name(label)
            if namespaced_label in all_bodies:
                return namespaced_label
            if label in all_bodies:
                return label

        # Priority 2: Standard target_box name
        target_body_name = "target_box"
        if target_body_name in all_bodies:
            return target_body_name

        # Priority 3: Heuristic search
        for name in all_bodies:
            if "target" in name.lower() or "bucket" in name.lower():
                return name
        return None

    def _build_simulation_metrics(self, current_time: float) -> SimulationMetrics:
        """Construct the final SimulationMetrics object."""
        metrics = self.metric_collector.get_metrics()

        # Final success determination
        if self.fail_reason:
            is_success = False
        elif self.smoke_test_mode:
            # Smoke mode is an approximation run: treat stable execution as success.
            is_success = True
        elif not self.require_goal_completion:
            # Benchmark mode is a stability/evidence pass, not a solve gate.
            is_success = True
        elif self.goal_sites:
            is_success = self.success
        else:
            is_success = True

        return SimulationMetrics(
            total_time=current_time,
            total_energy=metrics.total_energy,
            max_velocity=metrics.max_velocity,
            success=is_success,
            fail_reason=str(self.fail_reason) if self.fail_reason else None,
            fail_mode=self.fail_reason.reason if self.fail_reason else None,
            failure=self.fail_reason,
            payload_trajectory_monitor=(
                self.payload_trajectory_monitor.state
                if getattr(self, "payload_trajectory_monitor", None) is not None
                else None
            ),
            events=metrics.events,
            confidence=(
                SimulationConfidence.APPROXIMATE
                if self.smoke_test_mode
                else SimulationConfidence.HIGH
            ),
        )
