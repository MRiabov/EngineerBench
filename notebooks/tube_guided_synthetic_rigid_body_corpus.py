"""Compatibility wrapper for the synthetic corpus generator.

The implementation now lives under
`dataset.synthetic.tube_guided_synthetic_rigid_body_corpus`.
"""

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
    summary = main()
    import json

    print(json.dumps(summary, indent=2))
