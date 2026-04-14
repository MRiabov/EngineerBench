from __future__ import annotations

import contextlib
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog
import trimesh
from build123d import (
    Align,
    Box,
    Compound,
    Cylinder,
    Location,
    Solid,
    Sphere,
    export_stl,
)
from pydantic import BaseModel, ConfigDict, Field

from shared.enums import ZoneType

logger = structlog.get_logger(__name__)

MOVED_OBJECT_SCENE_PREFIX = "benchmark_moved_object__"


def normalize_preview_label(label: Any) -> str:
    """Return a file-safe preview label stem without adding fallback numbering."""
    text = "" if label is None else str(label).strip()
    if not text:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return cleaned


def moved_object_scene_name(label: str) -> str:
    """Return a namespaced scene identifier for the benchmark payload."""
    clean_label = str(label).strip()
    if not clean_label:
        raise ValueError("payload label must be non-empty")
    return f"{MOVED_OBJECT_SCENE_PREFIX}{clean_label}"


def is_moved_object_scene_name(name: str) -> bool:
    """Return True when a scene name belongs to the benchmark payload."""
    return str(name).startswith(MOVED_OBJECT_SCENE_PREFIX)


class PreviewEntity(BaseModel):
    """Renderable body or zone used by the build123d preview renderer."""

    model_config = ConfigDict(extra="forbid")

    label: str
    semantic_label: str
    instance_id: str
    instance_name: str
    object_type: str
    object_id: int
    pos: tuple[float, float, float]
    euler: tuple[float, float, float]
    mesh_paths: list[str] = Field(default_factory=list)
    box_size: tuple[float, float, float] | None = None
    material_id: str | None = None
    body_name: str | None = None
    geom_name: str | None = None
    zone_type: ZoneType | None = None
    color_rgba: tuple[float, float, float, float] | None = None
    segmentation_color_rgb: tuple[int, int, int] | None = None
    include_in_segmentation: bool = True


class PreviewScene(BaseModel):
    """Strict render-scene bundle used for RGB/depth/segmentation preview."""

    model_config = ConfigDict(extra="forbid")

    component_label: str | None = None
    entities: list[PreviewEntity] = Field(default_factory=list)
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    center: tuple[float, float, float]
    diagonal: float


class MaterializedMovedObject(BaseModel):
    """Typed record for the benchmark payload geometry and scene naming."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    label: str
    scene_name: str
    geometry: Solid | Compound | Any
    start_position: tuple[float, float, float]
    material_id: str

    def start_geometry(self) -> Solid | Compound | Any:
        """Return the payload geometry moved to its declared start pose."""
        return self.geometry.move(Location(self.start_position))


class AssemblyPartData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    label: str
    part: Solid | Compound | Any
    pos: list[float]
    euler: list[float]
    is_fixed: bool = False
    joint_type: str | None = None
    joint_axis: list[float] | None = None
    joint_range: list[float] | None = None
    material_id: str | None = None
    is_zone: bool = False
    zone_type: ZoneType | None = None
    zone_size: list[float] | None = None
    constraint: str | None = None
    weld_target: str | None = None


def build_moved_object_geometry(moved: Any):
    """Build the authored payload geometry from its declared shape."""
    shape = str(getattr(moved, "shape", "sphere")).strip().lower()
    radius_range = getattr(getattr(moved, "static_randomization", None), "radius", None)
    radius = float(max(radius_range)) if radius_range else None

    if shape == "sphere":
        sphere_radius = radius if radius is not None else 0.01
        return Sphere(
            sphere_radius,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    if shape in {"cube", "box"}:
        edge = (radius * 2.0) if radius is not None else 1.0
        return Box(
            edge,
            edge,
            edge,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    if shape == "cylinder":
        cylinder_radius = radius if radius is not None else 0.5
        return Cylinder(
            radius=cylinder_radius,
            height=(cylinder_radius * 2.0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )

    raise ValueError(
        f"Unsupported payload.shape '{shape}'. Expected sphere, cube, box, or cylinder."
    )


def materialize_moved_object(moved: Any) -> MaterializedMovedObject:
    """Materialize the benchmark payload geometry and its scene name."""
    label = str(getattr(moved, "label", "")).strip()
    if not label:
        raise ValueError("payload label must be non-empty")

    geometry = build_moved_object_geometry(moved)
    with contextlib.suppress(Exception):
        geometry.label = label

    start_position = tuple(float(value) for value in getattr(moved, "start_position"))
    material_id = str(getattr(moved, "material_id"))
    return MaterializedMovedObject(
        label=label,
        scene_name=moved_object_scene_name(label),
        geometry=geometry,
        start_position=start_position,
        material_id=material_id,
    )


def build_moved_object_start_geometry(moved: Any):
    """Materialize the benchmark payload at its declared startup pose."""
    return materialize_moved_object(moved).start_geometry()


class CommonAssemblyTraverser:
    """Unifies assembly traversal and metadata resolution for preview scene export."""

    @staticmethod
    def _resolve_material_id(metadata: Any) -> str | None:
        material_id = getattr(metadata, "material_id", None)
        return material_id or None

    @staticmethod
    def _is_structural_compound(node: Any) -> bool:
        from shared.models.schemas import CompoundMetadata, PartMetadata

        if not isinstance(node, Compound):
            return False

        children = list(getattr(node, "children", []) or [])
        if not children:
            return False

        metadata = getattr(node, "metadata", None)
        if isinstance(metadata, PartMetadata):
            return False
        if isinstance(metadata, CompoundMetadata):
            return True
        if isinstance(metadata, dict):
            try:
                PartMetadata(**metadata)
            except Exception:
                try:
                    return isinstance(CompoundMetadata(**metadata), CompoundMetadata)
                except Exception:
                    return True
            return False
        return True

    @staticmethod
    def traverse(
        assembly: Compound,
        *,
        allow_unnamed_labels: bool = False,
        unnamed_label_factory: Callable[[], str] | None = None,
    ) -> list[AssemblyPartData]:
        parts_data: list[AssemblyPartData] = []

        def _visit(
            node: Any, node_index: int, parent_location: Any | None = None
        ) -> None:
            if CommonAssemblyTraverser._is_structural_compound(node):
                composed_location = CommonAssemblyTraverser._compose_location(
                    node, parent_location
                )
                for child_index, child in enumerate(
                    list(getattr(node, "children", []) or [])
                ):
                    _visit(child, child_index, composed_location)
                return

            raw_label = getattr(node, "label", None)
            label = normalize_preview_label(raw_label)
            if not label:
                if not allow_unnamed_labels:
                    logger.error(
                        "top_level_build123d_label_missing",
                        part_index=node_index,
                        raw_label=raw_label,
                        part_type=type(node).__name__,
                    )
                    raise ValueError(
                        "Top-level build123d objects must have non-empty labels. "
                        f"Offending part index: {node_index}."
                    )
                if unnamed_label_factory is None:
                    label = f"unnamed_{node_index + 1}"
                else:
                    label = unnamed_label_factory()

            pos, euler = CommonAssemblyTraverser._resolve_location(
                node, parent_location
            )
            meta = CommonAssemblyTraverser._resolve_part_metadata(node)
            zone_info = CommonAssemblyTraverser._detect_zone(node, label)

            constraint = getattr(node, "constraint", None)
            weld_target = None
            if constraint and constraint.startswith("weld:"):
                weld_target = constraint.split(":")[1]

            parts_data.append(
                AssemblyPartData(
                    label=label,
                    part=node,
                    pos=pos,
                    euler=euler,
                    is_fixed=meta["is_fixed"],
                    material_id=meta["material_id"],
                    joint_type=meta["joint_type"],
                    joint_axis=meta["joint_axis"],
                    joint_range=meta["joint_range"],
                    is_zone=zone_info["is_zone"],
                    zone_type=zone_info["type"],
                    zone_size=zone_info["size"],
                    constraint=constraint,
                    weld_target=weld_target,
                )
            )

        _visit(assembly, 0)
        return parts_data

    @staticmethod
    def _compose_location(child: Any, parent_location: Any | None = None) -> Any:
        location = child.location
        if parent_location is not None:
            location = parent_location * location
        return location

    @staticmethod
    def _resolve_location(
        child: Any, parent_location: Any | None = None
    ) -> tuple[list[float], list[float]]:
        location = CommonAssemblyTraverser._compose_location(child, parent_location)
        pos = [
            location.position.X,
            location.position.Y,
            location.position.Z,
        ]
        euler = [
            location.orientation.X,
            location.orientation.Y,
            location.orientation.Z,
        ]
        return pos, euler

    @staticmethod
    def _resolve_part_metadata(child: Any) -> dict[str, Any]:
        from shared.models.schemas import CompoundMetadata, PartMetadata

        metadata = getattr(child, "metadata", None)
        if metadata is None:
            label = getattr(child, "label", "")
            if label.startswith("zone_"):
                return {
                    "is_fixed": True,
                    "material_id": None,
                    "joint_type": None,
                    "joint_axis": None,
                    "joint_range": None,
                }

            raise ValueError(
                f"Part '{label or 'unknown'}' is missing required metadata. "
                "Every part must have a .metadata attribute "
                "(PartMetadata or CompoundMetadata)."
            )

        if isinstance(metadata, dict):
            try:
                metadata = PartMetadata(**metadata)
            except Exception:
                try:
                    metadata = CompoundMetadata(**metadata)
                except Exception as e:
                    label_str = getattr(child, "label", "unknown")
                    raise ValueError(
                        f"Invalid metadata for part '{label_str}': {e}"
                    ) from e

        joint_type, joint_axis, joint_range = None, None, None
        if metadata.joint:
            joint_type = metadata.joint.type
            joint_axis = list(metadata.joint.axis)
            joint_range = list(metadata.joint.range) if metadata.joint.range else None

        return {
            "is_fixed": metadata.is_fixed,
            "material_id": CommonAssemblyTraverser._resolve_material_id(metadata),
            "joint_type": joint_type,
            "joint_axis": joint_axis,
            "joint_range": joint_range,
        }

    @staticmethod
    def _detect_zone(child: Any, label: str) -> dict[str, Any]:
        is_zone = False
        zone_type: ZoneType | None = None
        zone_size = None
        if label.startswith("zone_"):
            is_zone = True
            if "goal" in label:
                zone_type = ZoneType.GOAL
            elif "build" in label:
                zone_type = ZoneType.BUILD
            else:
                zone_type = ZoneType.FORBID
            bb = child.bounding_box()
            zone_size = [bb.size.X / 2, bb.size.Y / 2, bb.size.Z / 2]
        return {"is_zone": is_zone, "type": zone_type, "size": zone_size}


class MeshProcessor:
    """Converts build123d geometry into preview-ready mesh files."""

    def process_geometry(
        self,
        part: Solid | Compound,
        filepath: Path,
        decompose: bool = True,
        use_vhacd: bool = False,
        tolerance: float = 0.1,
        angular_tolerance: float = 0.1,
    ) -> list[Path]:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        temp_stl = filepath.with_suffix(".tmp.stl")
        export_stl(
            part, temp_stl, tolerance=tolerance, angular_tolerance=angular_tolerance
        )

        output_paths: list[Path] = []
        try:
            mesh = trimesh.load(temp_stl)
            if isinstance(mesh, trimesh.Scene):
                mesh = mesh.dump(concatenate=True)

            mesh = self._recenter_mesh(mesh)
            mesh = self._validate_watertight(mesh, filepath.name)

            if decompose:
                if use_vhacd:
                    try:
                        decomposed = trimesh.decomposition.convex_decomposition(mesh)
                        if isinstance(decomposed, list) and len(decomposed) > 1:
                            for i, dm in enumerate(decomposed):
                                obj_sub = filepath.with_name(f"{filepath.stem}_{i}.obj")
                                glb_sub = filepath.with_name(f"{filepath.stem}_{i}.glb")
                                dm.export(obj_sub, file_type="obj")
                                dm.export(glb_sub, file_type="glb")
                                output_paths.extend([obj_sub, glb_sub])
                            return output_paths
                    except Exception:
                        pass

                mesh = self.compute_convex_hull(mesh)

            obj_path = filepath.with_suffix(".obj")
            glb_path = filepath.with_suffix(".glb")

            mesh.export(obj_path, file_type="obj")
            try:
                self.export_topology_glb(part, glb_path)
            except Exception as e:
                logger.warning("topology_export_failed", error=str(e))
                mesh.export(glb_path, file_type="glb")

            output_paths.extend([obj_path, glb_path])
        finally:
            if temp_stl.exists():
                temp_stl.unlink()

        return output_paths

    def export_topology_glb(self, part: Solid | Compound, filepath: Path):
        scene = trimesh.Scene()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            faces = part.faces()
            for i, face in enumerate(faces):
                face_path = tmp_path / f"face_{i}.stl"
                export_stl(face, face_path)
                try:
                    face_mesh = trimesh.load(face_path)
                    if isinstance(face_mesh, trimesh.Scene):
                        face_mesh = face_mesh.dump(concatenate=True)
                    scene.add_geometry(
                        face_mesh,
                        node_name=f"face_{i}",
                        geom_name=f"face_{i}_geom",
                    )
                except Exception as e:
                    logger.warning("failed_to_export_face", face_index=i, error=str(e))
        scene.export(filepath, file_type="glb")

    def _recenter_mesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        centroid = mesh.centroid
        mesh.apply_translation(-centroid)
        return mesh

    def _validate_watertight(self, mesh: trimesh.Trimesh, name: str) -> trimesh.Trimesh:
        if mesh.is_watertight:
            return mesh
        try:
            mesh.fill_holes()
            mesh.fix_normals()
            mesh.fix_inversion()
        except Exception:
            pass
        if mesh.is_watertight:
            return mesh
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
        return mesh.convex_hull


__all__ = [
    "AssemblyPartData",
    "CommonAssemblyTraverser",
    "MaterializedMovedObject",
    "MeshProcessor",
    "MOVED_OBJECT_SCENE_PREFIX",
    "PreviewEntity",
    "PreviewScene",
    "build_moved_object_geometry",
    "build_moved_object_start_geometry",
    "is_moved_object_scene_name",
    "materialize_moved_object",
    "moved_object_scene_name",
    "normalize_preview_label",
]
