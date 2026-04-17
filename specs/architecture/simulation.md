# Simulation

## Scope summary

- Primary focus: physics simulation contract, backend split for simulation execution, and motion/constraint rules.
- Defines simulation constants, allowed mechanisms and components, controller semantics, benchmark fixture motion exception, and the motion contracts used by planners and coders.
- Rendering and preview policy live in [Rendering](./rendering.md); this file only covers simulation semantics and the evidence the simulation result must describe.

## Genesis for simulation

While this platform has notable downsides for future use, we pick Genesis because it provides the simulation backend we need and is fast enough to work.

Operational benchmarking notes, runtime optimization attempts, and dated performance measurements for the simulation stack are tracked in the relevant migration docs under `specs/migrations/`.

### Runtime cost model

For architecture and optimization decisions, we treat simulation runtime cost as three separate layers:

1. process-global cold cost:
   - Python child startup,
   - module import and runtime setup,
   - Genesis runtime initialization,
   - process-local compiler and backend warmup,
2. scene-specific build cost:
   - scene creation,
   - mesh conversion,
   - geometry-specific build work,
   - collision and backend scene preparation,
   - object-family-specific compilation work when it occurs,
3. actual simulation execution cost:
   - stepping the physics scene,
   - result extraction and validation logic,
   - simulation-side artifact recording.

This distinction is mandatory for future optimization work because different changes affect different layers.

- A persistent dedicated simulation child removes repeated process-global cold cost across requests on the same worker instance.
- A persistent child does not, by itself, remove scene-specific build cost for materially different scenes.
- Scene-specific cost reduction requires separate caching or reuse strategies such as compiled-scene caching, mesh caching, or geometry-hash caches.

The optimization log dated 2026-03-09 records the evidence for this split. In particular:

- the earlier init benchmark showed that literal `gs.init()` is not the dominant repeated cost by itself,
- the follow-up warm-process benchmark showed that different-scene-next cost is real, but still does not fully reset to the original cold-process cost for the primitive case,
- the minimal mesh case showed nearly identical warm-process cost for same-versus-different OBJ scenes in that experiment,
- the direct `simulate_subprocess(...)` benchmark on two distinct successful bundles, using distinct `session_id` values and both bundle orders, measured fresh-child totals of `125.8s` to `127.9s` and reused-child totals of `80.2s` to `80.9s`,
- the same direct benchmark measured second-request wall-clock time dropping from `31.4s` to `32.1s` in fresh-child mode down to `2.4s` to `2.5s` in reused-child mode, which is the strongest current evidence that the repeated cost is in process lifecycle and warm-runtime loss rather than same-session backend caching.

The architecture implication is explicit:

- we should not discuss "simulation startup cost" as if it were one number,
- we should separately measure and optimize process-global cold cost and scene-specific build cost,
- we should not reject the persistent-child design merely because different scenes still pay real rebuild cost.

### Persistent child runtime direction

The current optimization direction is now concrete enough to treat as an implementation plan rather than only a hypothesis.

The runtime direction is:

1. keep `worker-heavy` single-flight,
2. keep the process boundary between the FastAPI parent and the simulation runtime,
3. replace one-fresh-child-per-request execution in `simulation_runner.py` with one persistent dedicated child executor per worker instance for `simulate` and `validate`,
4. recreate that executor fail-closed after `BrokenProcessPool` or explicit shutdown,
5. add explicit child-side cleanup functions that clear backend or session state without killing the warm process.

The benchmark evidence makes one point explicit:

- the implementation target is process reuse,
- not thread reuse,
- not repeated same-session backend reuse,
- and not a narrow micro-optimization around the literal `gs.init()` call.

The persistent-child refactor therefore has to preserve the existing behavior contracts while changing only the child lifecycle:

1. public `/benchmark/*` request and response contracts stay unchanged,
2. `/ready` and heavy-admission semantics stay unchanged,
3. the current request fails closed if the child crashes,
4. the next request recreates a fresh child,
5. child cleanup is explicit and observable rather than being an accidental side effect of process exit.

The detailed dated plan for this refactor is recorded in the relevant migration docs under `specs/migrations/major/`.

### Warm-child backend cache split

The persistent child keeps backend caches split by both session and backend type.

The cache rule is:

1. a session may hold a warm MuJoCo backend and a warm Genesis backend at the same time,
2. explicit preview requests must not overwrite or alias the backend instance later used by `/benchmark/simulate`,
3. backend cache lookup is therefore keyed by `(session_id, backend_type)`, not by `session_id` alone,
4. session cleanup closes all cached backend instances for that session, not only the most recent one.

The reason is architectural rather than incidental:

- the preview path uses the renderer worker's selected preview backend for render evidence by default,
- `/benchmark/simulate` may still use Genesis for the same session,
- a single shared per-session backend cache would let the preview path poison the later simulation path with the wrong backend instance.

This split preserves warm-process reuse while keeping the simulation/backend-selection contract correct.

### Backend responsibility split

The system does not use one backend for every purpose.

The backend contract is:

1. `physics.backend` selects the physics simulation backend,
2. Genesis remains the backend for Genesis-only simulation behavior,
3. `/benchmark/validate` checks geometry/objective consistency and does not generate preview artifacts,
4. `/benchmark/simulate` runs the selected physics backend, remains the runtime path for Genesis-specific behavior when Genesis is selected, and produces the motion/result record that downstream roles compare against the rendered evidence,
5. benchmark payload observation from `config/agents_config.yaml` (`benchmark_payload_observation.window_s`, default `1.5s`) decides whether early payload out-of-bounds is a hard failure or later drift is evidence rather than a benchmark-simulation failure,
6. preview rendering is separate and lives in [Rendering](./rendering.md).

This means `/benchmark/validate` and `/benchmark/simulate` are intentionally asymmetric:

1. `/benchmark/validate`
   - checks geometry and objective consistency,
   - preserves the same script-source snapshot selected by the parent request when it launches an isolated preview child, so inline `script_content` and non-default `script_path` entrypoints do not get silently replaced by the workspace-authored source file,
   - does not add an extra Genesis load/render/build gate solely for parity checking,
   - fails closed on duplicate top-level labels or labels that use the reserved `environment` or `zone_` namespaces, because MJCF mesh/body names are derived from authored labels and the simulator owns the scene root and `zone_*` bodies.
2. `/benchmark/simulate`
   - runs the selected physics backend,
   - remains the runtime path for Genesis-specific behavior when Genesis is selected,
   - serves as the benchmark-side stability and evidence run for benchmark-owned fixtures rather than a solve gate,
   - uses the benchmark payload observation window from `config/agents_config.yaml` (`benchmark_payload_observation.window_s`, default `1.5s`) so payload out-of-bounds before the window is a hard failure and payload out-of-bounds after the window is benchmark evidence rather than a benchmark-simulation failure.

Genesis-specific runtime behavior is therefore established by actual Genesis simulation runs where Genesis behavior is required, not by duplicating a Genesis render/build check inside fast validation.

### Simulation evidence record

`simulation_result.json` is the canonical machine-readable record of the latest simulation run. It captures the selected backend, the observed outcome, and the motion facts needed to compare the run against the benchmark contract and any related render evidence. Any media bundle referenced by the result is owned by [Rendering](./rendering.md).

## Simulation constants and assumptions

The simulation operates in a real-world-like scenario, with rigid bodies, gravity, real-world materials, and standard properties like friction and restitution (bounciness).

Benchmark-owned fixtures are validated against their explicit motion contract and evidence. That benchmark-side contract can be weaker than the engineer-solution contract, but it still must stay deterministic, reviewable, and compatible with the simulation evidence path. Benchmark-side simulation validates the declared fixture motion and stability; it does not ask the benchmark generator to solve the benchmark. The benchmark payload observation window is policy-driven through `config/agents_config.yaml`, and the late-drift exception applies only to the payload, not to benchmark-owned fixtures or simulation bounds. Engineer-authored objects remain physically realistic and must satisfy the normal constraint rules.

The MuJoCo runtime-randomization verifier keeps the rollout and replay phases separate. Rollout uses MuJoCo batching, while replay stays serial for per-scene early exits and derived collision checks. The replay path now caches body and site ids once per scene and prechecks static bodies so the hot loop only handles moving-body state.

### Physically-realistic constraints

In the end, our systems should be transferrable to the real world.

For engineers, constraints must be physically realizable. A CAD-only relationship is not sufficient unless it corresponds to a real-world mechanism or support geometry.

#### Creating realistic constraints

Constraints created by the engineer should be enforced for validity. For example, two parts should be actually close together.

To support moving parts (hinges, sliders, motors), we use the joints that correspond to real mechanical interfaces and then validate the resulting assembly against the plan and simulation evidence.

##### Mechanisms and Moving Parts

Constraints must only be spawned from predefined components. A moving constraint must be backed by a real mechanism such as a bearing, motor, or other supported connector, and the connected parts must be physically consistent with the declared plan.

##### Benchmark fixture motion exception

Benchmark-owned moving fixtures are reviewed under an explicit-motion contract.

The rule is:

1. benchmark fixtures may be moving only when the benchmark contract explicitly requires that behavior,
2. benchmark fixtures may use motors, bearings, and other read-only environment components when their identity is explicit, and they are not treated as manufacturable engineer outputs,
3. benchmark handoff artifacts must explicitly document the fixture motion contract, including stable identity, motion kind/topology, axis/path or equivalent reference, bounds or operating envelope, trigger mode, and whether the engineer may rely on that motion,
4. reviewers validate the declared motion against simulation evidence and reject missing, contradictory, unsupported, or non-deterministic motion,
5. benchmark fixtures are validation setup, not engineer-owned solution parts, so manufacturability checks do not apply to them.

<!-- Future work: if benchmark input arrives as STEP, infer candidate constraint and motion metadata from the source geometry before materializing the explicit benchmark motion contract. -->

This exception is benchmark-only. It does not relax engineering realism requirements.

### Planner motion forecast contract

Engineer-owned moving solutions need a planner-authored payload trajectory contract, not just a prose description of the mechanism.

The contract is:

01. The forecast captures the nominal payload trajectory; the tolerance bands define the envelope around that path.
02. The canonical location is a dedicated `motion_forecast` section inside `assembly_definition.yaml` for engineering handoffs. That field name is the historical label for the planner-owned coarse payload trajectory. The first anchor must be build-zone valid, and the terminal anchor or terminal event must explicitly prove goal-zone entry/contact.
03. The forecast is sparse and ordered. It is not a full per-timestep replay of the physics engine.
04. The default planner cadence is coarse, typically `0.5s`. The exact cadence and tolerance budgets for planner and coder layers are policy-driven via `config/agents_config.yaml`, not hardcoded in the schema. The benchmark planner may use an even coarser course-setting layer for benchmark-owned moving fixtures when that contract allows it.
05. The coder may generate a denser implementation and verification trace, typically around `0.3s`, but that trace is derived evidence, not a replacement for the planner-owned contract. The engineer coder's precise path lives in a separate engineer-owned `payload_trajectory_definition.yaml` artifact rather than replacing `motion_forecast`; it refines the same payload-trajectory contract and contact proof at higher resolution instead of reinterpreting the mechanism, and it is required for every engineering handoff.
06. Each anchor must state:
    - `t_s`
    - an explicit `reference_point` such as COM, another named physical point, or a justified geometric proxy
    - absolute world coordinates in millimeters
    - explicit rotation in degrees via `rot_deg`
    - the positional tolerance band for that anchor, and optional rotational tolerance when the anchor admits an envelope instead of an exact pose
    - the first-contact surfaces expected to be touched by that reference point, in the order they are first encountered
07. The first anchor must state `build_zone_valid: true`; the reviewer then checks that its coordinates equal the payload spawn position and still lie inside the benchmark build zone.
08. The terminal anchor must carry `goal_zone_contact: true` or `goal_zone_entry: true`, or an equivalent structured `terminal_event`, and the recorded position must equal the center of the benchmark goal zone and still lie inside that zone.
09. Contact order is part of the contract. If the payload touches multiple surfaces before success, the first-touch order and an expected time window for each first contact must be recorded.
10. Tolerances must be grounded in runtime jitter and contact uncertainty. The default positional tolerance on any axis should not exceed `1.2x` the runtime jitter on that axis unless a calculation subsection or risk assessment explicitly justifies a wider band. Rotation is never implicit: the anchor either names an exact `rot_deg` or names a `rot_deg` plus a tolerance envelope. Because the current payloads are rigid-body only, the validated trajectory may not rise above the spawn height at any checked point.
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
- Assert the joint is valid programmatically (distance, not conflicting with other constraints, etc.).
- Generate the appropriate Genesis/MuJoCo XML element connecting the two bodies.
- Assign stable names to identifying joints so controllers can reference them (e.g. `motor_joint`).

#### Read-only benchmark fixtures

Benchmark-owned fixtures are read-only context. Engineer-owned parts must respect the declared geometry and collision constraints, but this document no longer treats benchmark-side attachment policy as a published contract surface.

#### Allowed components in simulation

The simulation would have only a set number of components that both the benchmark planner and engineer can use. The following list is acceptable:

1. 3D CAD parts:
   - Environment (read-only benchmark context):
     - Objectives (goal, forbid zones)
     - Parts (any obstacle or standard CAD object)
     - Input objects (for example, a ball that needs to be delivered somewhere)
   - Engineer parts:
     - 3D CAD parts representing real-life objects that engineers would normally create; bound by all physics.
2. Motors and simple scripts or functions that run the motors, for example in a sinusoidal wave or start/stop every few seconds. Accessible by both engineer and benchmark generator.

<!-- Future:
Bearings.
Gears,
PCBs
Wires
Fluid vessels, e.g. pipes, hoses, or tanks that supply each.
Fluid pumps.-->

### Constants

- Simulation timestep of the rigid-body simulation: `0.002s` (default MuJoCo setting),
- Max simulation time: `30 seconds` (configurable globally),
- Max speed: `>1000m/s`,
- Default benchmark size: `1*1*1m`,
- Default stretch: `0.5*0.5*0.5 to 2*2*2`, disproportionally,
- Collision:
  - How often the simulation is checked for collision with goals: every `0.05s`,
  - Number of vertices needed for collision: `1` (maybe more in the future),
- Units: Metric,
- Safety factor for motors and parts breaking: `20%`.

## Convex decomposition

<!-- MuJoCo does not currently provide convex decomposition; the worker implementation will need a V-HACD path later. -->

Genesis supports convex decomposition natively.

<!-- V-HACD behavior is left to the worker implementation; assume good defaults. -->

## Motors

The simulation uses standard Genesis/MuJoCo actuators. They are controlled by controller functions.

### Controller functions

Motor behavior is defined through controller functions exposed from a utility package such as `controllers`, which should provide time-based and position-based controllers.

#### Time-based functions (take in `t` as time)

1. Constant - `constant(power: float) -> float`
2. Sinusoidal - `sinusoidal(t: float, power: float) -> float`
3. Full-on, full-off - a.k.a. a square function in signals - `square(time_on_time_off: list[tuple[float, float]], power: float) -> float` - takes in lists of time when to start and stop; and how much power it would output.
4. Smooth on, smooth off - a.k.a. a trapezoidal function in signals - `trapezoidal(time_on_time_off: list[tuple[float, float]], power: float, ramp_up_time: float) -> float`

The exact names may change, but the control modes should remain available.

The controller utilities must be importable from the runtime `utils` package, just like tools such as `simulate`.

#### Implementation for time-based controller functions

One implementation option is to define a dict of control functions, then pass it to the simulation logic so it can control the motors through those functions. The `assembly_definition.yaml` `final_assembly.parts` entries will contain which controller functions the motors reference.

#### Position-based functions

Position-based controllers should support servos and stepper motors. Define a set of functions that do inverse kinematics, at least to rotate the motor to a given position.

The controller layer should support schedules such as "at 5 seconds, rotate to 45deg, then at 10 seconds, rotate to 0, and at 15 seconds rotate back to 45 deg" using Python functions. At minimum, the controller set should cover the time-based and constant cases.

<!-- Future work: full inverse kinematics pipelines may eventually replace the hand-authored position controllers. -->

<!-- MuJoCo already exposes `position`, `velocity`, and `motor` actuators; the controller layer decides which mode to use. -->

##### Position-based controllers implementation

For position-based control (servos, steppers), we use MuJoCo's native `<position>` actuator:

```xml
<actuator>
  <position name="servo1" joint="arm_hinge"
            kp="{kp_from_catalog}" kv="{kv_from_catalog}"
            forcerange="-{max_torque_nm} {max_torque_nm}"/>
</actuator>
```

Key differences from `<motor>`:

- `ctrl[i]` meaning: target position (radians for hinge, meters for slide) - not torque,
- internal PD control: MuJoCo applies `torque = kp * (target - pos) - kv * vel`,
- physics-based tracking: the joint seeks the target position naturally, without teleportation,
- `forcerange`: clamps output torque to realistic motor limits and prevents infinite force.

PD gain tuning is critical for stability:

- gains must be tuned relative to body inertia,
- low inertia plus high kp can cause numerical explosion,
- safe starting point: `kp=5`, `kv=0.5` with `mass=1`, `diaginertia=0.01`,
- add joint `damping` to improve stability further.

Available position controllers (`worker_heavy.utils.controllers`):

- `waypoint(schedule: list[tuple[float, float]])`: move to target positions at scheduled times,
- `hold_position(target: float)`: hold a fixed target position,
- `oscillate(center, amplitude, frequency, phase)`: sinusoidal position oscillation.

Catalog-backed motors in the actuator section below must supply their strength and parameter values from the motor catalog.

### Actuator force limits (forcerange)

MuJoCo's `forcerange` attribute clamps the actuator output to realistic torque limits:

```xml
<!-- Example: MG996R hobby servo with ~1.1 N·m max torque -->
<position name="servo" joint="arm" kp="15" kv="0.8" forcerange="-1.1 1.1"/>
```

Behavior:

- If PD control computes torque above `forcerange`, it is clamped to the limit,
- Motor "struggles" realistically when overloaded and cannot reach target,
- Simulation does not fail from clamping alone; see the failure logic below.

Source of values: `forcerange` comes from the motor catalog (`max_torque_nm` field).

### Motor overload failure

The maximum sustained load threshold must stay above the servo's rated torque.
If a motor is clamped at `forcerange` for more than `2 seconds` continuous, the simulation fails with `motor_overload`.

This forces agents to:

1. pick appropriately-sized motors for the load,
2. design mechanisms that do not exceed torque limits.
