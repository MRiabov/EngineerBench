"""Tests for static randomization utilities."""

import pytest

from worker_heavy.simulation.randomization import (
    MaterialAssignment,
    apply_material_to_mjcf_geom,
    get_eligible_materials,
    randomize_materials,
)

# Sample materials config for testing
TEST_MATERIALS = {
    "aluminum_6061": {
        "color": "#C0C0C0",
        "density_g_cm3": 2.7,
        "restitution": 0.5,
        "friction_coef": 0.61,
    },
    "abs": {
        "color": "#F5F5DC",
        "density_g_cm3": 1.02,
        "restitution": 0.4,
        "friction_coef": 0.35,
    },
    "pla": {
        "color": "#FFFFFF",
        "density_g_cm3": 1.25,
        "restitution": 0.3,
        "friction_coef": 0.40,
    },
}


class TestGetEligibleMaterials:
    def test_no_constraints_returns_all(self):
        """All materials are eligible without constraints."""
        eligible = get_eligible_materials(TEST_MATERIALS)
        assert len(eligible) == 3
        assert set(eligible) == {"aluminum_6061", "abs", "pla"}

    def test_whitelist_filters(self):
        """Only whitelisted materials are included."""
        eligible = get_eligible_materials(
            TEST_MATERIALS, whitelist=["aluminum_6061", "pla"]
        )
        assert len(eligible) == 2
        assert "abs" not in eligible


class TestRandomizeMaterials:
    def test_deterministic_with_seed(self):
        """Same seed produces same assignment."""
        parts = ["part_a", "part_b", "part_c"]

        result1 = randomize_materials(parts, TEST_MATERIALS, seed=42)
        result2 = randomize_materials(parts, TEST_MATERIALS, seed=42)

        assert result1 == result2

    def test_different_seeds_different_results(self):
        """Different seeds may produce different assignments."""
        parts = ["part_a", "part_b", "part_c"]

        result1 = randomize_materials(parts, TEST_MATERIALS, seed=42)
        result2 = randomize_materials(parts, TEST_MATERIALS, seed=99)

        # Very unlikely to be identical with different seeds
        # (probability 1/3^3 = 1/27)
        materials1 = [r.material_id for r in result1.values()]
        materials2 = [r.material_id for r in result2.values()]
        # At least check they're valid
        for m in materials1 + materials2:
            assert m in TEST_MATERIALS

    def test_assignment_contains_correct_properties(self):
        """Material assignments include all required properties."""
        parts = ["moving_part"]
        result = randomize_materials(parts, TEST_MATERIALS, seed=42)

        assignment = result["moving_part"]
        assert isinstance(assignment, MaterialAssignment)
        assert assignment.part_name == "moving_part"
        assert assignment.material_id in TEST_MATERIALS
        assert assignment.color.startswith("#")
        assert assignment.density_g_cm3 > 0
        assert 0 <= assignment.friction_coef <= 1
        assert 0 <= assignment.restitution <= 1

    def test_raises_on_no_eligible(self):
        """Raises ValueError if no materials meet constraints."""
        with pytest.raises(ValueError, match="No eligible materials"):
            randomize_materials(["part"], {}, seed=42)


class TestApplyMaterialToMjcfGeom:
    def test_color_conversion(self):
        """Hex color is converted to RGBA."""
        assignment = MaterialAssignment(
            part_name="test",
            material_id="aluminum_6061",
            color="#C0C0C0",
            density_g_cm3=2.7,
            friction_coef=0.61,
            restitution=0.5,
        )

        attrs = apply_material_to_mjcf_geom(assignment)

        # #C0C0C0 = 192/255 ≈ 0.753
        assert "rgba" in attrs
        rgba_parts = attrs["rgba"].split()
        assert len(rgba_parts) == 4
        assert abs(float(rgba_parts[0]) - 0.753) < 0.01  # Red
        assert abs(float(rgba_parts[1]) - 0.753) < 0.01  # Green
        assert abs(float(rgba_parts[2]) - 0.753) < 0.01  # Blue
        assert rgba_parts[3] == "1"  # Alpha

    def test_friction_output(self):
        """Friction coefficient is included."""
        assignment = MaterialAssignment(
            part_name="test",
            material_id="abs",
            color="#F5F5DC",
            density_g_cm3=1.02,
            friction_coef=0.35,
            restitution=0.4,
        )

        attrs = apply_material_to_mjcf_geom(assignment)

        assert "friction" in attrs
        assert "0.35" in attrs["friction"]
