# COTS Geometry Import

## Scope summary

- Primary focus: class-first resolution for catalog-backed COTS parts.
- Defines the typed class registry behind catalog-aware construction and the fidelity contract for imported proxy geometry.
- Sets the MVP policy that motors are first priority and that imported geometry should be interface-faithful, not vendor-faithful.
- Covers provenance, ownership, and verification expectations for imported COTS geometry.
- Does not define catalog search or simulation physics; those concerns remain in the COTS search and simulation architecture docs.

This document assumes the authored-script split already exists. It does not redefine `benchmark_script.py` or `solution_script.py`; it defines the COTS geometry import layer those scripts may call.

## Problem statement

The system already has COTS catalog metadata, hand-authored proxy parts, and catalog search, but it lacks a stable contract that turns a resolved catalog `part_id` into the right concrete COTS class and constructor arguments.

That gap creates four problems:

1. authored CAD scripts cannot rely on one predictable class-aware path for catalog-backed motors or other COTS components,
2. the catalog currently stores `import_recipe` text that looks like geometry source but is not a runtime construction mechanism,
3. benchmark-owned fixtures and engineer-owned BOM parts need different ownership semantics even when they share the same underlying catalog part,
4. the system needs an explicit verification story for proxy geometry so the MVP can ship quickly without pretending to be vendor-perfect.

The architecture answer is not to teach the runtime to execute catalog text. The answer is to add a typed, deterministic geometry provider layer.

## Current state

The current codebase already has the right ingredients, but they are not yet wired together as a public import path.

1. `shared/cots/runtime.py` resolves catalog rows and carries provenance metadata.
2. `shared/cots/indexer.py` generates `import_recipe` strings and populates catalog entries.
3. `shared/cots/parts/motors.py` contains hand-authored proxy geometry for a few families.
4. `shared/workers/loader.py` executes authored scripts and extracts their result objects, but it does not resolve catalog parts into concrete COTS classes.
5. `worker_heavy/utils/validation.py` and related costing code use COTS data for pricing and provenance, not for geometry construction.
6. `shared/cots/base.py` already emits usage events when a COTS instance is constructed, which gives the class-first contract a natural place to prove that a declared part was actually instantiated.

The missing layer is a class registry plus catalog-aware factory that sits between the catalog and authored CAD code.

## Core decision

### Public contract

The public contract is a concrete COTS class, not a generic geometry-import helper.

```py
from shared.cots.parts.motors import ServoMotor

motor = ServoMotor(size="DS3218")
# or, when exact catalog resolution is needed:
motor = ServoMotor.from_catalog_id("ServoMotor_DS3218")
```

The contract is:

1. catalog-aware construction resolves a `part_id` to a concrete COTS class plus constructor arguments,
2. the class instance is the geometry object; a separate `geometry()` method is not required for the MVP,
3. `label` is optional and is only a scene label, not catalog identity,
4. construction returns geometry in the provider's canonical local frame at the origin,
5. the class instance may attach existing CAD metadata such as `PartMetadata` or `CompoundMetadata`,
6. the resolution path must fail closed if the `part_id` does not resolve or if no provider exists for the resolved catalog family.

The class-aware factory must not require extra catalog fields for the MVP. If a future family genuinely needs a second selector, that selector must be justified by ambiguity or provider safety, not convenience.

### Separation of concerns

The system keeps three steps distinct:

1. COTS Search finds candidates and returns verified `part_id` values.
2. The class-aware factory instantiates the chosen `part_id` as a concrete COTS object.
3. Validation and costing persist provenance and enforce ownership rules.

Resolution does not search, and search does not resolve classes. The factory may validate a `part_id` against the catalog snapshot, but it does not choose a candidate or perform ranking.

## Geometry fidelity policy

### MVP target

The MVP target is interface fidelity.

The imported model should be good enough for:

1. placement,
2. collision and clearance checks,
3. preview rendering,
4. simulation attachment,
5. reviewer understanding.

The imported model does not need to be vendor faithful.

### What must be modeled

For a motor proxy, the geometry must model the things the rest of the system actually depends on:

1. outer envelope,
2. shaft axis and shaft protrusion,
3. mounting face or mounting footprint,
4. mounting hole pattern or equivalent attachment geometry,
5. connector or cable exit clearance if the part needs it for routing,
6. approximate mass and bounding box consistency.

### What must not be modeled

The MVP does not need:

1. threads,
2. screw heads,
3. casting marks,
4. branding,
5. photo-real surface detail,
6. vendor mesh fidelity for its own sake.

The model may look similar, but no more. Extra visual detail is not a substitute for correct mounting and axis contracts.

### Tolerance policy

The proxy should be close enough to be useful, not close enough to waste the schedule.

Recommended proxy tolerances are:

1. outer envelope within the larger of 10 percent or 2 mm,
2. shaft axis, mount datum, and hole center locations within 0.5 mm,
3. connector keepout or lead exit placement within 0.5 mm when that feature matters,
4. exact `cots_id`, label, and catalog provenance fields.

Those tolerances are for the proxy model, not for the behavior layer. Torque, speed, current, and other behavior parameters still come from catalog or simulation logic.

## Provider architecture

### Class registry

The geometry layer is a typed class registry, not a dict of ad hoc import snippets.

The registry should be modeled with typed classes and explicit provider identifiers. That keeps the architecture aligned with the repo rule that favors classes over freeform dicts for storage and API contracts.

Each provider entry should answer four questions:

1. Which canonical `part_id` does it serve?
2. Which family or variant does it implement?
3. Which concrete COTS class or factory creates the geometry?
4. Which interface contract does the returned geometry promise?

### Canonical flow

The resolution flow is:

1. resolve the catalog row for `part_id`,
2. select the matching provider,
3. build the proxy geometry,
4. attach metadata and labels,
5. return the class instance to the authored script,
6. let validation and simulation handle the rest.

The provider is allowed to use catalog metadata such as dimensions, weight, and category. It is not allowed to replace the catalog with inferred guesses.

The provider also defines the part's local frame. For motors, that local frame
is the rotation contract: the returned geometry must be built so that the
shaft axis, mounting datum, and connector clearance are consistent with the
declared provider orientation. Spin direction does not live in the geometry
provider; it lives in the motion or joint contract.

### Current provider seeds

The current hand-authored classes in `shared/cots/parts/motors.py` are the initial seed providers.

For the MVP, the motor proxy provider should be the first fully supported family. The existing `ServoMotor` implementation can be treated as the seed geometry source and may later gain a `from_catalog_id(...)` class-aware factory if the implementation needs exact catalog resolution.

### Future provider families

Later provider families may include:

1. `bd_warehouse`-backed standard parts where the external library already matches the needed family,
2. vendor asset imports when a trustworthy STEP or mesh asset exists,
3. other COTS families when the registry needs to expand.

Those later providers must follow the same typed registry contract and the same fail-closed resolution rules.

## Motor MVP

### Why motors first

Motors are the first priority because they are the most obvious cross-cutting COTS geometry family in the current codebase.

They drive three different concerns:

1. physical fit and mounting,
2. benchmark fixture realism.

That makes them the best first slice for proving the import architecture without broadening scope.

### Motor proxy contract

The motor proxy should expose a stable interface frame.

The recommended canonical frame is:

1. local origin at the mounting datum for the part,
2. local `+Z` aligned with the shaft axis,
3. local `-Z` pointing into the body or toward the mounting face interior,
4. local lateral axes used only for connector placement and footprint symmetry.

The provider may build the proxy internally in any convenient orientation as long as it exports that same declared interface frame.

That frame is the only orientation contract. The class-aware factory does not move or rotate the part into world space.

### Motor proxy contents

For the MVP, a motor proxy may be a small compound of simple solids rather than a vendor-perfect model.

The proxy should include:

1. the main body,
2. the shaft or horn stub,
3. mounting ears or a mounting footprint when those matter to fit,
4. a connector or cable exit silhouette when clearance matters,
5. any obvious keepout around the actuator head.

The proxy may deliberately omit fine features. The geometry is meant to be good enough for assembly reasoning and preview, not a dimensional copy of a vendor catalog page.

### Motor metadata

The returned motor geometry should carry the part identity through the existing CAD metadata contract.

At minimum, the object should preserve:

1. `PartMetadata.cots_id`,
2. the fixed/read-only ownership flag when the context is benchmark-owned,
3. any existing joint or axis metadata that the simulation layer needs,
4. a stable label when one is provided by the caller.

The geometry class or factory does not decide whether the part is benchmark-owned or engineer-owned. Ownership comes from the assembly context and the handoff artifacts.

## Ownership model

### Benchmark-owned fixtures

Benchmark-owned COTS parts are read-only environment fixtures.

If a benchmark uses an imported motor as fixture geometry, the part still remains benchmark context, not engineer deliverable context.

That means:

1. the geometry may be imported with the same helper,
2. the part follows the benchmark fixture contract and remains read-only benchmark context,
3. the part is excluded from engineer manufacturability validation and engineer pricing,
4. the benchmark handoff still needs visible geometry and stable provenance.

### Engineer-owned COTS parts

Engineer-owned imported COTS parts are solution components, not manufactured parts.

They contribute to:

1. engineer cost,
2. engineer weight,
3. assembly fit and simulation,
4. reviewer-visible evidence.

They do not contribute to manufactured-part pricing or fabrication routing.

### Ownership is not provider identity

The geometry provider does not determine ownership.

Ownership comes from:

1. where the part lives in the handoff,
2. which authored script created it,
3. whether the benchmark definition marks it as a fixture,
4. whether the assembly definition treats it as solution BOM or benchmark context.

That separation keeps the geometry layer reusable without letting it smuggle policy decisions into CAD code.

## Catalog and provenance

### Catalog identity

The canonical import key is the catalog `part_id`.

Alias normalization may exist internally, but the public contract should not depend on freeform names or guessed family strings. A caller should be able to look up a motor by the catalog row that was selected from search, then resolve that exact row into geometry.

### `import_recipe` role

`import_recipe` remains a catalog artifact, not an execution artifact.

It can serve as:

1. provenance text,
2. search-agent output,
3. debugging scaffold,
4. future template materialization input.

It must not be treated as the geometry import runtime.

### Provenance persistence

The class-aware factory is not the provenance store. Downstream validation and handoff artifacts still need the same catalog fields already used elsewhere in the system:

1. `catalog_version`,
2. `bd_warehouse_commit`,
3. `catalog_snapshot_id`,
4. `generated_at`.

The imported geometry should remain traceable to the catalog snapshot that produced it.

## Search, import, and prompts

### Search remains a separate node

The COTS Search subagent remains the mechanism for finding candidate parts.

It returns candidate part IDs and catalog metadata. It does not instantiate geometry.

### Class resolution is callable from authored scripts

Authored benchmark and solution scripts use the concrete COTS class or class-aware factory to instantiate the selected geometry after search or direct selection.

That keeps the authoring surface simple:

1. search or choose the part,
2. resolve the concrete class or factory for the chosen `part_id`,
3. place the returned geometry in the assembly,
4. let validation and simulation check the rest.

### Future scaffold hints

<!-- Future work: workspace template generation may insert commented class-instantiation examples into generated `benchmark_script.py` and `solution_script.py`, but that is a scaffold convenience only. It must not mutate live authored files at runtime or become the source of truth for geometry resolution. -->

If scaffold hints are added later, they should be generated from the same provider registry and kept commented out.

## Verification

### Verification layers

The class-resolution architecture needs three separate verification layers.

1. Geometry verification
   - the provider resolves,
   - the class instantiates,
   - the geometry exports cleanly,
   - the object renders with a sensible silhouette.
2. Interface verification
   - the shaft axis is correct,
   - the mounting datum is correct,
   - the mount pattern or keepout is correct,
   - the proxy envelope is within tolerance.
3. Behavior verification
   - the motor parameters used by simulation still match the expected part class,
   - power gating and torque behavior remain consistent with the existing simulation contract,
   - benchmark-owned fixtures stay read-only context.

### Declared COTS tracking

If a benchmark or solution handoff declares a COTS component as part of the
intended design, the authored geometry must actually instantiate that
component. Matching is by declared inventory, not by approximate geometry: the
realized COTS set must preserve the declared `part_id`s, labels, and quantities
as a multiset. A declared-but-unimported, extra, relabeled, or pair-swapped
COTS part is not considered used.

That check is separate from pricing. A part can be valid in YAML and still be a
contract failure if the authored geometry never instantiates it. The existing
`ComponentUsageEvent` emission from `COTSPart` is the natural signal for that
check.

### Failure policy

Verification must fail closed.

The failure classes are straightforward:

1. unknown `part_id`,
2. no registered provider,
3. geometry build failure,
4. interface contract mismatch,
5. provenance mismatch,
6. behavior mismatch,
7. unsupported family used as if it were supported.

No hidden fallback to a dummy geometry is allowed for the MVP motor path.

### Test entrypoint

The repo-wide integration-test rule still applies.

The authoritative checks for this architecture should run through `./scripts/run_integration_tests.sh`. The class-resolution layer should be covered by integration tests that exercise the real catalog lookup, the real geometry builder, and the real preview or simulation path.

### What the tests should prove

The first integration slice should prove:

1. a known motor `part_id` resolves to the correct concrete class or factory,
2. the geometry has the expected footprint and interface datums,
3. the returned object preserves COTS identity,
4. the instantiated motor can be used in benchmark and solution authored scripts,
5. motor behavior in simulation remains consistent with the existing actuation path,
6. missing or invalid `part_id` values fail closed.

## Non-goals

This document intentionally does not require:

1. vendor-fidelity STEP replicas,
2. automatic internet scraping of vendor assets,
3. runtime execution of `import_recipe` text,
4. a generic importer for every COTS family on day one,
5. editing base authored files at startup,
6. replacing the separate geometry and simulation contracts,
7. geometry details that do not affect fit, preview, or behavior.

Those items are valid future work, but they are not part of the MVP.

## Rollout phases

### Phase 1

The first phase is motor-only and uses handwritten build123d proxy builders.

The implementation should:

1. expose a class-aware factory or equivalent catalog-resolution entrypoint on the COTS base/class layer,
2. route motor `part_id` values through a typed class registry,
3. preserve COTS metadata, provenance, and usage events,
4. verify the proxy geometry with integration tests.

### Phase 2

The second phase can add more families after motors stabilize.

That may include:

1. PSU,
2. relay,
3. connector,
4. wire,
5. bearing or mechanical connector providers where their geometry is already reliable in `bd_warehouse`.

### Phase 3

The third phase can add richer asset sources.

That may include:

1. vendor asset imports,
2. deeper interface metadata,
3. scaffold generation for authoring templates,
4. optional preview helpers that surface the chosen provider family in reviewer artifacts.

## Acceptance criteria

The architecture is complete enough for the MVP when all of the following are true:

1. A known motor `part_id` can be resolved through the class-aware factory without any extra catalog selectors.
2. The returned geometry is a useful proxy, not a vendor-perfect copy, and still matches the declared interface contract.
3. The resolution path does not execute catalog `import_recipe` text.
4. Benchmark-owned and engineer-owned COTS parts can share the same class path while remaining distinct in ownership and pricing.
5. Motors are supported first, while the remaining COTS families remain post-MVP.
6. Integration tests prove the import path, the proxy geometry contract, the provenance contract, and the behavior contract.
7. Declared COTS parts that are part of the intended benchmark or solution design are actually instantiated into authored geometry, and declared-but-unused COTS parts fail the handoff or validation.
