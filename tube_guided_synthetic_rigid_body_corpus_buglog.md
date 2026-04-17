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

- [ ] still valid

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

  - The fresh `main` camera does track the payload body, but the shipped framing
    still makes the payload and goal zone hard to read.
  - A debug camera aimed at the corridor center makes the payload and goal zone
    visible together, so the issue is the default view selection rather than
    absent scene content.

### Solution notes

- Ensure the simulation video uses the worker-heavy video-producing path that
  tracks the payload body and preserves the objective context.
- Add or verify a camera that frames the payload, corridor, and goal zone in
  the same shot.
- If the payload is still hard to see, log or expose the tracked body name and
  the camera name in the render summary so the video is easier to interpret.

## Notes

- Fresh pipeline run: `main()` now fails later in bundle staging because the
  scratch coder workspace it constructs is missing `benchmark_definition.yaml`
  for the simulation-video preview step.
- The OOB failures are still happening on the payload body and not just at
  startup.
- The retry path is still failing, so this log is for diagnosis, not acceptance.
- Remove this file once the geometry and render issues are resolved.
