import mujoco
from build123d import Box, Compound

from shared.models.schemas import PartMetadata
from worker_heavy.simulation.builder import MuJoCoSimulationBuilder


def test_weld_constraint_generation(tmp_path):
    """
    Test that 'constraint="weld:target"' on a part generates a weld in the MJCF.
    This verifies the current behavior (manual parsing in builder) and future behavior (unified parsing).
    """
    # Create two parts
    part1 = Box(0.1, 0.1, 0.1)
    part1.label = "part_1"
    part1.metadata = PartMetadata(material_id="aluminum_6061")
    # Add the weld constraint
    part1.constraint = "weld:part_2"

    part2 = Box(0.1, 0.1, 0.1).translate((0.2, 0, 0))
    part2.label = "part_2"
    part2.metadata = PartMetadata(material_id="aluminum_6061")

    assembly = Compound(children=[part1, part2])

    builder = MuJoCoSimulationBuilder(tmp_path)
    scene_path = builder.build_from_assembly(assembly)

    assert scene_path.exists()

    # Read the generated XML
    xml_content = scene_path.read_text()

    # Check for <equality> and <weld>
    # The format is roughly:
    # <equality>
    #   <weld body1="part_1" body2="part_2" />
    # </equality>

    assert "<equality>" in xml_content
    # The attributes might be in any order, so check for substrings
    assert "weld" in xml_content
    assert 'body1="part_1"' in xml_content
    assert 'body2="part_2"' in xml_content

    # Also verify with MuJoCo loader to ensure valid XML
    model = mujoco.MjModel.from_xml_path(str(scene_path))
    assert model is not None
    # Check that we have 1 equality constraint
    assert model.neq == 1
    # Check the names of bodies involved in the constraint if possible,
    # but model.eq_obj1id and eq_obj2id store body IDs.

    # Get body IDs
    id1 = model.body("part_1").id
    id2 = model.body("part_2").id

    # Check that the equality constraint connects these bodies
    # eq_obj1id is an array of body IDs for the first object in the constraint
    assert model.eq_obj1id[0] == id1
    assert model.eq_obj2id[0] == id2
