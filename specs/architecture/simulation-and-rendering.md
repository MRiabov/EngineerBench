# Simulation and Rendering

## Scope summary

- Primary focus: physics simulation contract, backend split, and rendering behavior.
- Defines constraints realism rules, allowed mechanisms/components, and CAD-joint-to-simulator mapping.
- Specifies simulation constants, backend assumptions, and validation expectations.
- Use this file for changes related to simulation semantics, constraints, or rendering logic.

## Dedicated render services

Rendering is split by artifact family:

1. explicit preview renders and preview-style image post-processing run in a dedicated headless `worker-renderer` container,
2. simulation-video rendering is a switchable contract between `worker-heavy` and `worker-renderer`,
3. selection snapshots, depth renders, segmentation renders, and preview-manifest generation remain in `worker-renderer`.

Static validation no longer produces preview artifacts by default; explicit preview requests use the same renderer worker boundary instead.

The physics backends do not own the controller-facing render process state for preview jobs. They supply scene state, camera policy, and render-capability metadata where needed; the renderer worker owns the graphics stack for preview.

The render worker is containerized in every environment, including development, so the graphics stack stays isolated from simulation and from the controller process. That is intentional even when the other workers are launched as bare FastAPI processes during local development: the renderer is the one worker that must not inherit host Wayland/X11 state or ambient EGL quirks.
The renderer worker is the only service that owns VTK, EGL, OpenGL, and related graphics backend dependencies.

Preview rendering is a blocking agent-facing operation, so the renderer hot path should prefer safe in-process fan-out for independent work that is easy to parallelize, especially per-view and per-modality work. It should also minimize repeated bundle reconstruction, temporary-file churn, and unnecessary I/O-bound byte copying or serialization inside the render loop.

### Headless backend selection

The renderer worker selects its VTK OpenGL window class explicitly rather than relying on whatever the host process happens to expose.

The runtime rules are:

1. `VTK_DEFAULT_OPENGL_WINDOW` is part of the renderer worker contract and is honored by the render bootstrap.
2. The active physics backend owns its own accepted GL backend list through `PROBLEMOLOGIST_PHYSICS_GL_BACKEND`; MuJoCo currently accepts EGL, while Genesis has a backend-specific list.
3. The current renderer deployment defaults to OSMesa for reliability in headless Linux environments, with EGL still available as an explicit opt-in backend for environments that support it.
4. `PROBLEMOLOGIST_RENDER_GL_BACKEND` selects the renderer backend, and the render bootstrap resolves that into the matching VTK window class.
5. The renderer worker does not depend on Xvfb as its normal launch path.
6. A native `Render()` segfault is a backend/runtime failure, not a valid render completion.

The practical consequence is that the renderer image must contain the required Mesa/VTK runtime pieces for the selected backend, and the machine or container must be checked against a real render probe rather than package presence alone.

## Genesis for simulation

While this platform has notable downsides for future use, we pick Genesis because it provides the simulation backend we need and is fast enough to work.

Operational benchmarking notes, runtime optimization attempts, and dated performance measurements for the simulation stack are tracked in the relevant migration docs under `specs/migrations/`.

### Runtime cost model

For architecture and optimization decisions, we treat simulation runtime cost as three separate layers:

1. Process-global cold cost.
   - Python child startup.
   - module import and runtime setup.
   - Genesis runtime initialization.
   - process-local compiler and backend warmup.
2. Scene-specific build cost.
   - scene creation,
   - mesh conversion,
   - geometry-specific build work,
   - collision and backend scene preparation,
   - object-family-specific compilation work when it occurs.
3. Actual simulation execution cost.
   - stepping the physics scene,
   - rendering or artifact creation if requested,
   - result extraction and validation logic.

This distinction is mandatory for future optimization work because different changes affect different layers.

- A persistent dedicated simulation child removes repeated process-global cold cost across requests on the same worker instance.
- A persistent child does not, by itself, remove scene-specific build cost for materially different scenes.
- Scene-specific cost reduction requires separate caching or reuse strategies such as compiled-scene caching, mesh caching, or geometry-hash caches.

The optimization log dated 2026-03-09 records the evidence for this split. In particular:

- the earlier init benchmark showed that literal `gs.init()` is not the dominant repeated cost by itself,
- the follow-up warm-process benchmark showed that different-scene-next cost is real, but still does not fully reset to the original cold-process cost for the primitive case,
- the minimal mesh case showed nearly identical warm-process cost for same-versus-different OBJ scenes in that experiment.
- the direct `simulate_subprocess(...)` benchmark on two distinct successful bundles, using distinct `session_id` values and both bundle orders, measured fresh-child totals of `125.8s` to `127.9s` and reused-child totals of `80.2s` to `80.9s`,
- the same direct benchmark measured second-request wall-clock time dropping from `31.4s` to `32.1s` in fresh-child mode down to `2.4s` to `2.5s` in reused-child mode, which is the strongest current evidence that the repeated cost is in process lifecycle and warm-runtime loss rather than same-session backend caching.

The architecture implication is explicit:

- we should not discuss "simulation startup cost" as if it were one number,
- we should separately measure and optimize process-global cold cost and scene-specific build cost,
- we should not reject the persistent-child design merely because different scenes still pay real rebuild cost.

### Persistent child runtime direction

The current optimization direction is now concrete enough to treat as an implementation plan rather than only a hypothesis.

The runtime direction is:

1. Keep `worker-heavy` single-flight.
2. Keep the process boundary between the FastAPI parent and the simulation runtime.
3. Replace one-fresh-child-per-request execution in `simulation_runner.py` with one persistent dedicated child executor per worker instance for `simulate` and `validate`.
4. Recreate that executor fail-closed after `BrokenProcessPool` or explicit shutdown.
5. Add explicit child-side cleanup functions that clear backend or session state without killing the warm process.

The benchmark evidence makes one point explicit:

- the implementation target is process reuse,
- not thread reuse,
- not repeated same-session backend reuse,
- and not a narrow micro-optimization around the literal `gs.init()` call.

The persistent-child refactor therefore has to preserve the existing behavior contracts while changing only the child lifecycle:

1. Public `/benchmark/*` request and response contracts stay unchanged.
2. `/ready` and heavy-admission semantics stay unchanged.
3. The current request fails closed if the child crashes.
4. The next request recreates a fresh child.
5. Child cleanup is explicit and observable rather than being an accidental side effect of process exit.

The detailed dated plan for this refactor is recorded in the relevant migration docs under `specs/migrations/major/`.

### Warm-child backend cache split

The persistent child keeps backend caches split by both session and backend type.

The cache rule is:

1. A session may hold a warm MuJoCo backend and a warm Genesis backend at the same time.
2. Explicit preview requests must not overwrite or alias the backend instance later used by `/benchmark/simulate`.
3. Backend cache lookup is therefore keyed by `(session_id, backend_type)`, not by `session_id` alone.
4. Session cleanup closes all cached backend instances for that session, not only the most recent one.

The reason is architectural rather than incidental:

- explicit preview requests use the renderer worker's selected preview backend for render evidence by default,
- `/benchmark/simulate` may still use Genesis for the same session,
- a single shared per-session backend cache would let the preview path poison the later simulation path with the wrong backend instance.

This split preserves warm-process reuse while keeping the preview/backend-selection contract correct.

### Backend responsibility split

We do not use one backend for every purpose.

The backend contract is:

1. `physics.backend` selects the physics simulation backend.
2. Genesis remains the backend for Genesis-only simulation behavior.
3. Explicit preview rendering uses the renderer worker's selected preview backend and is executed by the renderer worker.
4. The explicit preview path is a fast geometry/context artifact path, not a Genesis-runtime proof path.
5. Manual render evidence is written into `renders/current-episode/` during the active stage, while the 24-view handoff bundles are written separately under `renders/benchmark_renders/`, `renders/engineer_plan_renders/`, or `renders/final_solution_submission_renders/` depending on the workflow.

This means `/benchmark/validate` and `/benchmark/simulate` are intentionally asymmetric:

1. `/benchmark/validate`
   - checks geometry/objective consistency,
   - does not generate preview artifacts,
   - preserves the same script-source snapshot selected by the parent request when it launches an isolated preview child, so inline `script_content` and non-default `script_path` entrypoints do not get silently replaced by the workspace-authored source file,
   - does not add an extra Genesis load/render/build gate solely for parity checking,
   - fails closed on duplicate top-level labels or labels that use the reserved `environment` or `zone_` namespaces, because MJCF mesh/body names are derived from authored labels and the simulator owns the scene root and `zone_*` bodies.
2. `/benchmark/simulate`
   - runs the selected physics backend,
   - remains the runtime path for Genesis-specific behavior when Genesis is selected,
   - produces dynamic render/video artifacts through the worker-heavy simulation pipeline when simulation evidence is needed,
   - serves as the benchmark-side stability/evidence run for benchmark-owned fixtures rather than a solve gate,
   - uses the benchmark payload observation window from `config/agents_config.yaml` (`benchmark_payload_observation.window_s`, default `1.5s`) so payload out-of-bounds before the window is a hard failure and payload out-of-bounds after the window is benchmark evidence rather than a benchmark-simulation failure.

Genesis-specific runtime behavior is therefore established by actual Genesis simulation runs where Genesis behavior is required, not by duplicating a Genesis render/build check inside fast validation.

### Render profile ownership

The render contract for dynamic simulation evidence is runtime-resolved and recorded with the simulation result, not by benchmark-level task config or agent config.

The rule is:

01. Simulation video is intended to be a backend/service switch. Today it runs on `worker-heavy`/MuJoCo because that path already exists, avoids another HTTP hop, and was the lowest-overhead implementation; moving it later requires a renderer-side video backend such as VTK or an equivalent.

02. The renderer backend exposes a typed capability record that states what artifact modes and view policies it supports.

03. The runtime-selected simulation render choice is serialized in `simulation_result.json` so reviewers can replay the exact evidence path.

04. Explicit preview remains a separate preview contract, executed by the renderer worker, and continues to live in the preview manifest path.

05. `render_cad(...)` is the ephemeral on-demand path. It normalizes scalar/list camera inputs into zip-paired views, renders a composed `Part | Compound` at the requested camera and modality set, streams queued/view-ready status over the websocket control path, and writes the resulting files into `renders/current-episode/` for the active stage. The canonical RGB preview artifact stem is `{part_name}_render_{angle_1}_{angle_2}`, and the persisted file is `<stem>.png`; `part_name` comes from the rendered component label, so previewing `Part(Box(), label="test_part")` at the default 45/45 orbit uses the unchanged `e45_a45` angle family and produces `test_part_render_e45_a45.png`. Scratch previews are separate from simulation evidence, validation results, and the persisted 24-view handoff bundles.

06. When `render_cad(..., payload_path=True)` is requested, the static render bundle may also include a motion-path overlay. The renderer resolves that overlay from the finest available motion artifact for the current workflow, preferring engineer-coder `payload_trajectory_definition.yaml`, then planner `motion_forecast`, then benchmark motion evidence when applicable. The overlay is review context only and does not affect validation or simulation semantics.

07. Every persistent handoff render request publishes an immutable 24-view bundle directory with a bundle-local manifest, using the established 8-azimuth by 3-elevation view family. RGB handoff bundles display the payload-path overlay specified by the relevant benchmark or engineer motion contract by default, and the overlay can be disabled through `render.handoff_rgb_payload_path_overlay.enabled` in `config/agents_config.yaml`. Historical discovery flows through the render bundle contract in [CAD and other infrastructure](./CAD-and-other-infra.md); `renders/render_manifest.json` may remain as a current-bundle compatibility alias. Simulation bundles may also persist `frames.jsonl` and frame-indexed `objects.parquet` sidecars sampled at the video-capture cadence when the active `PhysicsBackend` export path provides them.

08. The `worker_light.utils.render_query` helper family resolves against that bundle-local snapshot when the model needs a point coordinate from a render.

09. The render bundle path itself identifies whether the evidence belongs to benchmark input, engineer planning, or final solution submission. Final solution submission bundles must be composed from the benchmark-owned scene, including any declared benchmark payload, plus the approved engineer solution so benchmark fixtures and objective overlays are present by default. The simulation scene and preview scene snapshots are reconstructed through the shared typed scene-builder module, so authored traversal, payload insertion, and payload naming stay aligned across physics and rendering.

10. If a backend cannot satisfy the selected render path, the failure should surface as a validation/runtime contract error rather than being hidden behind an unrelated global fallback.

Any renderer-emitted file that crosses the `worker-renderer` boundary should already be backed by S3, with worker-light or controller code using the object key to re-materialize it locally if needed.

This keeps MuJoCo and Genesis distinct while still allowing each backend to use its own canonical default view when the runtime resolver allows that.

Agent-facing inspection of persisted simulation video is config-driven. When `config/agents_config.yaml` sets `render.split_video_renders_to_images=true`, `inspect_media(...)` may decode an `.mp4` artifact into representative image frames and attach those frames to the model instead of exposing the raw video bytes as a dead end. The sampling stride is controlled by `render.video_frame_attachment_stride`, so a 60-frame video with stride 6 yields 10 attached frames, while a 6-frame video yields 1 attached frame. `render.video_frame_jpeg_quality_percent` controls the JPEG encoding quality as a percent value. The stored MP4 remains the canonical simulation artifact; the split only affects multimodal review.

The low-frequency simulation-time frame sync path is now supported as an opt-in websocket stream for simulation evidence. The stream targets roughly one PNG every 0.5s of simulated time and is designed to stay manageable because the cadence is low; the final MP4 remains the canonical persisted artifact. Incremental S3 upload of those live frames remains an extension point if a future revision needs bundle-backed persistence for the stream itself.

## Simulation constants and assumptions

We operate in a real-world-like scenario, with rigid bodies, gravity, real-world materials, and standard properties like friction and restitution (bounciness).

Benchmark-owned fixtures are validated against their explicit motion contract and evidence. That benchmark-side contract can be weaker than the engineer-solution contract, but it still must stay deterministic, reviewable, and compatible with the simulation evidence path. Benchmark-side simulation validates the declared fixture motion and stability; it does not ask the benchmark generator to solve the benchmark. The benchmark payload observation window is policy-driven through `config/agents_config.yaml`, and the late-drift exception applies only to the payload, not to benchmark-owned fixtures or simulation bounds. Engineer-authored objects remain physically realistic and must satisfy the normal constraint rules.

### Physically-realistic constraints

In the end, our systems should be transferrable to the real world.

For engineers, constraints must be physically realizable. A CAD-only relationship is not sufficient unless it corresponds to a real-world mechanism or support geometry.

#### Creating realistic constraints

Constraints done by the engineer should be enforced for validity. E.g.: two parts should be actually close together.

To support moving parts (hinges, sliders, motors), we use the joints that correspond to real mechanical interfaces and then validate the resulting assembly against the plan and simulation evidence.

##### Mechanisms and Moving Parts

Genesis (which has parity with MuJoCo) constraints will only ever be spawned from predefined components. A moving constraint must be backed by a real mechanism such as a bearing, motor, or other supported connector, and the connected parts must be physically consistent with the declared plan.

##### Benchmark fixture motion exception

Benchmark-owned moving fixtures are reviewed under an explicit-motion contract.

The rule is:

1. benchmark fixtures may be moving only when the benchmark contract explicitly requires that behavior,
2. benchmark fixtures may use motors, bearings, and other COTS parts as read-only environment components when their identity is explicit, and they are not treated as manufacturable engineer outputs,
3. benchmark handoff artifacts must explicitly document the fixture motion contract, including stable identity, motion kind/topology, axis/path or equivalent reference, bounds or operating envelope, trigger mode, and whether the engineer may rely on that motion,
4. reviewers validate the declared motion against simulation evidence and reject missing, contradictory, unsupported, or non-deterministic motion,
5. benchmark fixtures are validation setup, not engineer-owned solution parts, so manufacturability checks do not apply to them.

<!-- Future work: if benchmark input arrives as STEP, infer candidate constraint/motion metadata from the source geometry before materializing the explicit benchmark motion contract. -->

This exception is benchmark-only. It does not relax engineering realism requirements.

### Planner motion forecast contract

Engineer-owned moving solutions need a planner-authored payload trajectory contract, not just a prose description of the mechanism.

The contract is:

01. The forecast captures the nominal payload trajectory; the tolerance bands define the envelope around that path.
02. The canonical location is a dedicated `motion_forecast` section inside `assembly_definition.yaml` for engineering handoffs that include moving engineer-owned parts. The first anchor must be build-zone valid, and the terminal anchor or terminal event must explicitly prove goal-zone entry/contact.
03. The forecast is sparse and ordered. It is not a full per-timestep replay of the physics engine.
04. The default planner cadence is coarse, typically `0.5s`. The exact cadence and tolerance budgets for planner and coder layers are policy-driven via `config/agents_config.yaml`, not hardcoded in the schema. The benchmark planner may use an even coarser course-setting layer for benchmark-owned moving fixtures when that contract allows it.
05. The coder may generate a denser implementation/verification trace, typically around `0.3s`, but that trace is derived evidence, not a replacement for the planner-owned contract. When required, the engineer coder's precise path lives in a separate engineer-owned `payload_trajectory_definition.yaml` artifact rather than replacing `motion_forecast`; it refines the payload trajectory and contact proof instead of reinterpreting the mechanism.
06. Each anchor must state:
    - `t_s`
    - an explicit `reference_point` such as COM, another named physical point, or a justified geometric proxy
    - absolute world coordinates in millimeters
    - explicit rotation in degrees via `rot_deg`
    - the positional tolerance band for that anchor, and optional rotational tolerance when the anchor admits an envelope instead of an exact pose
    - the first-contact surfaces expected to be touched by that reference point, in the order they are first encountered
07. The first anchor must state `build_zone_valid: true`; the reviewer then checks that its coordinates actually lie inside the benchmark build zone.
08. The terminal anchor must carry `goal_zone_contact: true` or `goal_zone_entry: true`, or an equivalent structured `terminal_event`, and the recorded position must lie inside the benchmark goal zone.
09. Contact order is part of the contract. If the payload touches multiple surfaces before success, the first-touch order and an expected time window for each first contact must be recorded.
10. Tolerances must be grounded in runtime jitter and contact uncertainty. The default positional tolerance on any axis should not exceed `1.2x` the runtime jitter on that axis unless a calculation subsection or risk assessment explicitly justifies a wider band. Rotation is never implicit: the anchor either names an exact `rot_deg` or names a `rot_deg` plus a tolerance envelope.
11. A plan that cannot state this payload trajectory at reviewable resolution is incomplete. The reviewer should not have to infer it from a vague mechanism description.
12. The planner owns the forecast. The coder may refine implementation details inside the approved envelope, but may not silently rewrite the forecast when the plan is already approved.
13. Simulation may fail fast when the realized motion leaves the tolerated corridor for a configurable number of consecutive checks or when the required contact sequence becomes impossible.
14. This contract applies to engineer-owned moving parts only. Benchmark-owned moving fixtures continue to use the benchmark motion contract in `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml`.
15. The benchmark planner uses the coarsest course-setting layer for benchmark-owned moving fixtures, with its cadence and tolerance budget also sourced from config policy or benchmark motion metadata, and downstream engineering treats that layer as read-only context.

Minimal shape:

```yaml
motion_forecast:
  reference_frame: world
  reference_point: com
  planner_sample_stride_s: 0.5 # illustrative; actual stride comes from config/agents_config.yaml
  tolerances:
    position_mm: [1.2, 1.2, 1.2]
    rotation_deg: [0.1, 0.1, 2.0]
  anchors:
    - t_s: 0.0
      pos_mm: [10.0, 10.0, 10.0]
      rot_deg: [0.0, 0.0, 0.0]
      build_zone_valid: true
      first_contacts: []
    - t_s: 0.5
      pos_mm: [10.0, 10.0, 10.5]
      goal_zone_contact: true
      first_contacts:
        - order: 1
          surface: ramp_top
          first_touch_window_s: [0.45, 0.55]
```

The reviewer evaluates the forecast against the plan, the assembly contract, the objective zones, and the runtime jitter envelope. The forecast is invalid if it leaves the contact order implicit, uses a non-world frame without justification, or claims a tolerance wider than the declared uncertainty without an explicit derivation.

##### Engineering motion metadata

Engineering solutions may include moving parts when the mechanism requires them, and the motion metadata must map to a real mechanism and remain reviewable in the planning artifacts.

Map of joints to Genesis (which has parity with MuJoCo) constraints and their uses:

1. RigidJoint to `<weld>` constraint:
   - Used for fixed connections.
   - Connects two bodies rigidly at the joint location.
2. **RevoluteJoint** to `<joint type="hinge">`:
   - Used for axles, pivots, and motors.
   - The joint axis in build123d becomes the hinge axis in Genesis.
   - If the joint is motorized, we add an `<actuator>` targeting this joint.
3. **PrismaticJoint** -> `<joint type="slide">`:
   - Used for linear sliders and rails.
   - The joint axis defines the slide direction.
   - Can be motorized with a `<position>` or `<motor>` actuator.

##### Implementation Logic for constraints

- Walk the `build123d` assembly and inspect `part.joints`.
- If a joint is connected (via `connect_to`), identify the two parts involved.
- Assert the joint is valid programmatically (distance, not conflicting with other constraints, etc.)
- Generate the appropriate Genesis/MuJoCo XML element connecting the two bodies.
- Assign stable names to identifying joints so controllers can reference them (e.g. "motor_joint").

#### Read-only benchmark fixtures

Benchmark-owned fixtures are read-only context. Engineer-owned parts must respect the declared geometry and collision constraints, but this document no longer treats benchmark-side attachment policy as a published contract surface.

#### Allowed components in simulation

The simulation would have only a set number of components that both the benchmark planner and engineer can use. The following list is acceptable:

1. 3d CAD parts:
   - Environment (read-only benchmark context);
     - Objectives (goal, forbid zones)
     - Parts (any obstacle/standard CAD object) <!-- probably needs for a better name-->
     - Input objects (e.g. - a ball that needs to be delivered somewhere.)
   - Engineer parts:
     - 3d CAD parts representing real-life objects that engineers would normally create; bound by all physics.
2. Motors (and simple scripts/functions that run the motors, e.g. in sinusoidal wave, or start/stop every few seconds). Accessible by both engineer and benchmark generator.

<!-- Future:
Bearings.
Gears,
PCBs
Wires
Fluid vessels, e.g. pipes, hoses, or tanks that supply each. 
Fluid pumps.-->

### Constants

- Simulation timestep of the rigid-body simulation - 0.002s (default MuJoCo setting)
- Max simulation time - 30 seconds (configurable globally)
- Max speed - >1000m/s
- Default benchmark size - 1\*1\*1m
- Default stretch - 0.5\*0.5\*0.5 to 2*2*2, disproportionally
- Collision:
  - How often is the simulation checked for collision with goals - every 0.05s.
  - Number of vertices needed for collision - 1 (maybe more in the future)
- Units: Metric.
- Safety factor (for motors and parts breaking) 20%.

## Convex decomposition

<!-- We don't have convex decomposition logic in MuJoCo (we do in Genesis, but we'll approach it later). We'll need a V-HACD logic on worker. -->

Genesis supports convex decomposition natively.

<!-- Note: I have no clue about how V-HACD works. Assume good defaults. -->

## Motors

We use standard Genesis/MuJoCo actuators. They need to be controller by the controller functions.

### Controller functions

We need to define how motors will behave, and we'll use a controller. For this, create a util package like `controllers`, which would have time and position-based controllers.

#### Time-based functions (take in `t` as time)

1. Constant - `constant(power:float) -> float` <!-- as far as I understand, a standard MuJoCo <motor> -->
2. Sinusoidal - `sinusoidal(t: float, power:float) -> float`
3. "full-on, full-off" - a.k.a. a "square" function in signals - `square(time_on_time_off: list[tuple[float,float]], power:float) -> float` - takes in lists of time when to start and stop; and how much power it would output.
4. "smooth on, smooth off"- a.k.a. a "trapezoidal function" in signals `trapezoidal(time_on_time_off: list[tuple[float,float]], power, ramp_up_time: float)`

Note: I'm not a pro in these functions - maybe they need renaming. but that's the idea.

Note: they will need to be importable utils, just as tools like `simulate` are.

#### Implementation for time-based controller functions

One easy way to implement it is to define a dict of control functions, then pass it to simulation logic, and it would control the motors by their control functions. The `assembly_definition.yaml` `final_assembly.parts` entries will contain which controller functions the motors are referencing.

#### Position-based functions

Oftentimes we'll want to control motors through positions, e.g. servos or stepper motors. Define a set of functions that would do inverse kinematics (rotate the motor to a given position, at least).

We want to allow to do something like "at 5 seconds, rotate to 45deg, then at 10 seconds, rotate to 0, and at 15 seconds rotate back to 45 deg." This will also involve Python functions (probably pre-determined). At least a basic set of these (time-based, constant).

<!-- In the future work, I presume, full inverse kinematics pipelines are desired. I know they are trivial in Genesis, it seems not so much in MuJoCo. -->

<!-- Notably, MuJoCo already has some... motor types: " MuJoCo has `position`, `velocity`, `motor` actuators". I don't know how they work -->

<!-- moving-part metadata stays out of benchmark_definition.yaml and lives in assembly_definition.yaml final_assembly.parts; benchmark fixture metadata may live in benchmark_definition.yaml under benchmark_parts. -->

##### Position-based controllers implementation

""" AI-generated, I'm not a pro in the MuJoCo motors.
For position-based control (servos, steppers), we use **MuJoCo's native `<position>` actuator**:

```xml
<actuator>
  <position name="servo1" joint="arm_hinge" 
            kp="{kp_from_COTS}" kv="{kv_from_COTS}"
            forcerange="-{max_torque_nm} {max_torque_nm}"/>
</actuator>
```

**Key differences from `<motor>`**:

- **`ctrl[i]` meaning**: Target position (radians for hinge, meters for slide) – *not* torque
- **Internal PD control**: MuJoCo applies `torque = kp * (target - pos) - kv * vel`
- **Physics-based tracking**: The joint "seeks" the target position naturally (no teleportation)
- **`forcerange`**: Clamps output torque to realistic motor limits (prevents infinite force)

**PD gain tuning** (critical for stability):

- Gains must be tuned relative to body inertia
- Low inertia + high kp = numerical explosion
- Safe starting point: `kp=5`, `kv=0.5` with `mass=1`, `diaginertia=0.01`
- Add joint `damping` to improve stability further

**Available position controllers** (`worker_heavy.utils.controllers`):

- `waypoint(schedule: list[tuple[float, float]])`: Move to target positions at scheduled times
- `hold_position(target: float)`: Hold a fixed target position
- `oscillate(center, amplitude, frequency, phase)`: Sinusoidal position oscillation

"""

Notably, we have a set of COTS motors in COTS section below. We need to assume/research COTS actuator strength and parameters.

### Actuator force limits (forcerange)

MuJoCo's `forcerange` attribute clamps the actuator output to realistic torque limits:

```xml
<!-- Example: MG996R hobby servo with ~1.1 N·m max torque -->
<position name="servo" joint="arm" kp="15" kv="0.8" forcerange="-1.1 1.1"/>
```

**Behavior**:

- If PD control computes torque > `forcerange`, it's clamped to the limit
- Motor "struggles" realistically when overloaded (can't reach target)
- Simulation does NOT fail from clamping alone (see below for failure logic)

**Source of values**: `forcerange` comes from COTS servo catalog (`max_torque_nm` field).

### Motor overload failure

We don't want motors to break; set the maximum *sustained* load threshold above the servo's rated torque.
If a motor is clamped at `forcerange` for more than **2 seconds continuous**, the simulation fails with `motor_overload`.

This forces agents to:

1. Pick appropriately-sized motors for the load
2. Design mechanisms that don't exceed torque limits
   """
   Note: AI-written, I'm not a pro in MuJoCo motors.
