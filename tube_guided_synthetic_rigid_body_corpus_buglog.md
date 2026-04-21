# Tube-Guided Synthetic Corpus Buglog

Temporary scratch log for the current geometry and rendering regressions in
`notebooks/tube_guided_synthetic_rigid_body_corpus.py` and the worker-heavy
simulation/render path.

## 1. Corridor box angles are wrong

- [x] stale / likely resolved

- Symptom: the CAD corridor looks bent/twisted in a way that does not match the
  intended route.

- Clarification: this is not just the x-z profile. The authored boxes that make
  up the tube are not staying straight relative to each other. Their local angle
  appears to be effectively doubled or otherwise over-rotated at span joins.

- Evidence:

  - The route waypoints themselves look plausible in top-down and profile views.
  - The render still shows a visibly corrupted chain of box segments.

- Likely cause:

  - The per-span frame/orientation logic is still wrong, even after transport
    smoothing and shorter spans.

- Current check:

  - `INT-281` locks down the build123d route scaffold with per-span frame,
    vertex-distance, and non-intersection assertions.
  - `INT-285` checks the actual trimesh export of representative box parts and
    verifies the exported mesh axes still match the intended route frame up to
    axis permutation.
  - `INT-286` checks that adjacent split sections remain contiguous in the
    build123d geometry at every tube break.
  - `INT-287` checks the same break continuity on the actual exported trimesh
    for the densest split segment.
  - The fresh debug render no longer shows the visibly twisted corridor chain
    that motivated this note.

### Solution notes

- Investigate the span-local frame construction and verify whether the box
  orientation is accumulating roll or applying the tangent rotation twice.
- Compare the exported `euler_deg` values against the actual placed object
  axes in the scene export.
- If the frame transport is still unstable, replace it with a simpler
  per-segment frame that preserves continuity without reusing the previous
  tangent basis incorrectly.

## 2. Simulation render scale is misleading

- [x] resolved

- Symptom: the MuJoCo ground appears as a tiny patch near the bottom of the
  frame, while the corridor/model looks huge.

- Evidence:

  - The render makes the environment hard to inspect because size cues are not
    trustworthy.
  - The current video framing is not giving a useful sense of scale.

- Likely cause:

  - The scene is being shown with a camera/framing choice that hides the real
    size relationship, or the scene units are not being visually contextualized.

- Current check:

  - The fresh `main` camera now anchors to the fixed `zone_build` body instead
    of riding with the payload.
  - The integration check confirms `main` remains the active simulation camera
    while the MJCF now targets `zone_build`, which restores useful corridor and
    goal scale cues in the video.

### Solution notes

- Keep the render camera anchored on a fixed scene reference so the corridor and
  goal remain readable while the payload moves through the route.
- Confirm whether the worker-side scene is still using a fallback free camera
  or a track-com camera that is too close.
- If needed, render an overlay or reference object that makes the unit scale
  obvious without relying on the ground patch.

HUMAN NOTE: I've added a point cloud rendering and export endpoint on worker-renderer. What this means is that you can check the scale/position of objects vs expected.

## 3. Payload/objective visibility is poor

- [x] resolved

- Symptom: the payload and objective elements are not clearly visible in the
  simulation video.

- Evidence:

  - The video mostly shows corridor geometry.
  - The payload can look static or absent, and the objective context is easy to
    miss.

- Likely cause:

  - The worker-side render camera is not yet giving a clean tracking view of the
    payload and objective zones.
  - The simulation output should probably surface the exact tracked body and
    objective overlay more explicitly.

- Current check:

  - The fresh `main` camera now tracks the fixed `zone_build` reference, so the
    corridor and goal zone remain visible instead of the camera riding with the
    payload.
  - The notebook run now retains timestamped render evidence under
    `logs/tube_guided_synthetic_rigid_body_corpus/runs/run_<timestamp>/` and
    the simulation summary surfaces the resolved camera name and tracked body
    names for easier inspection.

### Solution notes

- Ensure the simulation video uses the worker-heavy video-producing path that
  tracks the payload body and preserves the objective context.
- Add or verify a camera that frames the payload, corridor, and goal zone in
  the same shot.
- If the payload is still hard to see, log or expose the tracked body name and
  the camera name in the render summary so the video is easier to interpret.

## 4. Main-app geometry convention mismatch breaks point-cloud placement and camera placement

- [ ] unresolved

- Symptom: the new `worker-renderer` point-cloud debug path can produce sampled
  points that do not match the staged part placement for the synthetic corpus
  bundle, and the computed camera orbit can land inside corridor geometry.

- Evidence:

  - The parquet-backed `sampled_points.parquet` artifact is real and the render
    path is not blank anymore, so this is not a transport-only issue.
  - The weaker `scene.bounds_min_mm` / `scene.bounds_max_mm` check is not a
    reliable contract here because live sampled points can fall below `z=0`
    even when the render is otherwise plausible.
  - The stronger `point in any part bbox` assertion in `INT-289` fails on the
    live render path, which means the sampled points are not lining up with the
    authored component geometry the way they should.
  - The companion camera-placement check in `INT-290` is intended to fail when
    the camera origin is occluded by a corridor part, which matches the blue-
    screen symptom we have been seeing.
  - Both failures occur after the workspace is staged and exported, which means
    the synthetic authoring pipeline is producing input that looks internally
    consistent before the renderer boundary.
  - This should be treated as a bug in the main-app geometry convention or the
    worker-renderer consumption of it, not as a synthetic data pipeline defect.

- Likely cause:

  - This looks like a bug in the main-app geometry convention or the
    worker-renderer consuming it, not in the synthetic data pipeline itself.
  - One plausible source is mesh recentering or origin handling during export:
    `MeshProcessor.process_geometry()` recenters exported meshes on their
    centroid before the scene pose is reapplied, which may not match the part
    bbox contract the preview scene assumes.
  - Another plausible source is that worker-renderer is sampling a transformed
    mesh representation whose origin/pose no longer matches the main-app
    placement convention used when the preview scene computes part bboxes.
  - The camera occlusion symptom suggests the camera placement logic may be
    using the same broken convention, so the view can be blocked even when the
    scene should be visible.

- Current check:

  - `INT-289` now asserts on the actual sampled point cloud positions via
    parquet and keeps the bbox union check because that is the right placement
    signal.
  - `INT-290` recomputes the camera orbit and fails if the camera point is
    inside any corridor part bbox.
  - The test currently fails on that assertion, so the mismatch is reproducible
    and not just a heuristic render artifact.

### Solution notes

- Inspect the full geometry convention at the main app / renderer boundary and
  make sure the same origin is used for:
  - preview scene export,
  - mesh recentering or convex-hull fallback,
  - point-cloud sampling, and
  - bounding-box assertions.
- Verify the camera placement code uses the same convention as the part bbox
  export, otherwise the camera can end up occluded even when the route looks
  valid in the synthetic authoring layer.
- If the centroid recentering is intentional for physics, confirm that the
  preview scene bboxes are derived from the same recentered geometry rather than
  the authored part pose.
- If the renderer is sampling the wrong transform stack, fix it at the source
  instead of weakening the test. The failure should remain fail-closed.

## Notes

- The notebook now writes run-scoped render evidence under
  `logs/tube_guided_synthetic_rigid_body_corpus/runs/run_<timestamp>/`.
- The remaining render evidence is easier to inspect because the simulation
  summary now includes camera provenance and tracked body names.
- Remove this file once it is no longer needed for debugging history.
