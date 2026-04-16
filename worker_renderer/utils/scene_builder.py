from __future__ import annotations

from shared.simulation.scene_builder import (
    PAYLOAD_SCENE_PREFIX,
    AssemblyPartData,
    CommonAssemblyTraverser,
    MaterializedPayload,
    MeshProcessor,
    PreviewEntity,
    PreviewScene,
    build_payload_geometry,
    build_payload_start_geometry,
    is_payload_scene_name,
    materialize_payload,
    normalize_preview_label,
    payload_scene_name,
)

__all__ = [
    "AssemblyPartData",
    "CommonAssemblyTraverser",
    "MaterializedPayload",
    "MeshProcessor",
    "PAYLOAD_SCENE_PREFIX",
    "PreviewEntity",
    "PreviewScene",
    "build_payload_geometry",
    "build_payload_start_geometry",
    "is_payload_scene_name",
    "materialize_payload",
    "payload_scene_name",
    "normalize_preview_label",
]

MOVED_OBJECT_SCENE_PREFIX = PAYLOAD_SCENE_PREFIX
MaterializedMovedObject = MaterializedPayload
build_moved_object_geometry = build_payload_geometry
build_moved_object_start_geometry = build_payload_start_geometry
is_moved_object_scene_name = is_payload_scene_name
materialize_moved_object = materialize_payload
moved_object_scene_name = payload_scene_name
