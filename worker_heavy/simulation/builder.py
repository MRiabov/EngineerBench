from __future__ import annotations

import json
import math
import tempfile
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.dom import minidom

import structlog
import trimesh
from build123d import Compound, Solid, export_stl

from shared.enums import ZoneType
from shared.simulation.scene_builder import (
    CommonAssemblyTraverser,
    materialize_payload,
)

# YACV removed in favor of custom trimesh-based export capable of preserving topology
# try:
#     from yacv.exporter import export_all
# except ImportError:
#     export_all = None

if TYPE_CHECKING:
    from shared.models.schemas import BenchmarkDefinition, PayloadPart


logger = structlog.get_logger(__name__)


class MeshProcessor:
    """Handles conversion from build123d geometry to physics-ready meshes.

    Per architecture spec:
    - Exports to OBJ format (less bulky than STL)
    - Recenters parts to origin before export (position comes from MJCF body)
    - Validates watertightness for all meshes
    """

    def process_geometry(
        self,
        part: Solid | Compound,
        filepath: Path,
        decompose: bool = True,
        use_vhacd: bool = False,
        tolerance: float = 0.1,
        angular_tolerance: float = 0.1,
    ) -> list[Path]:
        """Converts a build123d object to OBJ and GLB file(s).

        OBJ is used for physics simulation (MuJoCo/Genesis),
        while GLB is used for efficient frontend visualization.

        Args:
            part: The build123d geometry to convert
            filepath: Output base path
            decompose: Whether to compute convex hull for physics
            use_vhacd: Whether to use V-HACD decomposition for concave shapes
            tolerance: Linear deflection tolerance for STL export
            angular_tolerance: Angular deflection tolerance for STL export

        Returns:
            List of output file paths (both .obj and .glb)

        Raises:
            ValueError: If mesh is not watertight
        """
        # Ensure the directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Export build123d object to a temporary STL file
        temp_stl = filepath.with_suffix(".tmp.stl")
        export_stl(
            part, temp_stl, tolerance=tolerance, angular_tolerance=angular_tolerance
        )

        output_paths = []
        try:
            mesh = trimesh.load(temp_stl)

            # If trimesh loaded a Scene, merge it into a single mesh
            if isinstance(mesh, trimesh.Scene):
                mesh = mesh.dump(concatenate=True)

            # Recenter mesh to origin (position will come from MJCF body pos)
            mesh = self._recenter_mesh(mesh)

            # Validate watertightness
            mesh = self._validate_watertight(mesh, filepath.name)

            if decompose:
                if use_vhacd:
                    try:
                        decomposed = trimesh.decomposition.convex_decomposition(mesh)
                        if isinstance(decomposed, list) and len(decomposed) > 1:
                            for i, dm in enumerate(decomposed):
                                # Export both OBJ and GLB for each decomposed part
                                obj_sub = filepath.with_name(f"{filepath.stem}_{i}.obj")
                                glb_sub = filepath.with_name(f"{filepath.stem}_{i}.glb")
                                dm.export(obj_sub, file_type="obj")
                                dm.export(glb_sub, file_type="glb")
                                output_paths.extend([obj_sub, glb_sub])
                            return output_paths
                    except Exception:
                        # Fallback to single convex hull if VHACD fails
                        pass

                mesh = self.compute_convex_hull(mesh)

            # Export in both formats
            obj_path = filepath.with_suffix(".obj")
            glb_path = filepath.with_suffix(".glb")

            mesh.export(obj_path, file_type="obj")

            # Custom topology-preserving export for frontend viewer
            try:
                self.export_topology_glb(part, glb_path)
            except Exception as e:
                logger.warning("topology_export_failed", error=str(e))
                # Fallback to simple mesh export
                mesh.export(glb_path, file_type="glb")

            output_paths.extend([obj_path, glb_path])
        finally:
            if temp_stl.exists():
                temp_stl.unlink()

        return output_paths

    def export_topology_glb(self, part: Solid | Compound, filepath: Path):
        """
        Exports the part to GLB with separate meshes for faces to allow selection in UI.
        """
        scene = trimesh.Scene()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # 1. Export Faces
            # access faces via topological properties
            faces = part.faces()
            for i, face in enumerate(faces):
                fname = tmp_path / f"face_{i}.stl"
                export_stl(face, fname)

                try:
                    # Load the face mesh
                    face_mesh = trimesh.load(fname)
                    if isinstance(face_mesh, trimesh.Scene):
                        face_mesh = face_mesh.dump(concatenate=True)

                    # Add to scene with specific name for UI selection
                    # The node name allows the frontend to identify it as 'face_X'
                    scene.add_geometry(
                        face_mesh,
                        node_name=f"face_{i}",
                        geom_name=f"face_{i}_geom",
                    )
                except Exception as e:
                    logger.warning(
                        "failed_to_export_face",
                        face_index=i,
                        error=str(e),
                    )

        # Export the scene to GLB
        scene.export(filepath, file_type="glb")

    def _recenter_mesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Recenter mesh to origin (0,0,0) based on its centroid."""
        centroid = mesh.centroid
        mesh.apply_translation(-centroid)
        return mesh

    def _validate_watertight(self, mesh: trimesh.Trimesh, name: str) -> trimesh.Trimesh:
        """Validate that mesh is watertight (required per architecture spec)."""
        if mesh.is_watertight:
            return mesh

        # T008: Attempt repair before failing
        try:
            # Basic repairs
            mesh.fill_holes()
            mesh.fix_normals()
            mesh.fix_inversion()
        except Exception:
            pass

        if mesh.is_watertight:
            return mesh

        # Last ditch: compute convex hull
        # This is safe for convex shapes (like the sphere in the repro)
        # For non-convex shapes, this simplifies geometry, but it ensures simulation runs.
        logger.warning(
            "mesh_not_watertight_falling_back_to_convex_hull",
            mesh_name=name,
        )
        try:
            hull = mesh.convex_hull
            if hull.is_watertight:
                return hull
        except Exception:
            pass

        raise ValueError(
            f"Mesh '{name}' is not watertight. "
            "All meshes must be watertight for physics simulation."
        )

    def compute_convex_hull(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Computes the convex hull of a mesh for better physics stability."""
        return mesh.convex_hull


class SceneCompiler:
    """Generates MJCF XML for MuJoCo simulation."""

    def __init__(self, model_name: str = "simulation_scene"):
        self.root = ET.Element("mujoco", model=model_name)

        # Basic configuration
        self.compiler = ET.SubElement(
            self.root, "compiler", angle="degree", coordinate="local", assetdir="assets"
        )
        ET.SubElement(self.root, "option", integrator="RK4", timestep="0.002")
        self.actuators = ET.SubElement(self.root, "actuator")

        # Visual assets and lighting
        visual = ET.SubElement(self.root, "visual")
        ET.SubElement(visual, "global", offwidth="2048", offheight="2048")
        ET.SubElement(
            visual,
            "headlight",
            diffuse="0.6 0.6 0.6",
            ambient="0.3 0.3 0.3",
            specular="0 0 0",
        )

        self.assets = ET.SubElement(self.root, "asset")
        # Default floor texture and material
        ET.SubElement(
            self.assets,
            "texture",
            name="grid",
            type="2d",
            builtin="checker",
            rgb1=".1 .2 .3",
            rgb2=".2 .3 .4",
            width="300",
            height="300",
        )
        ET.SubElement(
            self.assets,
            "material",
            name="grid",
            texture="grid",
            texrepeat="1 1",
            texuniform="true",
        )

        self.worldbody = ET.SubElement(self.root, "worldbody")
        ET.SubElement(
            self.worldbody, "light", pos="0 0 3", dir="0 0 -1", directional="true"
        )
        ET.SubElement(
            self.worldbody,
            "geom",
            name="floor",
            size="1000 1000 0.1",
            type="plane",
            material="grid",
        )

        # Body lookup cache
        self.body_elements: dict[str, ET.Element] = {}

        # Equality constraints
        self.equality = ET.SubElement(self.root, "equality")

    def add_mesh_asset(self, name: str, file_name: str):
        """Registers a mesh file in the MJCF assets."""
        ET.SubElement(self.assets, "mesh", name=name, file=file_name)

    def add_site(
        self,
        name: str,
        pos: list[float],
        size: float = 0.001,
        rgba: str | None = None,
        parent_body_name: str | None = None,
    ):
        """Adds a site to the worldbody or a specific body."""
        parent = self.worldbody
        if parent_body_name and parent_body_name in self.body_elements:
            parent = self.body_elements[parent_body_name]

        attrs = {"name": name, "pos": " ".join(map(str, pos)), "size": str(size)}
        if rgba:
            attrs["rgba"] = rgba
        ET.SubElement(parent, "site", **attrs)

    def add_spatial_tendon(
        self,
        name: str,
        site_names: list[str],
        width: float = 0.002,
        rgba: str = "0.1 0.1 0.8 1",
        limited: bool = False,
        tendon_range: list[float] | None = None,
        stiffness: float | None = None,
        damping: float | None = None,
    ):
        """Adds a spatial tendon connecting a sequence of sites."""
        if not hasattr(self, "tendon_element"):
            self.tendon_element = ET.SubElement(self.root, "tendon")

        attrs = {"name": name, "width": str(width), "rgba": rgba}
        if limited and tendon_range:
            attrs["limited"] = "true"
            attrs["range"] = " ".join(map(str, tendon_range))
        if stiffness is not None:
            attrs["stiffness"] = str(stiffness)
        if damping is not None:
            attrs["damping"] = str(damping)

        spatial = ET.SubElement(self.tendon_element, "spatial", **attrs)
        for site_name in site_names:
            ET.SubElement(spatial, "site", site=site_name)

    def add_weld(self, body1: str, body2: str):
        """Adds a weld constraint between two bodies."""
        ET.SubElement(self.equality, "weld", body1=body1, body2=body2)

    def add_body(
        self,
        name: str,
        mesh_names: list[str] | None = None,
        pos: list[float] | None = None,
        euler: list[float] | None = None,
        is_zone: bool = False,
        zone_type: ZoneType | None = None,
        zone_size: list[float] | None = None,
        is_fixed: bool = False,
        joint_type: str | None = None,
        joint_axis: list[float] | None = None,
        joint_range: list[float] | None = None,
        geom_rgba: str | None = None,
    ):
        """Adds a body to the worldbody. Can be a physical mesh or a logical zone.

        Args:
            name: Body identifier
            mesh_names: List of mesh asset names for this body
            pos: Position [x, y, z], defaults to [0, 0, 0]
            euler: Euler angles [rx, ry, rz], defaults to [0, 0, 0]
            is_zone: Whether this is a logical zone (goal/build/forbid)
            zone_type: Logical zone type.
            zone_size: Half-extents for zone box
            is_fixed: If True, part is fixed (no free joint added)
            joint_type: Optional joint type (e.g., "hinge", "slide").
            joint_axis: Optional joint axis [x, y, z].
            joint_range: Optional joint limits [min, max].
        """
        if pos is None:
            pos = [0, 0, 0]
        if euler is None:
            euler = [0, 0, 0]

        body = ET.SubElement(
            self.worldbody, "body", name=name, pos=" ".join(map(str, pos))
        )
        self.body_elements[name] = body
        if any(v != 0 for v in euler):
            body.set("euler", " ".join(map(str, euler)))

        if name == "target_box":
            # Add tracking camera for the main object
            ET.SubElement(
                self.worldbody,
                "camera",
                name="main",
                pos="1 1 1",
                mode="trackcom",
                target="target_box",
            )

        if is_zone:
            # Zone Logic (T005): goal = green, forbid = red
            if zone_type == ZoneType.GOAL:
                rgba = "0 1 0 0.3"
            elif zone_type == ZoneType.BUILD:
                rgba = "0.55 0.55 0.55 0.2"
            else:
                rgba = "1 0 0 0.3"
            size_str = " ".join(map(str, zone_size)) if zone_size else "0.05"
            ET.SubElement(body, "site", name=name, type="box", size=size_str, rgba=rgba)
        else:
            if mesh_names:
                for mesh_name in mesh_names:
                    geom_attrs = {"type": "mesh", "mesh": mesh_name}
                    if geom_rgba:
                        geom_attrs["rgba"] = geom_rgba
                    ET.SubElement(body, "geom", **geom_attrs)

            # Handle joints
            if is_fixed:
                return

            if joint_type:
                # Add specific joint
                joint_attrs = {"type": joint_type, "name": f"{name}_joint"}
                if joint_axis:
                    joint_attrs["axis"] = " ".join(map(str, joint_axis))
                if joint_range:
                    joint_attrs["range"] = " ".join(map(str, joint_range))
                ET.SubElement(body, "joint", **joint_attrs)
            else:
                # Default to free joint
                logger.warning(
                    "Adding free joint to body '%s'. This part will fall if not supported. "
                    "Use 'is_fixed=True' or 'constraint' attribute to secure it.",
                    name,
                )
                ET.SubElement(body, "joint", type="free")

    def add_actuator(
        self,
        name: str,
        joint: str,
        kp: float | None = None,
        kv: float | None = None,
        forcerange: tuple[float, float] | None = None,
        actuator_type: str = "position",
    ):
        """Adds an actuator to control a joint."""
        # Default gains if not derived
        final_kp = kp if kp is not None else 10.0
        final_kv = kv if kv is not None else 1.0
        final_forcerange = forcerange

        attrs = {
            "name": name,
            "joint": joint,
        }
        if actuator_type == "position":
            attrs["kp"] = str(final_kp)
            attrs["kv"] = str(final_kv)
        elif actuator_type == "velocity":
            attrs["kv"] = str(final_kv)
        else:
            attrs["kp"] = str(final_kp)
            attrs["kv"] = str(final_kv)

        if final_forcerange is not None:
            attrs["forcerange"] = f"{final_forcerange[0]} {final_forcerange[1]}"

        ET.SubElement(self.actuators, actuator_type, **attrs)

    def save(self, path: Path):
        """Saves the MJCF XML to a file."""
        xml_str = ET.tostring(self.root, encoding="utf-8")
        pretty_xml = minidom.parseString(xml_str).toprettyxml(indent="  ")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            f.write(pretty_xml)


class SimulationBuilderBase(ABC):
    """Abstract base class for simulation builders."""

    def __init__(self, output_dir: Path, use_vhacd: bool = False):
        self.output_dir = Path(output_dir)
        self.assets_dir = self.output_dir / "assets"
        self.processor = MeshProcessor()
        self.use_vhacd = use_vhacd

    @abstractmethod
    def build_from_assembly(
        self,
        assembly: Compound,
        objectives: BenchmarkDefinition | None = None,
        payload_parts: list["PayloadPart"] | None = None,
        smoke_test_mode: bool = False,
    ) -> Path:
        """Converts an assembly of parts into a simulation scene."""
        pass


class MuJoCoSimulationBuilder(SimulationBuilderBase):
    """Orchestrates the conversion of build123d assemblies to MuJoCo scenes."""

    def __init__(self, output_dir: Path, use_vhacd: bool = False):
        super().__init__(output_dir, use_vhacd)
        self.compiler = SceneCompiler()

    def build_from_assembly(
        self,
        assembly: Compound,
        objectives: BenchmarkDefinition | None = None,
        payload_parts: list["PayloadPart"] | None = None,
        smoke_test_mode: bool = False,
    ) -> Path:
        """Converts an assembly of parts into a MuJoCo scene.xml and associated STLs."""
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        weld_constraints = []
        body_locations = {}  # name -> (pos_mm, euler_deg)

        from worker_heavy.workbenches.config import load_config, load_merged_config

        custom_cfg_path = self.output_dir / "manufacturing_config.yaml"
        if custom_cfg_path.exists():
            mfg_config = load_merged_config(custom_cfg_path)
        else:
            mfg_config = load_config()

        # 1. Add zones from objectives if provided
        if objectives:
            # Add Goal Zone
            gz = objectives.objectives.goal_zone_mm
            # Calculate center and half-extents
            gz_pos = [
                (gz.min_mm[0] + gz.max_mm[0]) / 2,
                (gz.min_mm[1] + gz.max_mm[1]) / 2,
                (gz.min_mm[2] + gz.max_mm[2]) / 2,
            ]
            gz_size = [
                (gz.max_mm[0] - gz.min_mm[0]) / 2,
                (gz.max_mm[1] - gz.min_mm[1]) / 2,
                (gz.max_mm[2] - gz.min_mm[2]) / 2,
            ]
            self.compiler.add_body(
                name="zone_goal",
                is_zone=True,
                zone_type=ZoneType.GOAL,
                zone_size=gz_size,
                pos=gz_pos,
            )

            # Add Forbid Zones
            for i, fz in enumerate(objectives.objectives.forbid_zones):
                fz_pos = [
                    (fz.min_mm[0] + fz.max_mm[0]) / 2,
                    (fz.min_mm[1] + fz.max_mm[1]) / 2,
                    (fz.min_mm[2] + fz.max_mm[2]) / 2,
                ]
                fz_size = [
                    (fz.max_mm[0] - fz.min_mm[0]) / 2,
                    (fz.max_mm[1] - fz.min_mm[1]) / 2,
                    (fz.max_mm[2] - fz.min_mm[2]) / 2,
                ]
                self.compiler.add_body(
                    name=f"zone_forbid_{i}_{fz.name}",
                    is_zone=True,
                    zone_type=ZoneType.FORBID,
                    zone_size=fz_size,
                    pos=fz_pos,
                )

            bz = objectives.objectives.build_zone_mm
            bz_pos = [
                (bz.min_mm[0] + bz.max_mm[0]) / 2,
                (bz.min_mm[1] + bz.max_mm[1]) / 2,
                (bz.min_mm[2] + bz.max_mm[2]) / 2,
            ]
            bz_size = [
                (bz.max_mm[0] - bz.min_mm[0]) / 2,
                (bz.max_mm[1] - bz.min_mm[1]) / 2,
                (bz.max_mm[2] - bz.min_mm[2]) / 2,
            ]
            self.compiler.add_body(
                name="zone_build",
                is_zone=True,
                zone_type=ZoneType.BUILD,
                zone_size=bz_size,
                pos=bz_pos,
            )

        # 2. Add parts from assembly
        parts_data = CommonAssemblyTraverser.traverse(assembly)

        for data in parts_data:
            if data.weld_target:
                weld_constraints.append((data.label, data.weld_target))

            if data.is_zone:
                self.compiler.add_body(
                    name=data.label,
                    is_zone=True,
                    zone_type=data.zone_type,
                    zone_size=data.zone_size_mm,
                    pos=data.pos_mm,
                    euler=data.euler_deg,
                )
            else:
                material_id = data.material_id
                mesh_path_base = self.assets_dir / data.label
                # Use coarser mesh for smoke tests
                tolerance = 1.0 if smoke_test_mode else 0.1
                saved_paths = self.processor.process_geometry(
                    data.part,
                    mesh_path_base,
                    use_vhacd=self.use_vhacd,
                    tolerance=tolerance,
                    angular_tolerance=tolerance,
                )
                obj_paths = [p for p in saved_paths if p.suffix == ".obj"]

                mesh_names = []
                for j, path in enumerate(obj_paths):
                    mesh_name = (
                        f"{data.label}_{j}" if len(obj_paths) > 1 else data.label
                    )
                    self.compiler.add_mesh_asset(name=mesh_name, file_name=path.name)
                    mesh_names.append(mesh_name)

                self.compiler.add_body(
                    name=data.label,
                    mesh_names=mesh_names,
                    pos=data.pos_mm,
                    euler=data.euler_deg,
                    is_fixed=data.is_fixed,
                    joint_type=data.joint_type,
                    joint_axis=data.joint_axis,
                    joint_range=data.joint_range,
                    geom_rgba=self._resolve_geom_rgba(material_id, mfg_config),
                )
                body_locations[data.label] = (data.pos_mm, data.euler_deg)

        # 3. Add the benchmark-mandated payload as a dynamic body.
        if objectives and getattr(objectives, "payload", None):
            moved = objectives.payload
            payload_object = materialize_payload(moved)
            moved_part = payload_object.geometry
            moved_body_name = payload_object.scene_name

            mesh_path_base = self.assets_dir / moved_body_name
            tolerance = 1.0 if smoke_test_mode else 0.1
            saved_paths = self.processor.process_geometry(
                moved_part,
                mesh_path_base,
                use_vhacd=self.use_vhacd,
                tolerance=tolerance,
                angular_tolerance=tolerance,
            )
            obj_paths = [p for p in saved_paths if p.suffix == ".obj"]
            mesh_names = []
            for j, path in enumerate(obj_paths):
                mesh_name = (
                    f"{moved_body_name}_{j}" if len(obj_paths) > 1 else moved_body_name
                )
                self.compiler.add_mesh_asset(name=mesh_name, file_name=path.name)
                mesh_names.append(mesh_name)

            self.compiler.add_body(
                name=moved_body_name,
                mesh_names=mesh_names,
                pos=[float(v) for v in payload_object.start_position_mm],
                euler=[0.0, 0.0, 0.0],
                is_fixed=False,
                geom_rgba=self._resolve_geom_rgba(
                    payload_object.material_id, mfg_config
                ),
            )
            if "main" not in self.compiler.body_elements:
                scene_span_mm = self._scene_diagonal_mm(assembly)
                if objectives is not None:
                    scene_span_mm = max(
                        scene_span_mm, self._objectives_diagonal_mm(objectives)
                    )
                # Prefer the fixed build-zone body as the camera target when
                # available. Tracking the payload body makes the view follow
                # the object and hides the corridor/goal scale in the video.
                camera_target = (
                    "zone_build"
                    if objectives is not None
                    and "zone_build" in self.compiler.body_elements
                    else moved_body_name
                )
                # Keep the overview far enough away to preserve route context.
                camera_distance_mm = max(scene_span_mm * 1.1, 250.0)
                camera_offset_mm = camera_distance_mm / math.sqrt(3.0)
                ET.SubElement(
                    self.compiler.worldbody,
                    "camera",
                    name="main",
                    pos=(
                        f"{camera_offset_mm:.6f} "
                        f"{camera_offset_mm:.6f} "
                        f"{camera_offset_mm:.6f}"
                    ),
                    mode="trackcom",
                    target=camera_target,
                )
            body_locations[moved_body_name] = (
                list(payload_object.start_position_mm),
                [0.0, 0.0, 0.0],
            )

        # Apply collected constraints

        for body1, body2 in weld_constraints:
            self.compiler.add_weld(body1, body2)

        scene_path = self.output_dir / "scene.xml"
        self.compiler.save(scene_path)
        return scene_path

    @staticmethod
    def _resolve_geom_rgba(material_id: str | None, mfg_config: Any) -> str | None:
        if not material_id:
            return None

        mat_def = mfg_config.materials.get(material_id)
        if mat_def is None and mfg_config.cnc:
            mat_def = mfg_config.cnc.materials.get(material_id)
        if mat_def is None and mfg_config.injection_molding:
            mat_def = mfg_config.injection_molding.materials.get(material_id)
        if mat_def is None and mfg_config.three_dp:
            mat_def = mfg_config.three_dp.materials.get(material_id)
        if mat_def is None or not mat_def.color:
            return None

        color = mat_def.color.lstrip("#")
        if len(color) != 6:
            return None
        r = int(color[0:2], 16) / 255
        g = int(color[2:4], 16) / 255
        b = int(color[4:6], 16) / 255
        return f"{r:.3f} {g:.3f} {b:.3f} 1"

    @staticmethod
    def _scene_diagonal_mm(assembly: Compound) -> float:
        bbox = assembly.bounding_box()
        dx = float(bbox.size.X)
        dy = float(bbox.size.Y)
        dz = float(bbox.size.Z)
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @staticmethod
    def _objectives_diagonal_mm(objectives: BenchmarkDefinition) -> float:
        boxes = [
            objectives.objectives.goal_zone_mm,
            *objectives.objectives.forbid_zones,
            objectives.objectives.build_zone_mm,
        ]
        min_x = min(box.min_mm[0] for box in boxes)
        min_y = min(box.min_mm[1] for box in boxes)
        min_z = min(box.min_mm[2] for box in boxes)
        max_x = max(box.max_mm[0] for box in boxes)
        max_y = max(box.max_mm[1] for box in boxes)
        max_z = max(box.max_mm[2] for box in boxes)
        dx = max_x - min_x
        dy = max_y - min_y
        dz = max_z - min_z
        return math.sqrt(dx * dx + dy * dy + dz * dz)


class GenesisSimulationBuilder(SimulationBuilderBase):
    """Orchestrates the conversion of build123d assemblies to Genesis scenes."""

    def build_from_assembly(
        self,
        assembly: Compound,
        objectives: BenchmarkDefinition | None = None,
        payload_parts: list["PayloadPart"] | None = None,
        smoke_test_mode: bool = False,
    ) -> Path:
        """Converts an assembly of parts into a Genesis scene descriptor (JSON)."""
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        scene_data = {"entities": []}

        # 1. Add zones from objectives
        if objectives:
            # Add Goal Zone
            gz = objectives.objectives.goal_zone_mm
            gz_pos = [(gz.min_mm[i] + gz.max_mm[i]) / 2 for i in range(3)]
            gz_size = [(gz.max_mm[i] - gz.min_mm[i]) / 2 for i in range(3)]
            scene_data["entities"].append(
                {
                    "name": "zone_goal",
                    "type": "box",
                    "pos_mm": gz_pos,
                    "size_mm": gz_size,
                    "is_zone": True,
                    "zone_type": ZoneType.GOAL,
                }
            )

            # Add Forbid Zones
            for i, fz in enumerate(objectives.objectives.forbid_zones):
                fz_pos = [(fz.min_mm[j] + fz.max_mm[j]) / 2 for j in range(3)]
                fz_size = [(fz.max_mm[j] - fz.min_mm[j]) / 2 for j in range(3)]
                scene_data["entities"].append(
                    {
                        "name": f"zone_forbid_{i}_{fz.name}",
                        "type": "box",
                        "pos_mm": fz_pos,
                        "size_mm": fz_size,
                        "is_zone": True,
                        "zone_type": ZoneType.FORBID,
                    }
                )

            bz = objectives.objectives.build_zone_mm
            bz_pos = [(bz.min_mm[i] + bz.max_mm[i]) / 2 for i in range(3)]
            bz_size = [(bz.max_mm[i] - bz.min_mm[i]) / 2 for i in range(3)]
            scene_data["entities"].append(
                {
                    "name": "zone_build",
                    "type": "box",
                    "pos_mm": bz_pos,
                    "size_mm": bz_size,
                    "is_zone": True,
                    "zone_type": ZoneType.BUILD,
                }
            )

        # 2. Add parts from assembly
        parts_data = CommonAssemblyTraverser.traverse(assembly)

        # Load manufacturing config for material coloring and cost lookup
        from worker_heavy.workbenches.config import load_config, load_merged_config

        custom_cfg_path = self.output_dir / "manufacturing_config.yaml"
        if custom_cfg_path.exists():
            load_merged_config(custom_cfg_path)
        else:
            load_config()

        for data in parts_data:
            mesh_path_base = self.assets_dir / data.label

            # Use coarser mesh for smoke tests to speed up Genesis voxelization
            tolerance = 1.0 if smoke_test_mode else 0.1
            self.processor.process_geometry(
                data.part,
                mesh_path_base,
                decompose=False,
                tolerance=tolerance,
                angular_tolerance=tolerance,
            )

            entity_info = {
                "name": data.label,
                "pos_mm": data.pos_mm,
                "euler_deg": data.euler_deg,
                "material_id": data.material_id,
                "is_fixed": data.is_fixed,
                "joint": {
                    "type": data.joint_type,
                    "axis": data.joint_axis,
                    "range": data.joint_range,
                }
                if data.joint_type
                else None,
            }

            entity_info["type"] = "mesh"
            entity_info["file"] = str(
                mesh_path_base.with_suffix(".obj").relative_to(self.assets_dir.parent)
            )

            scene_data["entities"].append(entity_info)

        scene_path = self.output_dir / "scene.json"
        with scene_path.open("w") as f:
            json.dump(scene_data, f, indent=2)

        return scene_path
