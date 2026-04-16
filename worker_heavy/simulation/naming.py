from __future__ import annotations

from shared.simulation.scene_builder import (
    PAYLOAD_SCENE_PREFIX,
    is_payload_scene_name,
    payload_scene_name,
)

__all__ = [
    "PAYLOAD_SCENE_PREFIX",
    "is_payload_scene_name",
    "payload_scene_name",
]

MOVED_OBJECT_SCENE_PREFIX = PAYLOAD_SCENE_PREFIX
is_moved_object_scene_name = is_payload_scene_name
moved_object_scene_name = payload_scene_name
