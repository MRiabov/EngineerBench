import sys
from pathlib import Path

from build123d import Align, Box, BuildPart, Compound, Location

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from scene_spec import SCENE

from shared.models.schemas import CompoundMetadata, PartMetadata


def _make_part(spec: dict[str, object]):
    size = spec["size"]
    center = spec["center"]
    label = str(spec["label"])
    material_id = str(spec["material_id"])
    fixed = bool(spec["fixed"])
    orientation_deg = float(spec.get("orientation_deg", 0.0))

    with BuildPart() as part:
        Box(*size, align=(Align.CENTER, Align.CENTER, Align.MIN))
    built = part.part.move(Location(center, (0.0, 0.0, orientation_deg)))
    built.label = label
    built.metadata = PartMetadata(material_id=material_id, is_fixed=fixed)
    return built


def build() -> Compound:
    assembly = Compound(
        label="paper_compact_transfer_benchmark",
        children=[_make_part(spec) for spec in SCENE.values()],
    )
    assembly.metadata = CompoundMetadata(is_fixed=False)
    return assembly
