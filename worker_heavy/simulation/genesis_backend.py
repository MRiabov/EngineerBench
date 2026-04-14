import inspect
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
import structlog

from shared.agents import get_video_render_resolution
from shared.enums import ZoneType
from shared.runtime.headless import configure_headless_rendering

if TYPE_CHECKING:
    pass

# Force headless mode for pyglet (used by genesis/pyrender)
configure_headless_rendering()

try:
    import genesis as gs
except ImportError:
    gs = None
except Exception:
    # Catch other import-time errors like display issues if environment vars didn't help
    gs = None

from shared.models.simulation import (
    RendererCapabilities,
    RenderMode,
)
from shared.simulation.backends import (
    ActuatorState,
    BodyState,
    ContactForce,
    PhysicsRendererBackend,
    SimulationScene,
    SiteState,
    StepResult,
    build_render_bundle_object_pose_records,
)
from shared.workers.schema import RenderBundleObjectPoseRecord

logger = structlog.get_logger(__name__)


def _parse_compile_kernels_env() -> bool | None:
    """Parse optional GENESIS_COMPILE_KERNELS override from environment."""
    raw = os.getenv("GENESIS_COMPILE_KERNELS", "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    logger.warning("invalid_genesis_compile_kernels_env", value=raw)
    return None


class GenesisBackend(PhysicsRendererBackend):
    _lock = threading.Lock()

    def __init__(self, session_id: str | None = None, num_envs: int = 1):
        self.scene = None
        self.entities = {}  # name -> gs.Entity
        self.entity_configs = {}  # name -> dict (from json)
        self.cameras = {}  # name -> gs.Camera
        self.mjcf_actuators = {}  # name -> {joint: str, force_range: tuple}
        self.applied_controls = {}  # name -> float
        self.current_time = 0.0
        self.mfg_config = None
        self.particle_budget = None
        self.smoke_test_mode = False
        self._is_built = False
        self.session_id = session_id
        self.num_envs = max(1, num_envs)
        self.render_width, self.render_height = get_video_render_resolution()
        self._ensure_initialized()

    def _ensure_initialized(self):
        if gs is not None and not getattr(gs, "_initialized", False):
            import os
            import time

            import torch

            start_t = time.time()

            force_cpu = os.getenv("GENESIS_FORCE_CPU", "0") == "1"
            has_gpu = torch.cuda.is_available() and not force_cpu

            backend = gs.gpu if has_gpu else gs.cpu
            logger.info(
                "genesis_initializing", backend="gpu" if backend == gs.gpu else "cpu"
            )

            max_init_retries = 3
            for attempt in range(max_init_retries):
                try:
                    # Reduce logging in smoke test mode
                    gs.init(
                        backend=backend,
                        logging_level="warning" if self.smoke_test_mode else "info",
                    )
                    logger.info(
                        "genesis_initialized",
                        backend="gpu" if backend == gs.gpu else "cpu",
                        duration=time.time() - start_t,
                    )
                    break
                except Exception as e:
                    if "EGL_BAD_DISPLAY" in str(e) and attempt < max_init_retries - 1:
                        logger.warning("genesis_init_egl_retry", attempt=attempt + 1)
                        time.sleep(1.0)
                        continue

                    if backend == gs.gpu:
                        logger.error(
                            "genesis_gpu_init_failed_falling_back_to_cpu",
                            error=str(e),
                            session_id=self.session_id,
                        )
                        backend = gs.cpu
                        start_t = time.time()
                        try:
                            gs.init(backend=gs.cpu)
                            logger.info(
                                "genesis_initialized",
                                backend="cpu",
                                duration=time.time() - start_t,
                            )
                            break
                        except Exception as e2:
                            logger.warning(
                                "genesis_init_failed",
                                error=str(e2),
                                session_id=self.session_id,
                            )
                            raise
                    else:
                        logger.warning(
                            "genesis_init_failed",
                            error=str(e),
                            session_id=self.session_id,
                        )
                        raise

    def _load_mfg_config(self, config_dir: Optional["Path"] = None):
        try:
            from worker_heavy.workbenches.config import load_config, load_merged_config

            if config_dir:
                custom_path = config_dir / "manufacturing_config.yaml"
                if custom_path.exists():
                    self.mfg_config = load_merged_config(custom_path)
                    logger.info(
                        "genesis_loaded_custom_mfg_config", path=str(custom_path)
                    )
                    return

            if self.mfg_config is None:
                self.mfg_config = load_config()
        except Exception as e:
            logger.error(
                "failed_to_load_mfg_config", error=str(e), session_id=self.session_id
            )

    @staticmethod
    def _zone_visual_rgba(
        zone_type: ZoneType | str | None,
    ) -> tuple[float, float, float, float]:
        if zone_type == ZoneType.GOAL:
            return (0.0, 1.0, 0.0, 0.3)
        if zone_type == ZoneType.BUILD:
            return (0.55, 0.55, 0.55, 0.2)
        return (1.0, 0.0, 0.0, 0.3)

    def _add_zone_visual(self, ent_cfg) -> None:
        if self.scene is None or gs is None:
            return

        pos = tuple(float(v) for v in (ent_cfg.pos or (0.0, 0.0, 0.0)))
        if ent_cfg.size is not None:
            size = tuple(float(v) for v in ent_cfg.size)
        elif ent_cfg.min is not None and ent_cfg.max is not None:
            size = tuple(float(ent_cfg.max[i] - ent_cfg.min[i]) / 2.0 for i in range(3))
            pos = tuple(float(ent_cfg.min[i] + ent_cfg.max[i]) / 2.0 for i in range(3))
        else:
            return

        color = self._zone_visual_rgba(getattr(ent_cfg, "zone_type", None))
        surface = gs.surfaces.Default(color=color[:3], opacity=color[3])
        base_kwargs = {"pos": pos, "size": size, "fixed": True}
        morph_variants = (
            {**base_kwargs, "collision": False, "visualization": True},
            {**base_kwargs, "collision": False},
            {**base_kwargs, "visualization": True},
            base_kwargs,
        )

        last_error: Exception | None = None
        for morph_kwargs in morph_variants:
            try:
                self.scene.add_entity(
                    gs.morphs.Box(**morph_kwargs),
                    surface=surface,
                )
                return
            except TypeError as exc:
                last_error = exc

        if last_error is not None:
            raise RuntimeError(
                "Genesis failed to create zone visualization for "
                f"{getattr(ent_cfg, 'name', '<unknown>')}: {last_error}"
            )

    def load_scene(self, scene: SimulationScene, render_only: bool = False) -> None:
        with self._lock:
            # OPTIMIZATION/FIX: If same scene is already built, skip rebuild.
            # This avoids "Scene is already built" error when multiple calls (simulate + prerender)
            # share the same backend instance.
            if (
                self._is_built
                and self.scene_meta
                and self.scene_meta.scene_path == scene.scene_path
                and self.scene_meta.config == scene.config
            ):
                logger.debug("genesis_backend_reuse_scene", scene_path=scene.scene_path)
                return

            # Ensure fresh state for Genesis global state
            self.close()
            self._ensure_initialized()

            if gs is None:
                raise ImportError("Genesis not installed")

            self.scene_meta = scene
            config_dir = Path(scene.scene_path).parent if scene.scene_path else None
            self._load_mfg_config(config_dir=config_dir)

            # Reset state for new scene
            self.entities = {}
            self.entity_configs = {}
            self.cameras = {}
            self.mjcf_actuators = {}
            self.applied_controls = {}
            self._is_built = False

            if "gs_scene" in scene.assets:
                self.scene = scene.assets["gs_scene"]
                self._is_built = True
                return

            # Keep the build fail-closed on transient Genesis build failures.
            max_retries = 3

            for attempt in range(max_retries):
                try:
                    self._load_scene_internal(scene, render_only=render_only)
                    # If we get here, it succeeded
                    if not render_only:
                        self._is_built = True
                    break
                except Exception as e:
                    # Check for OOM
                    error_str = str(e).lower()
                    if (
                        "out of memory" in error_str
                        or "cuda error: out of memory" in error_str
                    ):
                        logger.warning(
                            "genesis_oom_detected",
                            attempt=attempt + 1,
                            reduction=0.0,
                        )
                        # Clean up and retry
                        self.close()
                        if attempt == max_retries - 1:
                            logger.error(
                                "genesis_oom_persistent", session_id=self.session_id
                            )
                            raise
                    else:
                        logger.error(
                            "failed_to_build_genesis_scene",
                            error=str(e),
                            session_id=self.session_id,
                        )
                        raise

    @property
    def is_built(self) -> bool:
        if self.scene is None:
            return False
        # Genesis 0.3.x has .is_built on scene
        if hasattr(self.scene, "is_built"):
            return self.scene.is_built
        return self._is_built

    @property
    def timestep(self) -> float:
        if self.scene and hasattr(self.scene, "sim_options"):
            return self.scene.sim_options.dt
        return 0.002

    def _get_mat_props(self, material_id: str) -> Any | None:

        if not self.mfg_config:
            return None
        res = self.mfg_config.materials.get(material_id)
        if not res and self.mfg_config.cnc:
            res = self.mfg_config.cnc.materials.get(material_id)
        if not res and self.mfg_config.injection_molding:
            res = self.mfg_config.injection_molding.materials.get(material_id)
        if not res and self.mfg_config.three_dp:
            res = self.mfg_config.three_dp.materials.get(material_id)
        return res

    def _load_scene_internal(
        self, scene: SimulationScene, render_only: bool = False
    ) -> None:
        """Internal helper to build the scene, allowing for retries on OOM."""
        if gs is None:
            raise ImportError("Genesis not installed")

        # Optimization for smoke tests: substeps help with Genesis stability.
        # We use production dt for stability.
        is_smoke = getattr(self, "smoke_test_mode", False)
        sim_options = gs.options.SimOptions(
            dt=0.002,
            substeps=4 if is_smoke else 10,
        )

        self.scene = gs.Scene(
            sim_options=sim_options,
            show_viewer=False,
        )

        # Add default ground plane
        self.scene.add_entity(gs.morphs.Plane())

        if scene.scene_path and (
            scene.scene_path.endswith(".xml") or scene.scene_path.endswith(".mjcf")
        ):
            try:
                # WP2: Parse MJCF to find actuators and mapping to joints
                import xml.etree.ElementTree as ET

                tree = ET.parse(scene.scene_path)
                root = tree.getroot()
                for act in root.findall(".//actuator/*"):
                    name = act.get("name")
                    joint_name = act.get("joint")
                    force_range = act.get("forcerange")
                    if name and joint_name:
                        fr = (-1000.0, 1000.0)
                        if force_range:
                            try:
                                parts = [float(x) for x in force_range.split()]
                                if len(parts) == 2:
                                    fr = (parts[0], parts[1])
                            except ValueError:
                                pass
                        self.mjcf_actuators[name] = {
                            "joint": joint_name,
                            "force_range": fr,
                        }

                # Load MJCF directly
                mjcf_entity = self.scene.add_entity(
                    gs.morphs.MJCF(file=scene.scene_path)
                )
                self.entities["mjcf_scene"] = mjcf_entity
                logger.debug(
                    "genesis_mjcf_loaded",
                    path=scene.scene_path,
                    actuators=list(self.mjcf_actuators.keys()),
                )
            except Exception as e:
                logger.error(
                    "failed_to_load_mjcf_in_genesis",
                    error=str(e),
                    session_id=self.session_id,
                )

        elif scene.scene_path and scene.scene_path.endswith(".json"):
            import json
            from pathlib import Path

            from shared.models.schemas import SceneDefinition

            scene_dir = Path(scene.scene_path).parent
            try:
                with Path(scene.scene_path).open() as f:
                    raw_data = json.load(f)
                    data = SceneDefinition(**raw_data)

                    # 1. Add Entities
                    for ent_cfg in data.entities:
                        name = ent_cfg.name
                        self.entity_configs[name] = ent_cfg.model_dump(
                            exclude_none=True
                        )

                        if ent_cfg.is_zone:
                            self._add_zone_visual(ent_cfg)
                            continue

                        material_id = ent_cfg.material_id
                        # WP2 Fix: Robust material lookup across all methods
                        mat_props = self._get_mat_props(material_id)

                        # Load rigid mesh geometry.
                        material = gs.materials.Rigid(
                            rho=mat_props.density_kg_m3
                            if mat_props and mat_props.density_kg_m3
                            else 2700,
                            friction=mat_props.friction_coef
                            if mat_props and mat_props.friction_coef
                            else 0.5,
                            coup_restitution=(
                                mat_props.restitution
                                if mat_props and mat_props.restitution
                                else 0.5
                            ),
                        )
                        if not ent_cfg.file:
                            continue
                        obj_path = scene_dir / ent_cfg.file
                        entity = self.scene.add_entity(
                            gs.morphs.Mesh(
                                file=str(obj_path),
                                pos=ent_cfg.pos,
                                euler=ent_cfg.euler,
                            ),
                            material=material,
                        )

                        self.entities[name] = entity

                    self._is_built = True

            except Exception as e:
                logger.error(
                    "failed_to_parse_genesis_json",
                    error=str(e),
                    session_id=self.session_id,
                )
                raise

        # In Genesis, we must call build() before step()
        if self.scene and not self._is_built:
            # Add default cameras before building
            try:
                if "main" not in self.cameras:
                    self.cameras["main"] = self.scene.add_camera()
                if "prerender" not in self.cameras:
                    self.cameras["prerender"] = self.scene.add_camera()
            except Exception as e:
                logger.warning("genesis_add_camera_failed_pre_build", error=str(e))

            if render_only:
                # OPTIMIZATION: Genesis can render without building the full physics scene.
                # However, some versions/configurations fail with AttributeError: 'Camera' object has no attribute '_is_batched'
                # if the scene is not built.
                logger.info("genesis_building_scene_for_render_only")

            try:
                compile_kernels = _parse_compile_kernels_env()
                build_kwargs: dict[str, bool | int] = {"n_envs": self.num_envs}
                if compile_kernels is not None:
                    sig = inspect.signature(self.scene.build)
                    if "compile_kernels" in sig.parameters:
                        build_kwargs["compile_kernels"] = compile_kernels
                        logger.info(
                            "genesis_scene_build_compile_kernels_override",
                            compile_kernels=compile_kernels,
                            render_only=render_only,
                            session_id=self.session_id,
                        )
                    else:
                        logger.info(
                            "genesis_scene_build_compile_kernels_unsupported",
                            compile_kernels=compile_kernels,
                            session_id=self.session_id,
                        )
                logger.info("genesis_building_scene")
                self.scene.build(**build_kwargs)
            except Exception as e:
                if "already built" not in str(e).lower():
                    logger.warning("genesis_build_failed", error=str(e))
                    raise
            self._is_built = True

    def step(self, dt: float) -> StepResult:
        with self._lock:
            if self.scene is None:
                self.current_time += dt
                return StepResult(time=self.current_time, success=True)

        if not self._is_built:
            # Fallback for unexpected state
            logger.warning("genesis_step_called_unbuilt_attempting_sync")
            if getattr(self.scene, "is_built", False):
                self._is_built = True
            else:
                return StepResult(
                    time=self.current_time,
                    success=False,
                    failure_reason="Scene is not built yet.",
                )

        try:
            # Genesis step size is controlled by gs.Scene(sim_options=...)
            # Ideally dt matches what was configured in gs.Scene
            # Reduce debug logging overhead: only log every 100 steps
            self._step_counter = getattr(self, "_step_counter", 0) + 1
            if self._step_counter % 100 == 0:
                logger.debug(
                    "genesis_scene_stepping",
                    is_built=self._is_built,
                    scene_is_built=getattr(self.scene, "is_built", False),
                )
            self.scene.step()

            # WP2: Ensure current_time matches Genesis physics clock
            actual_dt = dt
            if (
                hasattr(self.scene, "sim_options")
                and self.scene.sim_options is not None
            ):
                actual_dt = getattr(self.scene.sim_options, "dt", dt)

            self.current_time += actual_dt

        except Exception as e:
            logger.warning("genesis_step_failed", error=str(e))
            return StepResult(
                time=self.current_time, success=False, failure_reason=str(e)
            )

        return StepResult(time=self.current_time, success=True)

    def get_body_state(self, body_id: str, env_idx: int | None = None) -> BodyState:
        logger.debug("genesis_get_body_state_request", body_id=body_id, env_idx=env_idx)
        try:
            envs_idx = None if env_idx is None else [env_idx]

            def _as_vector(
                val: Any, size: int, default: tuple[float, ...]
            ) -> tuple[float, ...]:
                """Best-effort conversion to fixed-size float vector."""
                if val is None:
                    return default
                if hasattr(val, "cpu"):
                    val = val.cpu().numpy()

                if isinstance(val, np.ndarray):
                    arr = val
                    if arr.ndim >= 2 and arr.shape[-1] == size:
                        arr = arr.reshape(-1, size)[0]
                    elif arr.ndim == 1 and arr.shape[0] >= size:
                        arr = arr[:size]
                    elif arr.ndim == 0:
                        return default
                    else:
                        return default
                    return tuple(float(x) for x in arr.tolist())

                if isinstance(val, (list, tuple)):
                    if len(val) > 0 and isinstance(val[0], (list, tuple)):
                        val = val[0]
                    if len(val) >= size:
                        return tuple(float(val[i]) for i in range(size))
                    return default

                return default

            if body_id not in self.entities:
                # Check links within MJCF entities (from WP07)
                for ent in self.entities.values():
                    try:
                        # In Genesis, if it's an MJCF entity, it's a RigidEntity
                        # which has a .links attribute
                        target_link = None
                        if hasattr(ent, "links"):
                            for link in ent.links:
                                if link.name == body_id:
                                    target_link = link
                                    break

                        if target_link:
                            logger.debug("genesis_link_state_found", body_id=body_id)

                            pos = _as_vector(
                                target_link.get_pos(envs_idx=envs_idx)
                                if hasattr(target_link, "get_pos")
                                else target_link.pos,
                                3,
                                (0.0, 0.0, 0.0),
                            )
                            quat = _as_vector(
                                target_link.get_quat(envs_idx=envs_idx)
                                if hasattr(target_link, "get_quat")
                                else target_link.quat,
                                4,
                                (1.0, 0.0, 0.0, 0.0),
                            )
                            vel = _as_vector(
                                target_link.get_vel(envs_idx=envs_idx)
                                if hasattr(target_link, "get_vel")
                                else target_link.vel,
                                3,
                                (0.0, 0.0, 0.0),
                            )

                            angvel = (0.0, 0.0, 0.0)
                            if hasattr(target_link, "get_angvel"):
                                angvel = _as_vector(
                                    target_link.get_angvel(envs_idx=envs_idx),
                                    3,
                                    (0.0, 0.0, 0.0),
                                )
                            elif hasattr(target_link, "angvel"):
                                angvel = _as_vector(
                                    target_link.angvel,
                                    3,
                                    (0.0, 0.0, 0.0),
                                )

                            return BodyState(
                                pos=pos,
                                quat=quat,
                                vel=vel,
                                angvel=angvel,
                            )
                    except Exception as e:
                        logger.debug(
                            "genesis_get_link_failed", body_id=body_id, error=str(e)
                        )
                        continue

                logger.debug("genesis_body_not_found", body_id=body_id)
                return BodyState(
                    pos=[0.0, 0.0, 0.0],
                    quat=[1.0, 0.0, 0.0, 0.0],
                    vel=[0.0, 0.0, 0.0],
                    angvel=[0.0, 0.0, 0.0],
                )

            entity = self.entities[body_id]
            logger.debug("genesis_calling_get_state", body_id=body_id)
            state = entity.get_state()
            logger.debug("genesis_get_state_returned", body_id=body_id)

            if (
                hasattr(state, "pos")
                and state.pos.ndim >= 2
                and state.pos.shape[-1] == 3
            ):
                # Soft-body particle state is batched per environment.
                pos_arr = state.pos.cpu().numpy()
                vel_arr = state.vel.cpu().numpy() if hasattr(state, "vel") else None
                if env_idx is not None and pos_arr.ndim >= 2:
                    pos_arr = pos_arr[env_idx]
                    if vel_arr is not None and vel_arr.ndim >= 2:
                        vel_arr = vel_arr[env_idx]

                def _collapse_state_vector(
                    arr: np.ndarray,
                ) -> tuple[float, float, float]:
                    if arr.ndim == 1:
                        flat = arr
                    else:
                        flat = np.mean(arr.reshape(-1, arr.shape[-1]), axis=0)
                    values = np.asarray(flat).reshape(-1)
                    if values.size < 3:
                        return (0.0, 0.0, 0.0)
                    return tuple(float(x) for x in values[:3].tolist())

                pos = _collapse_state_vector(pos_arr)
                vel = (
                    _collapse_state_vector(vel_arr)
                    if vel_arr is not None
                    else (0.0, 0.0, 0.0)
                )
                return BodyState(pos=pos, quat=(1, 0, 0, 0), vel=vel, angvel=(0, 0, 0))
            return BodyState(
                pos=_as_vector(entity.get_pos(envs_idx=envs_idx), 3, (0.0, 0.0, 0.0)),
                quat=_as_vector(
                    entity.get_quat(envs_idx=envs_idx), 4, (1.0, 0.0, 0.0, 0.0)
                ),
                vel=_as_vector(entity.get_vel(envs_idx=envs_idx), 3, (0.0, 0.0, 0.0)),
                angvel=_as_vector(
                    entity.get_ang(envs_idx=envs_idx), 3, (0.0, 0.0, 0.0)
                ),
            )
        except BaseException as e:
            logger.warning(
                "genesis_get_body_state_error",
                error=str(e),
                type=type(e).__name__,
                body_id=body_id,
                session_id=self.session_id,
            )
            return BodyState(
                pos=(0.0, 0.0, 0.0),
                quat=(1.0, 0.0, 0.0, 0.0),
                vel=(0.0, 0.0, 0.0),
                angvel=(0.0, 0.0, 0.0),
            )

    def get_state(self) -> dict[str, Any]:
        if self.scene is None:
            return {"time": self.current_time}
        return {
            "time": self.current_time,
            "n_entities": len(self.entities),
        }

    # Rendering & Visualization
    def render(self) -> np.ndarray:
        return self.render_camera("default", self.render_width, self.render_height)

    def get_render_capabilities(self) -> RendererCapabilities:
        return RendererCapabilities(
            backend_name="genesis",
            artifact_modes_supported=[RenderMode.SIMULATION_VIDEO],
            supports_default_view=True,
            supports_named_cameras=True,
            supports_rgb=True,
            supports_depth=True,
            supports_segmentation=True,
            default_view_label="default",
        )

    def render_camera(self, camera_name: str, width: int, height: int) -> np.ndarray:
        logger.debug(
            "genesis_render_camera_start",
            camera_name=camera_name,
            width=width,
            height=height,
            session_id=self.session_id,
        )
        try:
            with self._lock:
                if not self.scene:
                    logger.debug(
                        "genesis_render_camera_empty_scene",
                        camera_name=camera_name,
                        width=width,
                        height=height,
                        session_id=self.session_id,
                    )
                    return np.zeros((height, width, 3), dtype=np.uint8)

            if camera_name not in self.cameras:
                # Add a default camera if not found
                cam = self.scene.add_camera(res=(width, height))
                self.cameras[camera_name] = cam

            cam = self.cameras[camera_name]
            # Genesis can return (rgb, depth, segmentation) or more
            res = cam.render()
            rgb = res[0] if isinstance(res, tuple) else res

            if hasattr(rgb, "cpu"):
                rgb = rgb.cpu().numpy()

            rgb_image = rgb.astype(np.uint8)
            logger.debug(
                "genesis_render_camera_complete",
                camera_name=camera_name,
                width=width,
                height=height,
                session_id=self.session_id,
                shape=tuple(rgb_image.shape),
            )
            return rgb_image
        except Exception as exc:
            logger.error(
                "genesis_render_camera_failed",
                camera_name=camera_name,
                width=width,
                height=height,
                session_id=self.session_id,
                error=str(exc),
            )
            raise

    def set_camera(
        self,
        camera_name: str,
        pos: tuple[float, float, float] | None = None,
        lookat: tuple[float, float, float] | None = None,
        up: tuple[float, float, float] | None = None,
        fov: float | None = None,
    ) -> None:
        if not self.scene:
            return

        if camera_name not in self.cameras:
            # Create with default res, will be updated by render_camera if needed
            cam = self.scene.add_camera(res=(self.render_width, self.render_height))
            self.cameras[camera_name] = cam

        cam = self.cameras[camera_name]

        # Genesis cameras use set_pose or similar
        # Based on Genesis 0.3.x: cam.set_pose(pos=..., lookat=..., up=...)
        kwargs = {}
        if pos is not None:
            kwargs["pos"] = pos
        if lookat is not None:
            kwargs["lookat"] = lookat
        if up is not None:
            kwargs["up"] = up

        if kwargs:
            cam.set_pose(**kwargs)

        if fov is not None:
            # cam.fov = fov
            pass

    def get_camera_matrix(self, _camera_name: str) -> np.ndarray:
        return np.eye(4)

    def set_site_pos(self, _site_name: str, _pos: np.ndarray) -> None:
        pass

    def get_contact_forces(self) -> list[ContactForce]:
        # logger.debug("genesis_get_contact_forces_start")
        if not self.scene:
            return []

        # Genesis provides contacts via solver/sim
        # In version 0.3.x, contacts are typically accessed via simulator.get_contacts()
        try:
            # logger.debug("genesis_calling_sim_get_contacts")
            contacts = self.scene.sim.get_contacts()
            results = []
            for c in contacts:
                # c has fields like pos, normal, force, entities, etc.
                # c.entities is a tuple of (entity_a, entity_b)
                force = c.force.cpu().numpy() if hasattr(c.force, "cpu") else c.force
                results.append(
                    ContactForce(
                        body1=c.entities[0].name,
                        body2=c.entities[1].name,
                        force=tuple(force.tolist()),
                        position=tuple(c.pos.cpu().numpy().tolist())
                        if hasattr(c.pos, "cpu")
                        else tuple(c.pos.tolist()),
                    )
                )
            return results
        except Exception as e:
            import traceback

            logger.warning(
                "genesis_get_contact_forces_failed",
                error=str(e),
                stack="".join(traceback.format_stack()),
            )
            # Fallback if API changed or no contacts
            return []

    def get_site_state(self, _site_name: str) -> SiteState:
        return SiteState(pos=(0, 0, 0), quat=(1, 0, 0, 0), size=(0, 0, 0))

    def get_actuator_state(self, actuator_name: str) -> ActuatorState:
        ctrl_val = self.applied_controls.get(actuator_name, 0.0)

        # 1. Check MJCF actuators
        if actuator_name in self.mjcf_actuators:
            info = self.mjcf_actuators[actuator_name]
            joint_name = info["joint"]
            entity = self.entities.get("mjcf_scene")
            if entity:
                try:
                    # Find joint by name
                    joint = None
                    for j in entity.joints:
                        if j.name == joint_name:
                            joint = j
                            break

                    if joint:
                        idx = joint.dof_start
                        forces = self._as_numpy_vector(entity.get_dofs_force())
                        vels = self._as_numpy_vector(entity.get_dofs_velocity())

                        return ActuatorState(
                            force=float(forces[idx]),
                            velocity=float(vels[idx]),
                            ctrl=ctrl_val,
                            forcerange=info["force_range"],
                        )
                except Exception as e:
                    logger.debug("failed_to_get_mjcf_actuator_state", error=str(e))

        return ActuatorState(force=0.0, velocity=0.0, ctrl=ctrl_val, forcerange=(0, 0))

    def _set_entity_dofs_force(self, entity, forces):
        """Helper to set DOFs force, supporting different Genesis versions."""
        if hasattr(entity, "control_dofs_force"):
            entity.control_dofs_force(forces)
        elif hasattr(entity, "set_dofs_force"):
            entity.set_dofs_force(forces)
        else:
            logger.error(
                "entity_missing_force_control_method",
                entity=str(entity),
                session_id=self.session_id,
            )

    @staticmethod
    def _as_numpy_vector(values: Any) -> np.ndarray:
        if hasattr(values, "cpu"):
            values = values.cpu().numpy()
        return np.asarray(values, dtype=float)

    def apply_control(self, control_inputs: dict[str, float]) -> None:
        for actuator_name, val in control_inputs.items():
            self.applied_controls[actuator_name] = val

            # 1. Handle MJCF actuators
            if actuator_name in self.mjcf_actuators:
                info = self.mjcf_actuators[actuator_name]
                joint_name = info["joint"]
                entity = self.entities.get("mjcf_scene")
                if entity:
                    try:
                        # Find joint by name
                        joint = None
                        for j in entity.joints:
                            if j.name == joint_name:
                                joint = j
                                break

                        if joint:
                            idx = joint.dof_start
                            # We need to set all DOFs or use specific indices
                            forces = entity.get_dofs_force()
                            forces[idx] = val
                            self._set_entity_dofs_force(entity, forces)
                    except Exception as e:
                        logger.debug("mjcf_apply_control_failed", error=str(e))
                continue

    def get_all_body_names(self) -> list[str]:
        names = list(self.entities.keys())
        for ent in self.entities.values():
            try:
                # Add link names if it's an articulated entity (from WP07)
                if hasattr(ent, "links"):
                    for link in ent.links:
                        if link.name not in names:
                            names.append(link.name)
            except Exception:
                continue
        return names

    def get_all_actuator_names(self) -> list[str]:
        return list(self.mjcf_actuators.keys())

    def get_all_site_names(self) -> list[str]:
        return [name for name, cfg in self.entity_configs.items() if cfg.get("is_zone")]

    def get_all_tendon_names(self) -> list[str]:
        return []

    def get_all_camera_names(self) -> list[str]:
        return list(self.cameras.keys())

    def export_object_pose_records(
        self,
        *,
        body_names: list[str] | None = None,
        frame_index: int | None = None,
    ) -> list[RenderBundleObjectPoseRecord]:
        return build_render_bundle_object_pose_records(
            self,
            body_names=body_names,
            frame_index=frame_index,
        )

    def check_collision(
        self, body_name: str, site_name: str, env_idx: int | None = None
    ) -> bool:
        """Checks if a body is in collision with another body or site (zone)."""
        logger.debug(
            "genesis_check_collision_start",
            body=body_name,
            site=site_name,
            env_idx=env_idx,
        )
        # In Genesis, sites are often just entities or zones.
        # If site_name is an entity, check contact.
        target_entity = self.entities.get(body_name)
        site_entity = self.entities.get(site_name)

        if not target_entity or not site_entity:
            # Check if it's a zone in entity_configs
            ent_cfg = self.entity_configs.get(site_name)
            if not ent_cfg and self.scene_meta:
                # Fallback for scene_meta
                for cfg in self.scene_meta.assets.get("entities", []):
                    if cfg.get("name") == site_name:
                        ent_cfg = cfg
                        break

            if ent_cfg and ent_cfg.get("is_zone"):
                # Check if target body pos is within zone
                state = self.get_body_state(body_name, env_idx=env_idx)
                pos = state.pos

                # Handle both min/max and pos/size representations
                if "min" in ent_cfg and "max" in ent_cfg:
                    z_min = ent_cfg["min"]
                    z_max = ent_cfg["max"]
                elif "pos" in ent_cfg and "size" in ent_cfg:
                    center = ent_cfg["pos"]
                    half_extents = ent_cfg["size"]
                    z_min = [center[i] - half_extents[i] for i in range(3)]
                    z_max = [center[i] + half_extents[i] for i in range(3)]
                else:
                    return False

                return all(z_min[i] <= pos[i] <= z_max[i] for i in range(3))

            return False

        # If both are entities, check simulation contacts
        contacts = self.get_contact_forces()
        for c in contacts:
            if (c.body1 == body_name and c.body2 == site_name) or (
                c.body1 == site_name and c.body2 == body_name
            ):
                return True

        return False

    def get_tendon_tension(self, tendon_name: str) -> float:
        """Returns zero because cable/tendon support is not part of the bundle."""
        return 0.0

    def apply_jitter(
        self,
        body_name: str,
        jitter: tuple[float, float, float],
        env_idx: int | None = None,
    ) -> None:
        """Apply position jitter to a body in Genesis using qpos."""
        import torch

        envs_idx = None if env_idx is None else [env_idx]

        if body_name in self.entities:
            entity = self.entities[body_name]
            qpos = entity.get_qpos(envs_idx=envs_idx)
            # Assuming first 3 are position for free bodies or similar
            # If it has DOFs, jitter the first 3 (which are usually root translations)
            if qpos.shape[-1] >= 3:
                jitter_tensor = torch.tensor(
                    jitter, dtype=qpos.dtype, device=qpos.device
                )
                if qpos.ndim == 2:
                    qpos[:, :3] += jitter_tensor
                else:
                    qpos[:3] += jitter_tensor
                entity.set_qpos(qpos, envs_idx=envs_idx)
        else:
            # Check links within entities
            for ent in self.entities.values():
                if hasattr(ent, "links"):
                    for link in ent.links:
                        if link.name == body_name:
                            # link.q_start/q_end give indices into entity qpos
                            qpos = ent.get_qpos(envs_idx=envs_idx)
                            q_extent = qpos.shape[-1]
                            if link.q_start + 3 <= q_extent:
                                jitter_tensor = torch.tensor(
                                    jitter, dtype=qpos.dtype, device=qpos.device
                                )
                                if qpos.ndim == 2:
                                    qpos[:, link.q_start : link.q_start + 3] += (
                                        jitter_tensor
                                    )
                                else:
                                    qpos[link.q_start : link.q_start + 3] += (
                                        jitter_tensor
                                    )
                                ent.set_qpos(qpos, envs_idx=envs_idx)
                            return

    def reset(self) -> None:
        """Reset Genesis state without rebuilding the compiled scene."""
        if self.scene is None or not self.is_built:
            raise RuntimeError("Scene not loaded")

        self.scene.reset()

    def close(self) -> None:
        try:
            if self.scene and hasattr(self.scene, "destroy"):
                try:
                    self.scene.destroy()
                except Exception as e:
                    logger.debug("scene_destroy_failed", error=str(e))
        except Exception:
            pass
        self.scene = None
        self.entities = {}
        self.cameras = {}
        self._is_built = False
