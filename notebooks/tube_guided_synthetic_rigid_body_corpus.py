"""Compatibility wrapper for the synthetic corpus generator.

The implementation now lives under
`dataset.synthetic.tube_guided_synthetic_rigid_body_corpus`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus import (
    ContactHit,
    PartSpec,
    RoutePoint,
    ScenarioConfig,
    SegmentSpan,
    default_route_points,
    main,
    synthesize,
)

__all__ = [
    "ContactHit",
    "PartSpec",
    "RoutePoint",
    "ScenarioConfig",
    "SegmentSpan",
    "default_route_points",
    "main",
    "synthesize",
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-simulation-video",
        action="store_true",
        help="Disable the default simulation-video render step.",
    )
    args = parser.parse_args()
    if args.no_simulation_video:
        os.environ["PROBLEMOLOGIST_TUBE_GUIDED_SYNTHETIC_DISABLE_RENDER"] = "1"

    summary = main()
    import json

    print(json.dumps(summary, indent=2))
