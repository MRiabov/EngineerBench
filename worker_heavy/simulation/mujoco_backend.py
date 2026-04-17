import contextlib
import threading
from typing import Any

import structlog

from shared.agents import get_video_render_resolution
from worker_heavy.simulation._mujoco_env import ensure_headless_physics

ensure_headless_physics()

import mujoco
import numpy as np
from mujoco.rendering.classic.renderer import Renderer as MujocoRenderer

from shared.enums import FailureReason

# ... (rest of imports)
logger = structlog.get_logger(__name__)
from shared.models.simulation import (
    RendererCapabilities,
    RenderMode,
    SimulationFailure,
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
from shared.workers.schema import RenderBundleObjectPoseRecord, SegmentationLegendEntry


class MuJoCoBackend(PhysicsRendererBackend):
    _lock = threading.Lock()

    def __init__(self, session_id: str | None = None):
        self.model = None
        self.data = None
        self.renderer = None
        self.render_width, self.render_height = get_video_render_resolution()
        self.custom_cameras = {}  # name -> mjvCamera
        self.smoke_test_mode = False
        self.session_id = session_id

        # ID caches to avoid expensive string lookups in loop
        self._body_id_cache = {}
        self._site_id_cache = {}
        self._actuator_id_cache = {}
        self._tendon_id_cache = {}
        self._camera_id_cache = {}

    def load_scene(self, scene: SimulationScene, render_only: bool = False) -> None:
        with self._lock:
            if scene.scene_path:
                self.model = mujoco.MjModel.from_xml_path(scene.scene_path)
                self.data = mujoco.MjData(self.model)
                mujoco.mj_forward(self.model, self.data)

                # Clear caches on new scene load
                self._body_id_cache.clear()
                self._site_id_cache.clear()
                self._actuator_id_cache.clear()
                self._tendon_id_cache.clear()
                self._camera_id_cache.clear()

                if self.smoke_test_mode:
                    # Accelerate simulation for smoke tests
                    self.model.opt.timestep = 0.05
            else:
                raise ValueError("MuJoCoBackend requires scene_path")

    def _get_body_id(self, name: str) -> int:
        if name not in self._body_id_cache:
            self._body_id_cache[name] = mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_BODY, name
            )
        return self._body_id_cache[name]

    def _get_site_id(self, name: str) -> int:
        if name not in self._site_id_cache:
            self._site_id_cache[name] = mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_SITE, name
            )
        return self._site_id_cache[name]

    def _get_actuator_id(self, name: str) -> int:
        if name not in self._actuator_id_cache:
            self._actuator_id_cache[name] = mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, name
            )
        return self._actuator_id_cache[name]

    def _get_tendon_id(self, name: str) -> int:
        if name not in self._tendon_id_cache:
            self._tendon_id_cache[name] = mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_TENDON, name
            )
        return self._tendon_id_cache[name]

    def _get_camera_id(self, name: str) -> int:
        if name not in self._camera_id_cache:
            self._camera_id_cache[name] = mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_CAMERA, name
            )
        return self._camera_id_cache[name]

    def step(self, dt: float) -> StepResult:
        with self._lock:
            if self.model is None or self.data is None:
                raise RuntimeError("Scene not loaded")

        # In MuJoCo, dt is usually model.opt.timestep
        # If passed dt != model.opt.timestep, we might need multiple steps or to change model.opt.timestep
        # For now, we assume dt is a single step or we do multiple steps to reach dt

        target_time = self.data.time + dt
        while self.data.time < target_time:
            # Check for instability before step
            if np.any(np.isnan(self.data.qpos)) or np.any(np.isnan(self.data.qvel)):
                return StepResult(
                    time=self.data.time,
                    success=False,
                    failure=SimulationFailure(reason=FailureReason.PHYSICS_INSTABILITY),
                )

            mujoco.mj_step(self.model, self.data)

            # Check for instability after step
            if np.any(np.isnan(self.data.qpos)) or np.any(np.isnan(self.data.qvel)):
                return StepResult(
                    time=self.data.time,
                    success=False,
                    failure=SimulationFailure(reason=FailureReason.PHYSICS_INSTABILITY),
                )

        return StepResult(time=self.data.time, success=True)

    def get_time(self) -> float:
        if self.data is None:
            return 0.0
        return float(self.data.time)

    def get_body_state(self, body_id: str) -> BodyState:
        # MuJoCo uses integer IDs or names
        try:
            bid = self._get_body_id(body_id)
        except:
            bid = int(body_id)

        if bid == -1:
            raise ValueError(f"Body {body_id} not found")

        return BodyState(
            pos=tuple(self.data.xpos[bid].tolist()),
            quat=tuple(self.data.xquat[bid].tolist()),
            vel=tuple(self.data.cvel[bid][3:].tolist()),
            angvel=tuple(self.data.cvel[bid][:3].tolist()),
        )

    def get_state(self) -> dict[str, Any]:
        if self.data is None:
            return {}
        return {
            "time": self.data.time,
            "qpos": self.data.qpos.tolist(),
            "qvel": self.data.qvel.tolist(),
            "act": self.data.act.tolist() if self.model and self.model.na > 0 else [],
        }

    def get_particle_positions(self) -> np.ndarray | None:
        # MuJoCo (rigid only) does not have particles
        return None

    # Rendering & Visualization
    def render(self) -> np.ndarray:
        # Default render should work even when the scene has no named cameras.
        # In that case, fall back to MuJoCo's free/default view rather than
        # forcing a synthetic camera name that may not exist in the XML.
        cam_name = None
        if self.model and self.model.ncam > 0:
            cam_name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_CAMERA, 0)

        if cam_name:
            return self.render_camera(cam_name, self.render_width, self.render_height)

        frame, _, _ = self.render_camera_modalities(
            None,
            self.render_width,
            self.render_height,
            include_rgb=True,
            include_depth=False,
            include_segmentation=False,
        )
        if frame is None:
            raise RuntimeError("RGB rendering was disabled for render")
        return frame

    def get_render_capabilities(self) -> RendererCapabilities:
        return RendererCapabilities(
            backend_name="mujoco",
            artifact_modes_supported=[RenderMode.SIMULATION_VIDEO],
            supports_default_view=True,
            supports_named_cameras=True,
            supports_rgb=True,
            supports_depth=True,
            supports_segmentation=True,
            default_view_label="free",
        )

    def render_camera(self, camera_name: str, width: int, height: int) -> np.ndarray:
        frame, _, _ = self.render_camera_modalities(
            camera_name,
            width,
            height,
            include_rgb=True,
            include_depth=False,
            include_segmentation=False,
        )
        if frame is None:
            raise RuntimeError("RGB rendering was disabled for render_camera")
        return frame

    def render_camera_modalities(
        self,
        camera_name: str | None,
        width: int,
        height: int,
        *,
        include_rgb: bool = True,
        include_depth: bool = True,
        include_segmentation: bool = True,
    ) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
        logger.debug(
            "mujoco_render_camera_modalities_start",
            camera_name=camera_name,
            width=width,
            height=height,
            include_rgb=include_rgb,
            include_depth=include_depth,
            include_segmentation=include_segmentation,
            session_id=self.session_id,
        )
        try:
            # Recreate renderer every time to avoid resolution/framebuffer issues
            if self.renderer is not None:
                with contextlib.suppress(BaseException):
                    self.renderer.close()

            self.renderer = MujocoRenderer(self.model, height, width)

            # Require an explicit camera. Silent default-view fallback hides bad
            # scene contracts and makes render failures look like success.
            cam = self.custom_cameras.get(camera_name, camera_name)
            if isinstance(cam, str):
                cid = self._get_camera_id(cam)
                if cid == -1:
                    raise ValueError(f"Unknown MuJoCo camera: {cam}")

            frame = None
            depth_frame = None
            segmentation_frame = None

            if include_rgb:
                if cam is None:
                    self.renderer.update_scene(self.data)
                else:
                    self.renderer.update_scene(self.data, camera=cam)
                frame = np.array(self.renderer.render(), copy=True)

            if include_depth:
                self.renderer.enable_depth_rendering()
                if cam is None:
                    self.renderer.update_scene(self.data)
                else:
                    self.renderer.update_scene(self.data, camera=cam)
                depth_frame = np.array(self.renderer.render(), copy=True)
                self.renderer.disable_depth_rendering()

            if include_segmentation:
                self.renderer.enable_segmentation_rendering()
                if cam is None:
                    self.renderer.update_scene(self.data)
                else:
                    self.renderer.update_scene(self.data, camera=cam)
                # MuJoCo returns (objid, objtype) pairs per pixel in segmentation mode.
                segmentation_frame = np.array(self.renderer.render(), copy=True)
                self.renderer.disable_segmentation_rendering()

            logger.debug(
                "mujoco_render_camera_modalities_complete",
                camera_name=camera_name,
                width=width,
                height=height,
                include_rgb=include_rgb,
                include_depth=include_depth,
                include_segmentation=include_segmentation,
                session_id=self.session_id,
                rgb_shape=tuple(frame.shape) if frame is not None else None,
                depth_shape=tuple(depth_frame.shape)
                if depth_frame is not None
                else None,
                segmentation_shape=(
                    tuple(segmentation_frame.shape)
                    if segmentation_frame is not None
                    else None
                ),
            )
            return frame, depth_frame, segmentation_frame
        except Exception as exc:
            logger.error(
                "mujoco_render_camera_modalities_failed",
                camera_name=camera_name,
                width=width,
                height=height,
                include_rgb=include_rgb,
                include_depth=include_depth,
                include_segmentation=include_segmentation,
                session_id=self.session_id,
                error=str(exc),
            )
            raise

    def describe_segmentation(
        self, segmentation_frame: np.ndarray
    ) -> list[SegmentationLegendEntry]:
        if segmentation_frame.ndim < 3 or segmentation_frame.shape[2] < 2:
            return []

        obj_ids = segmentation_frame[..., 0].astype(np.int64, copy=False)
        obj_types = segmentation_frame[..., 1].astype(np.int64, copy=False)
        valid_mask = (obj_ids >= 0) & (obj_types >= 0)
        if not valid_mask.any():
            return []

        unique_pairs = np.unique(
            np.stack((obj_ids[valid_mask], obj_types[valid_mask]), axis=1),
            axis=0,
        )

        legend: list[SegmentationLegendEntry] = []
        for obj_id, obj_type in unique_pairs:
            color = self._stable_segmentation_color(int(obj_id), int(obj_type))
            color_hex = "#{:02X}{:02X}{:02X}".format(*color)
            object_type_name = self._mjtobj_name(int(obj_type))
            body_name = None
            geom_name = None
            instance_name = f"{object_type_name.lower()}:{int(obj_id)}"
            semantic_label = instance_name

            if int(obj_type) == int(mujoco.mjtObj.mjOBJ_GEOM):
                geom_name = mujoco.mj_id2name(
                    self.model, mujoco.mjtObj.mjOBJ_GEOM, int(obj_id)
                )
                if 0 <= int(obj_id) < self.model.ngeom:
                    body_id = int(self.model.geom_bodyid[int(obj_id)])
                    body_name = mujoco.mj_id2name(
                        self.model, mujoco.mjtObj.mjOBJ_BODY, body_id
                    )
                semantic_label = body_name or geom_name or semantic_label
                instance_name = body_name or geom_name or instance_name
            elif int(obj_type) == int(mujoco.mjtObj.mjOBJ_BODY):
                body_name = mujoco.mj_id2name(
                    self.model, mujoco.mjtObj.mjOBJ_BODY, int(obj_id)
                )
                semantic_label = body_name or semantic_label
                instance_name = body_name or instance_name
            else:
                generic_name = self._safe_id2name(int(obj_type), int(obj_id))
                semantic_label = generic_name or semantic_label
                instance_name = generic_name or instance_name

            legend.append(
                SegmentationLegendEntry(
                    instance_id=f"{object_type_name.lower()}:{int(obj_id)}",
                    instance_name=instance_name,
                    semantic_label=semantic_label,
                    object_type=object_type_name.lower(),
                    object_id=int(obj_id),
                    body_name=body_name,
                    geom_name=geom_name,
                    color_rgb=color,
                    color_hex=color_hex,
                )
            )

        return sorted(
            legend, key=lambda entry: (entry.semantic_label, entry.instance_id)
        )

    def colorize_segmentation(self, segmentation_frame: np.ndarray) -> np.ndarray:
        if segmentation_frame.ndim < 3 or segmentation_frame.shape[2] < 2:
            return np.zeros((*segmentation_frame.shape[:2], 3), dtype=np.uint8)

        obj_ids = segmentation_frame[..., 0].astype(np.int64, copy=False)
        obj_types = segmentation_frame[..., 1].astype(np.int64, copy=False)
        valid_mask = (obj_ids >= 0) & (obj_types >= 0)
        seg_image = np.zeros((*segmentation_frame.shape[:2], 3), dtype=np.uint8)
        if not valid_mask.any():
            return seg_image

        unique_pairs = np.unique(
            np.stack((obj_ids[valid_mask], obj_types[valid_mask]), axis=1),
            axis=0,
        )
        for obj_id, obj_type in unique_pairs:
            color = self._stable_segmentation_color(int(obj_id), int(obj_type))
            pair_mask = valid_mask & (obj_ids == obj_id) & (obj_types == obj_type)
            seg_image[pair_mask] = color
        return seg_image

    @staticmethod
    def _stable_segmentation_color(obj_id: int, obj_type: int) -> tuple[int, int, int]:
        seed = ((obj_type + 1) * 73856093) ^ ((obj_id + 1) * 19349663)
        red = 64 + (seed & 0x7F)
        green = 64 + ((seed >> 7) & 0x7F)
        blue = 64 + ((seed >> 14) & 0x7F)
        return red, green, blue

    @staticmethod
    def _mjtobj_name(obj_type: int) -> str:
        with contextlib.suppress(Exception):
            return mujoco.mjtObj(obj_type).name
        return f"OBJ_{obj_type}"

    def _safe_id2name(self, obj_type: int, obj_id: int) -> str | None:
        with contextlib.suppress(Exception):
            return mujoco.mj_id2name(self.model, mujoco.mjtObj(obj_type), obj_id)
        return None

    def set_camera(
        self,
        camera_name: str,
        pos: tuple[float, float, float] | None = None,
        lookat: tuple[float, float, float] | None = None,
        up: tuple[float, float, float] | None = None,
        fov: float | None = None,
    ) -> None:
        if camera_name not in self.custom_cameras:
            cam = mujoco.MjvCamera()
            mujoco.mjv_defaultCamera(cam)
            self.custom_cameras[camera_name] = cam

        cam = self.custom_cameras[camera_name]
        if pos is not None:
            # mjvCamera doesn't have direct pos, but lookat and distance/azimuth/elevation
            # For exact pos, we might need a workaround or just use lookat/dist
            # MuJoCo cameras usually look at something.
            # If we want to set pos, we might need to calculate dist/azim/elev
            # For simplicity, we'll support lookat and distance-based approach if pos is used.
            # Or we can use mjv_setCamera (not available in all versions)

            # Simple heuristic: if pos is provided, assume it's for distance calculation if lookat is also there
            if lookat is not None:
                p = np.array(pos)
                l = np.array(lookat)
                diff = p - l
                cam.distance = np.linalg.norm(diff)
                # azim/elev calculation
                cam.azimuth = np.rad2deg(np.arctan2(diff[0], diff[1]))
                cam.elevation = np.rad2deg(np.arcsin(diff[2] / cam.distance))

        if lookat is not None:
            cam.lookat = np.array(lookat)

        if fov is not None:
            # fov is in model.cam_fovy usually, but MjvCamera doesn't have fov
            pass

    def get_camera_matrix(self, camera_name: str) -> np.ndarray:
        # Return 4x4 projection * view matrix or similar
        # This is a bit complex in MuJoCo, for now returning identity or placeholder
        # Actual implementation would use mjv_updateScene and camera params
        return np.eye(4)

    def set_site_pos(self, site_name: str, pos: np.ndarray) -> None:
        sid = self._get_site_id(site_name)
        if sid != -1:
            self.model.site_pos[sid] = pos
        else:
            raise ValueError(f"Site {site_name} not found")

    def get_contact_forces(self) -> list[ContactForce]:
        forces = []
        for i in range(self.data.ncon):
            contact = self.data.contact[i]
            c_force = np.zeros(6)
            mujoco.mj_contactForce(self.model, self.data, i, c_force)

            # c_force is in contact frame: [normal, tangential1, tangential2, torque1, torque2, torque3]
            # Convert to world frame if needed

            body1_name = mujoco.mj_id2name(
                self.model,
                mujoco.mjtObj.mjOBJ_BODY,
                self.model.geom_bodyid[contact.geom1],
            )
            body2_name = mujoco.mj_id2name(
                self.model,
                mujoco.mjtObj.mjOBJ_BODY,
                self.model.geom_bodyid[contact.geom2],
            )

            forces.append(
                ContactForce(
                    body1=body1_name or f"body_{self.model.geom_bodyid[contact.geom1]}",
                    body2=body2_name or f"body_{self.model.geom_bodyid[contact.geom2]}",
                    force=tuple(c_force[:3].tolist()),
                    position=tuple(contact.pos.tolist()),
                )
            )
        return forces

    def get_site_state(self, site_name: str) -> SiteState:
        sid = self._get_site_id(site_name)
        if sid == -1:
            raise ValueError(f"Site {site_name} not found")

        quat = np.zeros(4)
        mujoco.mju_mat2Quat(quat, self.data.site_xmat[sid])

        return SiteState(
            pos=tuple(self.data.site_xpos[sid].tolist()),
            quat=tuple(quat.tolist()),
            size=tuple(self.model.site_size[sid].tolist()),
        )

    def get_actuator_state(self, actuator_name: str) -> ActuatorState:
        aid = self._get_actuator_id(actuator_name)
        if aid == -1:
            raise ValueError(f"Actuator {actuator_name} not found")

        # Get actuator velocity. In MuJoCo, this depends on the joint it's attached to.
        vel = 0.0
        # actuator_velocity is available in newer mujoco
        if hasattr(self.data, "actuator_velocity"):
            vel = self.data.actuator_velocity[aid]
        else:
            # Fallback: find joint and use its velocity
            trntype = self.model.actuator_trntype[aid]
            if trntype == mujoco.mjtTrn.mjTRN_JOINT:
                joint_id = self.model.actuator_trnid[aid, 0]
                qvel_adr = self.model.jnt_doveladr[joint_id]
                vel = self.data.qvel[qvel_adr]

        return ActuatorState(
            force=self.data.actuator_force[aid],
            velocity=float(vel),
            ctrl=self.data.ctrl[aid],
            forcerange=tuple(self.model.actuator_forcerange[aid].tolist()),
        )

    def apply_control(self, control_inputs: dict[str, float]) -> None:
        for name, value in control_inputs.items():
            aid = self._get_actuator_id(name)
            if aid != -1:
                self.data.ctrl[aid] = value

    def get_all_body_names(self) -> list[str]:
        return [
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, i)
            for i in range(self.model.nbody)
        ]

    def get_all_actuator_names(self) -> list[str]:
        return [
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
            for i in range(self.model.nu)
        ]

    def get_all_site_names(self) -> list[str]:
        return [
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_SITE, i)
            for i in range(self.model.nsite)
        ]

    def get_all_tendon_names(self) -> list[str]:
        return [
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_TENDON, i)
            for i in range(self.model.ntendon)
        ]

    def get_all_camera_names(self) -> list[str]:
        names = [
            name
            for name in (
                mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_CAMERA, i)
                for i in range(self.model.ncam)
            )
            if name
        ]
        # Include custom cameras
        for name in self.custom_cameras:
            if name not in names:
                names.append(name)
        return names

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

    def check_collision(self, body_name: str, site_name: str) -> bool:
        bid = self._get_body_id(body_name)
        sid = self._get_site_id(site_name)

        if bid == -1 or sid == -1:
            return False

        geom_start = self.model.body_geomadr[bid]
        geom_num = self.model.body_geomnum[bid]

        zone_pos = self.data.site_xpos[sid]
        zone_size = self.model.site_size[sid]
        zone_type = self.model.site_type[sid]
        site_mat = self.data.site_xmat[sid].reshape(3, 3)

        # Fallback: check body center if no geoms
        if geom_num == 0:
            body_pos = self.data.xpos[bid]
            diff = body_pos - zone_pos
            v_local = diff @ site_mat
            if zone_type == mujoco.mjtGeom.mjGEOM_BOX:
                return all(np.abs(v_local) <= zone_size[:3])
            if zone_type == mujoco.mjtGeom.mjGEOM_SPHERE:
                return np.linalg.norm(diff) <= zone_size[0]
            return False

        for i in range(geom_num):
            geom_id = geom_start + i
            geom_type = self.model.geom_type[geom_id]
            geom_pos = self.data.geom_xpos[geom_id]
            geom_mat = self.data.geom_xmat[geom_id].reshape(3, 3)

            # Broadphase check: skip if geom is clearly outside zone
            geom_rbound = self.model.geom_rbound[geom_id]
            # Max possible distance from site center to site bounds
            max_site_dist = np.max(zone_size[:3])
            dist = np.linalg.norm(geom_pos - zone_pos)
            if dist > geom_rbound + max_site_dist + 0.01:
                continue

            vertices = []
            if geom_type == mujoco.mjtGeom.mjGEOM_MESH:
                mesh_id = self.model.geom_dataid[geom_id]
                vert_adr = self.model.mesh_vertadr[mesh_id]
                vert_num = self.model.mesh_vertnum[mesh_id]
                raw_verts = self.model.mesh_vert[vert_adr : vert_adr + vert_num]
                vertices = geom_pos + raw_verts @ geom_mat.T
            else:
                # For non-mesh geoms, just use center for now
                vertices = np.array([geom_pos])

            # Check vertices against the zone
            if zone_type == mujoco.mjtGeom.mjGEOM_BOX:
                diff = vertices - zone_pos
                v_local = diff @ site_mat
                # Use np.atleast_2d to handle single vertex case
                in_box = np.all(np.abs(np.atleast_2d(v_local)) <= zone_size[:3], axis=1)
                if np.any(in_box):
                    return True
            elif zone_type == mujoco.mjtGeom.mjGEOM_SPHERE:
                diff = vertices - zone_pos
                dists = np.linalg.norm(np.atleast_2d(diff), axis=1)
                if np.any(dists < zone_size[0]):
                    return True
        return False

    def get_tendon_tension(self, tendon_name: str) -> float:
        tid = self._get_tendon_id(tendon_name)
        if tid == -1:
            raise ValueError(f"Tendon {tendon_name} not found")
        return float(self.data.ten_force[tid])

    def apply_jitter(self, body_name: str, jitter: tuple[float, float, float]) -> None:
        """Apply position jitter to a body in MuJoCo."""
        body_id = self._get_body_id(body_name)
        if body_id == -1:
            return

        # T019: Locate the free joint of the body to apply jitter instead of hardcoded indices
        jnt_adr = self.model.body_jntadr[body_id]
        jnt_num = self.model.body_jntnum[body_id]

        for i in range(jnt_num):
            j_id = jnt_adr + i
            if self.model.jnt_type[j_id] == mujoco.mjtJoint.mjJNT_FREE:
                q_adr = self.model.jnt_qposadr[j_id]
                self.data.qpos[q_adr : q_adr + 3] += np.array(jitter)
                mujoco.mj_forward(self.model, self.data)
                return

        # If no free joint found, we might be trying to jitter a fixed body or one with specific joints.
        # Fallback to legacy behavior if it's the first body (usually the target)
        if body_id == 1:
            self.data.qpos[0:3] += np.array(jitter)
            mujoco.mj_forward(self.model, self.data)

    def reset(self) -> None:
        """Reset MuJoCo state without recompiling the model."""
        if self.model is None or self.data is None:
            raise RuntimeError("Scene not loaded")

        mujoco.mj_resetData(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)

    def close(self) -> None:
        """Close MuJoCo backend and release resources."""
        if self.renderer:
            with contextlib.suppress(Exception):
                self.renderer.close()
            self.renderer = None
        self.data = None
        self.model = None

        self._body_id_cache.clear()
        self._site_id_cache.clear()
        self._actuator_id_cache.clear()
        self._tendon_id_cache.clear()
        self._camera_id_cache.clear()
