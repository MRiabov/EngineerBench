SCENE = {
    "base_plate": {
        "label": "base_plate",
        "material_id": "aluminum_6061",
        "is_fixed": True,
        "center": (0.0, 0.0, 0.0),
        "size": (1.60, 0.70, 0.04),
    },
    "support_tower": {
        "label": "support_tower",
        "material_id": "aluminum_6061",
        "is_fixed": True,
        "center": (-0.55, -0.05, 0.04),
        "size": (0.18, 0.18, 0.55),
    },
    "forbid_blocker": {
        "label": "forbid_blocker",
        "material_id": "silicone_rubber",
        "is_fixed": True,
        "center": (0.02, 0.02, 0.04),
        "size": (0.18, 0.12, 0.30),
    },
    "goal_tray": {
        "label": "goal_tray",
        "material_id": "hdpe",
        "is_fixed": True,
        "center": (0.65, 0.16, 0.04),
        "size": (0.34, 0.20, 0.08),
        "orientation_deg": 90.0,
    },
    "payload": {
        "label": "payload",
        "material_id": "hardwood",
        "is_fixed": False,
        "center": (-0.74, -0.16, 0.04),
        "size": (0.12, 0.08, 0.10),
        "orientation_deg": 90.0,
    },
}
