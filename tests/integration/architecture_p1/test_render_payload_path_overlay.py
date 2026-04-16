from __future__ import annotations

from pathlib import Path

from worker_renderer.utils.payload_path_overlay import resolve_payload_path_points

ROOT = Path(__file__).resolve().parents[3]


def test_resolve_payload_path_points_prefers_planner_motion_forecast(tmp_path: Path):
    workspace_root = tmp_path

    benchmark_definition = (
        ROOT
        / "dataset"
        / "data"
        / "seed"
        / "artifacts"
        / "engineer_coder"
        / "ec-002-low-friction-cube"
        / "benchmark_definition.yaml"
    ).read_text(encoding="utf-8")
    workspace_root.joinpath("benchmark_definition.yaml").write_text(
        benchmark_definition,
        encoding="utf-8",
    )

    assembly_definition = (
        ROOT
        / "shared"
        / "assets"
        / "template_repos"
        / "engineer"
        / "assembly_definition.yaml"
    ).read_text(encoding="utf-8")
    workspace_root.joinpath("assembly_definition.yaml").write_text(
        assembly_definition
        + """

motion_forecast:
  moving_part_names:
    - bridge_deck
  reference_frame: world
  sample_stride_s: 0.5
  anchors:
    - t_s: 0.0
      reference_point: build_zone_start
      pos_mm: [0.0, 0.0, 5.0]
      rot_deg: [0.0, 0.0, 0.0]
      position_tolerance_mm: [1.2, 1.2, 1.2]
      rotation_tolerance_deg: [0.1, 0.1, 5.0]
      build_zone_valid: true
    - t_s: 2.5
      reference_point: goal_zone_contact
      pos_mm: [12.0, 0.0, 2.0]
      rot_deg: [0.0, 0.0, 0.0]
      position_tolerance_mm: [1.2, 1.2, 1.2]
      rotation_tolerance_deg: [0.1, 0.1, 5.0]
      goal_zone_contact: true
""",
        encoding="utf-8",
    )

    points = resolve_payload_path_points(workspace_root)

    assert points == [(0.0, 0.0, 5.0), (12.0, 0.0, 2.0)]


def test_resolve_payload_path_points_does_not_invent_benchmark_line(
    tmp_path: Path,
):
    workspace_root = tmp_path
    benchmark_definition = (
        ROOT
        / "dataset"
        / "data"
        / "seed"
        / "artifacts"
        / "engineer_coder"
        / "ec-002-low-friction-cube"
        / "benchmark_definition.yaml"
    ).read_text(encoding="utf-8")
    workspace_root.joinpath("benchmark_definition.yaml").write_text(
        benchmark_definition,
        encoding="utf-8",
    )

    points = resolve_payload_path_points(workspace_root)

    assert points is None
