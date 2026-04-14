# Definitions of Success and Failure

## Definition of "success" and failure in the simulation

We want to support one primary use-case: moving a payload from one position to another, using motors and gravity; avoiding forbidden zones, and staying in simulation bounds.

<!-- another use-case could be: given a severe constraint in positioning, design a system which would support a given load. However, the issue is that it's not  -->

### Moving a payload from one screen to another

We define the "simulation objective" from four components:

1. A "build zone" - where the agent can actually create parts (note: the agent is forbidden to construct outside of this zone),
2. A "goal zone" - the area to which the payload needs to move,
3. The payload - the object which is spawned to be moved into the goal
4. A "forbid" zone - an area none of the simulation objects the agent may not go into.

The objectives are always axis-aligned bounding boxes (AABB) for simplicity. The forbid or goal zone is triggered if the agent touches it even slightly.

Additionally, the simulation is constrained by the bounds of the simulation, i.e. the space which the simulation can not leave.

#### Checking for objective interaction

As above, "The forbid or goal zone is triggered if the agent touches it even slightly". This means that if any vertex (let's limit to vertices for simplicity/speed) touches the simulation, it fails.

### Randomization

<!-- LLM-generated from my other spec. -->

The benchmarks are randomized to enable a wider data distribution with less generation effort.

"Static" randomization is stronger than the "runtime" randomization. Static randomization are complete variations of the environment - stretching the entire space, stretching objectives, etc. Whereas runtime randomization - meant to make the engineer less prone to "overfitting" their CAD to the exact environment - is smaller.

#### Static randomization

- The benchmark volume size can vary 2x in all sides, and will be rescaled to random values, e.g. 1.68\*0.8\*1.3; the benchmark generator agent can narrow the scaling down if somehing is expected to break; however it is undesirable as we want to keep randomization higher.
  - The environment - objectives (goals, forbids, build zones) are rescaled respectively.
- Goal, and obstacle positions are randomized by up to 40% of their size inwards (meaning they are becoming smaller and repositioned anywhere in the region where they are becoming smaller; smaller by their own size. They will always stay within original (maximum) bounds for safety).
- The models that make up the scene can and should be different. Up to the point where it remains a valid problem instance for the engineering graph; but the benchmark generation agent must ensure randomization of the environment too; which can be also made quite extreme (which is preferred - we are not to make it easy.)

##### Material static randomization

If a part is moving (has degrees of freedom), let us randomly switch its material for a more randomly generated environment - e.g., a part would be heavier, lighter, more/less stiff, have more/less restitution, have more/less friction coefficient; the material would be from predetermined files.
The engineer would be informed about materials of various parts ahead of time.
(Notably, the benchmark generator should probably allow constraining some materials but only optionally so - e.g. if something is translated by the motor, it probably isn't ABS plastic, it's at least a metal. Allow the "minimum strength" or similar material selection.)

##### Visual static randomization

To allow for better visual generalization and more realistic environments, environment parts will change their colors to alongside of the material change, defined in materials config.

#### Runtime randomization

Notably, the engineer is informed about runtime randomization to prevent unexpected issues.

- The spawned "moved" object will also include some position jitter to ensure the CAD model's robustness against variable input.
- The spawned "moved" object must already clear benchmark-owned fixture geometry at its declared start pose. Runtime jitter validates robustness around that pose; it does not permit an initial overlap.

##### Runtime randomization verification

The runtime randomization verifies robustness across multiple jittered initial scenes (e.g. 5) inside one backend execution.

Execution contract:

1. A verification request is one admitted heavy-worker job.
2. That job performs one MuJoCo/Genesis scene build/load step for the requested design, or uses an equivalent compiled-scene cache hit.
3. The job then spawns `num_scenes` parallel scene/environment instances from that compiled state.
4. Each parallel scene receives its own runtime-jittered initial condition.
5. The backend advances those jittered scenes as one batched simulation run and aggregates outcomes at the end.
6. `num_scenes` means batch width inside one backend run. It does not mean serialized reruns of the whole simulation.
7. Serial full-scene replay over jitter seeds is non-compliant where backend-supported scene batching/reuse is available.
8. Parallel batched execution is mandatory for runtime-randomization verification when backend-supported reuse is available and the worker has enough RAM for the requested batch.

### Failure

Failure is achieved via either of:

1. Timeout of the simulation

   - How to define timeout of the simulation? that's a question. I suggest putting a hard cap of 30 seconds on all simulations and letting the Benchmark Planner decide how quickly a given goal should be achieved (with leeway); no more than 30 seconds though.

2. Any of components going out of bounds of the workspace

   - Benchmark payloads use the config-driven observation window in `config/agents_config.yaml` (`benchmark_payload_observation.window_s`, default `1.5s`): payload out-of-bounds before the window is a failure, while payload out-of-bounds after the window is benchmark evidence rather than a benchmark-simulation failure.
   - This exception applies only to the benchmark payload; benchmark-owned fixtures still fail on out-of-bounds at any time.

3. Instability in simulation (e.g. NaNs, parts interference)

4. Any part going into forbid zones.

5. Any part is broken:

6. The runtime-spawned moved object overlaps benchmark-owned fixture geometry at its declared start pose.

   - This is a startup validation failure, not a physics-side collision event.
   - Reject the benchmark before the first simulation step if the spawn pose is not clear.

## Conversion of CAD to mesh and to MuJoCo/Genesis

We will convert `build123d` CAD files into `obj` format (not STL, because the it is very bulky), and then put the obj into mesh. I think build123d allows a `export_obj(Compound|Part)` function.

The conversion pipeline is - putting every part into mesh;

When I implemented a similar pipeline some time ago, it was helpful to: recenter all build123d parts so that they are at (0,0,0), then export them, then add them to Genesis/MuJoCo with confidence at their known position (and trivially) because they are at (0,0,0). We need to know build123d part position ahead of time though.

<!-- Note: Genesis if we'll migrate to it, supports GLB. -->

## Preview/visualization

We want the agent to be able to preview their own CAD models (likely done more often). We will render CAD images, not MuJoCo for it. The materials will have their colors.

### Mesh limits and Simplification

The mesh is unbounded in vertex counts because we are simulating engineering-grade materials. That said, the mesh should be simplified where *safe* to do so; however the higher quality is desired.

- **Smoke Test Optimization**: When `smoke_test_mode=True` is requested, the system automatically increases the CAD-to-STL export tolerance (e.g., from 0.1 to 1.0). This generates coarser meshes that are drastically faster for the physics engine (especially Genesis on CPU) to voxelize, enabling rapid stability and multitenancy checks.
- **Dynamic Manufacturing Resolution**: Simulation and validation logic must dynamically resolve the manufacturing method from CAD metadata. This ensures that validation rules (like CNC undercut detection) are only applied when appropriate for the chosen production process.

## Materials

We have a set of materials defined in `manufacturing_config.yaml`, which defines: `materials` section, and which materials can be used for the simulation - their weight, price, and cost per KG. The config is auto-validated with unit tests (e.g., can't reference and inexisting material).

`manufacturing_config.yaml` can be read-only for the agents to gauge the pricing ahead of time. It is also used during programmatic validation of manufacturability.

`manufacturing_config.yaml` sample schema:

```yaml
manufacturing_processes:
  cnc:
    setup_price: [...]
    price_per_X: [...]
    price_per_Y: [...]

  injection_molding:
  # [...]

materials:
  alu-6061:
    color: #
    yield_strength:
    restitution: 
    friction_coef: 
    # and others
  ... 
```

The materials are only ever chosen from the config.

## "Workbenches" - manufacturability verification

The agents will have *Workbenches* - a set of tools they can use to:

1. Verify their manufacturability.
2. Calculate costs of their parts (and verify against the user-inputted goals)
