# Tube-Guided Synthetic Corpus Buglog

Temporary scratch log for the current geometry and rendering regressions in
`notebooks/tube_guided_synthetic_rigid_body_corpus.py` and the worker-heavy
simulation/render path.

## 1. Corridor box angles are wrong

- [ ]

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

### Solution notes

- Investigate the span-local frame construction and verify whether the box
  orientation is accumulating roll or applying the tangent rotation twice.
- Compare the exported `euler_deg` values against the actual placed object
  axes in the scene export.
- If the frame transport is still unstable, replace it with a simpler
  per-segment frame that preserves continuity without reusing the previous
  tangent basis incorrectly.

## 2. Simulation render scale is misleading

- [ ]

- Symptom: the MuJoCo ground appears as a tiny patch near the bottom of the
  frame, while the corridor/model looks huge.
- Evidence:
  - The render makes the environment hard to inspect because size cues are not
    trustworthy.
  - The current video framing is not giving a useful sense of scale.
- Likely cause:
  - The scene is being shown with a camera/framing choice that hides the real
    size relationship, or the scene units are not being visually contextualized.

### Solution notes

- Make the render camera explicitly track the payload and show enough context to
  read ground, corridor, and objective scale together.
- Confirm whether the worker-side scene is still using a fallback free camera
  or a track-com camera that is too close.
- If needed, render an overlay or reference object that makes the unit scale
  obvious without relying on the ground patch.

## 3. Payload/objective visibility is poor

- [ ]

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

### Solution notes

- Ensure the simulation video uses the worker-heavy video-producing path that
  tracks the payload body and preserves the objective context.
- Add or verify a camera that frames the payload, corridor, and goal zone in
  the same shot.
- If the payload is still hard to see, log or expose the tracked body name and
  the camera name in the render summary so the video is easier to interpret.

## Notes

- The OOB failures are still happening on the payload body and not just at
  startup.
- The retry path is still failing, so this log is for diagnosis, not acceptance.
- Remove this file once the geometry and render issues are resolved.
