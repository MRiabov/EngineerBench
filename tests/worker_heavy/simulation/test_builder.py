import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import pytest
from build123d import Box, Compound

from shared.models.schemas import CompoundMetadata, JointMetadata, PartMetadata
from worker_heavy.simulation.builder import (
    CommonAssemblyTraverser,
    MeshProcessor,
    MuJoCoSimulationBuilder,
    SceneCompiler,
)


def test_mesh_processor_dual_export(tmp_path):
    """Test that mesh processor exports both OBJ and GLB format."""
    processor = MeshProcessor()
    box = Box(1, 1, 1)
    input_path = tmp_path / "test_box.stl"

    result_paths = processor.process_geometry(box, input_path)

    assert len(result_paths) == 2
    suffixes = {p.suffix for p in result_paths}
    assert ".obj" in suffixes
    assert ".glb" in suffixes
    for p in result_paths:
        assert p.exists()
        assert p.stat().st_size > 0


def test_scene_compiler(tmp_path):
    compiler = SceneCompiler()
    xml_path = tmp_path / "scene.xml"

    compiler.add_mesh_asset("box", "box.stl")
    compiler.add_body("box_body", mesh_names=["box"], pos=[0, 0, 1])
    compiler.save(xml_path)

    assert xml_path.exists()
    content = xml_path.read_text()
    assert "<mujoco" in content
    assert 'mesh="box"' in content


def test_simulation_builder(tmp_path):
    # Create a small assembly
    box1 = Box(0.1, 0.1, 0.1)
    box1.label = "part_1"
    box1.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=False,
        joint=JointMetadata(type="hinge", axis=(0, 0, 1), range=(-90, 90)),
    )

    # zone_goal
    box2 = Box(0.2, 0.2, 0.2)
    box2.label = "zone_goal"

    assembly = Compound(children=[box1, box2])

    builder = MuJoCoSimulationBuilder(tmp_path)
    scene_path = builder.build_from_assembly(assembly)

    assert scene_path.exists()
    # Check MJCF for joint mapping
    tree = ET.parse(scene_path)
    root = tree.getroot()
    joint = root.find(".//body[@name='part_1']/joint")
    assert joint is not None
    assert joint.get("type") == "hinge"
    # SceneCompiler uses " ".join(map(str, joint_axis)) which results in floats
    assert joint.get("axis") == "0.0 0.0 1.0"
    assert joint.get("range") == "-90.0 90.0"

    # Try loading with MuJoCo
    model = mujoco.MjModel.from_xml_path(str(scene_path))
    assert model is not None
    assert model.nmesh == 1
    assert model.nsite == 1
    assert np.allclose(model.site_size[0], [0.1, 0.1, 0.1])


def test_compound_metadata_resolution():
    box = Box(0.1, 0.1, 0.1)
    box.label = "compound_part"
    box.metadata = CompoundMetadata(
        fixed=False, joint=JointMetadata(type="slide", axis=(1, 0, 0))
    )

    parts_data = CommonAssemblyTraverser.traverse(box)
    assert len(parts_data) == 1
    data = parts_data[0]
    assert data.is_fixed is False
    assert data.joint_type == "slide"
    assert data.joint_axis == [1.0, 0.0, 0.0]


def test_vhacd_decomposition(tmp_path):
    b1 = Box(1, 0.2, 0.2)
    b2 = Box(0.2, 1, 0.2).translate((-0.4, 0.4, 0))
    part = b1 + b2
    part.label = "concave_part"
    part.metadata = PartMetadata(material_id="steel")

    assembly = Compound(children=[part])

    builder = MuJoCoSimulationBuilder(tmp_path, use_vhacd=True)
    scene_path = builder.build_from_assembly(assembly)

    assert scene_path.exists()
    assets_dir = tmp_path / "assets"
    obj_files = list(assets_dir.glob("concave_part*.obj"))
    assert len(obj_files) >= 1

    model = mujoco.MjModel.from_xml_path(str(scene_path))
    assert model.nmesh >= 1


def test_simulation_builder_missing_metadata_fails(tmp_path):
    box1 = Box(0.1, 0.1, 0.1)
    box1.label = "bad_part"

    assembly = Compound(children=[box1])
    builder = MuJoCoSimulationBuilder(tmp_path)

    with pytest.raises(ValueError) as excinfo:
        builder.build_from_assembly(assembly)

    assert "missing required metadata" in str(excinfo.value)
    assert "bad_part" in str(excinfo.value)
