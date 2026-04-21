# Agent handovers

## Scope summary

- Primary focus: deterministic handoff contracts between Planner, Coder, and Reviewer roles.
- Defines which files are handed over, what each artifact must contain, and when refusals are valid.
- Specifies routing behavior for review outcomes, replanning loops, and benchmark-to-engineer transition.
- Use this file to validate inter-agent boundary correctness.

## All handovers that happen

User prompt ->
Benchmark Planner -> Benchmark Plan Reviewer -> Benchmark Coder -> Benchmark Reviewer

Benchmark-side routing rules:

- `Benchmark Plan Reviewer` rejects planner handoff when the plan contains conflicting geometry, ambiguous/randomization-invalid benchmark definitions, or references to nonexistent benchmark objects across planner artifacts. Rejection routes back to `Benchmark Planner`.
- `Benchmark Coder` can refuse and route back to `Benchmark Planner` when the approved plan is infeasible to implement. Benchmark Coder refusal is valid only for plan infeasibility, not for generic coding failure.
- `Benchmark Reviewer` routes back to `Benchmark Coder` when the implemented environment CAD model does not adhere to the approved plan inventory, has invalid geometry such as intersections, violates the declared benchmark motion contract, or is unstable under benchmark simulation.

Benchmark Reviewer "accepts" and passes the environment to the Engineering Planner model. (indirect contact - no actual "communication")

Engineering Planner -> Engineering Plan Reviewer -> Engineering Coder -> Engineering Execution Reviewer

The Engineering Planner will try to think of the cheapest and most efficient, but *stable* approach of solving the environment given known constraints (objectives info, cost/weight info, geometry info, build zones).
Engineering Coder can refuse the plan if the plan was inappropriate, e.g. set too low price or the approach was inappropriate.
In this case, the Engineering Coder must provide `plan_refusal.md` (with role-specific reasons + evidence). The Engineering Plan Reviewer validates that refusal and either confirms (`CONFIRM_PLAN_REFUSAL`) and routes back to planner, or rejects (`REJECT_PLAN_REFUSAL`) and routes back to coding.

Reviewer outputs are made deterministic by persisting two YAML artifacts per review round: a routing-owned decision file and a structured comments/checklist file. The reviews and plans must be appropriate.

## Reviewer manifest naming contract

Reviewer handoff manifests are reviewer-scoped at gate boundaries.
There is no shared/canonical reviewer manifest file.
For engineering execution, the same file name is used both as the coder's
submission handoff and as the reviewer entry gate; that shared filename is
intentional.

Required manifest filenames:

1. Benchmark Plan Reviewer: `.manifests/benchmark_plan_review_manifest.json`
2. Benchmark Reviewer: `.manifests/benchmark_review_manifest.json`
3. Engineering Plan Reviewer: `.manifests/engineering_plan_review_manifest.json`
4. Engineering Execution Reviewer: `.manifests/engineering_execution_handoff_manifest.json`

Validation rule:

- Reviewer entry is blocked if the reviewer-specific manifest for that stage is missing, stale, or invalid for the latest revision.
- The stage-specific manifest must carry valid revision/session metadata and `reviewer_stage`; mismatch is a fail-closed handover error.
- Review-content validation and `plan_refusal.md` checks must run against the worker filesystem session (`metadata.worker_session_id` when present, otherwise `episode_id` fallback) to prevent cross-session artifact lookups.
- Benchmark review manifests record benchmark-neutral motion evidence verification, not benchmark-side goal completion. `goal_reached` remains engineer-owned.

## Current Role Manifest Contract

`.manifests/current_role.json` records the role that is currently running the
workspace node.
Backend workspace materialization writes the file before node entry and
rewrites it when the same workspace is handed to another node.
Node-entry validation compares the file against the node being entered and
fails closed on mismatch.
The file is backend-owned metadata under `.manifests/**`; agent roles do not
write it directly.

## Reviewer persistence naming contract

Reviewer outputs are persisted as reviewer-scoped YAML file pairs. We do not use shared review filenames or shared per-round folders. Local CLI-provider submission helpers may also accept a single markdown review document with YAML frontmatter, but routing still keys off the stage-scoped reviewer files.

Required reviewer file pairs:

1. Benchmark Plan Reviewer:
   - `reviews/benchmark-plan-review-decision-round-<n>.yaml`
   - `reviews/benchmark-plan-review-comments-round-<n>.yaml`
2. Benchmark Reviewer:
   - `reviews/benchmark-execution-review-decision-round-<n>.yaml`
   - `reviews/benchmark-execution-review-comments-round-<n>.yaml`
3. Engineering Plan Reviewer:
   - `reviews/engineering-plan-review-decision-round-<n>.yaml`
   - `reviews/engineering-plan-review-comments-round-<n>.yaml`
4. Engineering Execution Reviewer:
   - `reviews/engineering-execution-review-decision-round-<n>.yaml`
   - `reviews/engineering-execution-review-comments-round-<n>.yaml`

Validation rules:

- Reviewer output is invalid if the stage-specific decision file is missing for that reviewer/round.
- Reviewer output is invalid if the stage-specific comments/checklist file is missing for that reviewer/round.
- Routing is driven only by the decision YAML. The comments/checklist YAML is explanatory and evaluative, not the source of truth for branch transition.

## Structured schema strictness contract

All planner/reviewer machine-readable outputs are strict-schema artifacts by default.

Rules:

1. Unknown/extra fields are rejected at validation time for handoff artifacts and reviewer artifacts.
2. This rule applies recursively to nested objects inside those artifacts, not only to top-level keys.
3. Unknown/extra fields must fail closed (handoff/review is invalid and routing does not progress on that output).
4. Open-ended key/value sections are exception-only and must be explicitly modeled as open-ended in schema (for example, a dedicated metadata map). They are never implicitly accepted by parser defaults.
5. If a schema intentionally allows extras for a specific field/model, that exception must be explicit in code and documented in architecture/runtime notes.

## Inventory exactness contract

Planner handoff packages are binding inventories, not loose geometry hints.

Rules:

1. The planner-authored evidence script must preserve the same multiset of authored labels and quantities as the associated plan/YAML inventory.
2. Inventory equality is checked by label multiplicity, not by ordering. For identity-bearing rows, the label and identity travel together as one pair; validators must reject pair-swaps that preserve the separate label counts but assign them to different rows.
3. Repeated references in `final_assembly` count as quantity and must survive into the planner evidence script and downstream implementation.
4. The planner must self-validate this exactness before the role-scoped planner submission helper (`submit_benchmark_plan()` or `submit_engineering_plan()`, depending on graph); if the evidence script drifts, the handoff is invalid.
5. The coder and reviewer must compare the implemented model against the approved inventory and reject missing, extra, or relabeled items.
6. Every planner-declared inventory label and selected `part_id` must appear at least once in the stage-specific plan file as an exact identifier mention. Backticks are preferred for the first mention, but the exact string match is what matters for validation.

## Payload terminology contract

Payload naming is canonical across planner, coder, reviewer, and schema-facing architecture docs.

Rules:

1. The canonical term is `payload`.
2. Legacy names `moved_part`, `moving_part`, and `moved_object` are deprecated.
3. New specs, examples, and newly authored machine-readable artifacts must not introduce deprecated payload aliases.
4. Legacy aliases may exist only as temporary backwards-compatibility read paths during migration and must not be treated as the forward contract.

## Benchmark Planner and Benchmark Plan Reviewer

The Benchmark Generator Planner will submit multiple files to the CAD implementing agent.

The plan will have the following bullet points. The plan will be validated for consistency, and will not be accepted until the markdown passes strict formatting criteria, and will ensure that the bullet points are there:

1. `benchmark_plan.md`:
   - Learning objective (summary of what the agents needs to or will learn as a result of this challenge);
   - The geometry of the environment:
     - coordinates of all major shapes in the environment + randomization.
     - Geometry and coordinates of all moving parts:
       - motors
       - non-fixed parts.
   - Input objective:
     - Shape of the input (can be anything; the ball is the easiest, any more complex shape is more difficult to solve (however it's more interesting too))
       - how shape is randomized (shape of the input should be held more or less constant throughout the run). This is a bullet point list.
     - Central position and position randomization margins (e.g. x:50, y:80, z:20, x_variation: 20, y_variation: 20, z_variation: 10)
   - Where the input objective is located (coordinates + randomization),
   - Objectives location:
     - A "forbid" objectives as a set of approximate AABB coordinates,
     - A "goal" objective as a single AABB coordinate
       The agents' file must correspond to roughly the structure detailed above, with automatic checks in place.
2. A `todo.md` TODO list from the planner.
3. A draft of `benchmark_definition.yaml` with rough values filled in.
4. A draft of `benchmark_assembly_definition.yaml` with benchmark-owned fixture inventory and geometry. This is read-only handoff context for downstream engineer stages and must still be a schema-valid full `AssemblyDefinition` artifact.
5. `benchmark_plan_evidence_script.py`, the benchmark-owned build123d evidence script that makes the draft geometry legible as a sketch/previewable scene for the benchmark plan reviewers and downstream engineer intake.
6. An explicit `submit_benchmark_plan()` handoff action which persists `.manifests/benchmark_plan_review_manifest.json`.

<!-- Note: it may be interesting that the Coder could try a few "approaches" on how to reduce costs without actually editing CAD, and would get fast response for cost by just editing YAML. However, it will almost by definition deviate from the plan. -->

The agent must make sure that the geometric plan is valid, the input objective does not interfere with anything (and goal objectives are not obstruted), that there is proper randomization, etc., no object coincides with each other. `payload.material_id` is mandatory and must reference a known material from `manufacturing_config.yaml`; empty strings or invented material IDs are invalid planner handoff.
If the user provides explicit benchmark objective overrides (for example `max_unit_cost`, `max_weight`, `target_quantity`), the planner preserves them semantically in `benchmark_definition.yaml` and must not silently mutate those constraints. Runtime may backfill corresponding estimate fields only to keep the benchmark constraint contract internally consistent.

`Benchmark Plan Reviewer` gate requirements:

- Source of truth contract: benchmark planner handoff artifacts are `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, benchmark-owned `benchmark_assembly_definition.yaml`, and `benchmark_plan_evidence_script.py`. That script must preserve the benchmark inventory labels, repeated quantities, and selected component identities exactly. `benchmark_script.py` is created later by `Benchmark Coder` after plan approval.
- Reviewer-stage manifest: `.manifests/benchmark_plan_review_manifest.json`.
- Entry guard behavior:
  - Reject when the manifest is missing, stale for the latest planner revision, or schema-invalid.
  - Reject when planner artifacts mention benchmark objects, moving parts, joints, or zones that are not declared consistently across the planner handoff package.
  - Reject when `benchmark_plan_evidence_script.py` diverges from the declared benchmark inventory labels, quantities, or selected component identities.
  - Reject when `payload.material_id` is missing, empty, or not known to `manufacturing_config.yaml`, or when `benchmark_assembly_definition.yaml` is not a schema-valid full `AssemblyDefinition` artifact.
  - Reject when moving benchmark fixtures are missing motion-visible handoff data needed by engineering intake, such as actuation mode, axis/path or equivalent reference, motion limits or operating envelope, and whether the engineer may rely on the motion.
  - Reject when benchmark-side motion is impossible, unstable, non-deterministic, or cannot be reconstructed from the handoff artifacts and evidence.

<!-- Future work: if benchmark input arrives as STEP, infer candidate motion constraints from the source geometry before explicit benchmark handoff materialization. -->

- Review-stage behavior:
  - `Benchmark Plan Reviewer` is read-only with respect to planner-owned artifacts. It inspects, validates, and decides; it does not rewrite `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, or `benchmark_plan_evidence_script.py`.
- Approval effect:
  - Only an approved benchmark plan reviewer handoff is allowed to pause in `PLANNED` state and unblock `Benchmark Coder`.

`Benchmark Coder` owns all implementation changes to `benchmark_script.py` and helper implementation modules for the current revision. The benchmark planner's evidence script is read-only context for benchmark coder entry, and the coder must preserve the same benchmark inventory labels, repeated quantities, and selected component identities when materializing `benchmark_script.py`.

## Benchmark Generator with Engineer handover

The Engineer agent(s) (for whom the first point of access is Engineering Planner) have access to meshes and a exact reconstruction of the environment as a starting point to their build123d scene, however they can not modify/move it from their build123d scene. In fact, we validate for the fact that the engineer wouldn't move it or changed it (validating for changing it via hashing) - in both MJCF and build123d.

The benchmark-owned environment, benchmark input objects, benchmark objective markers, and benchmark-owned moving fixtures are read-only task fixtures. They are validation setup, not engineer-owned deliverables: they are validated for geometry correctness, placement, randomization, and valid component identifiers/runtime metadata as a valid problem instance for the engineering graph, but they are not validated for manufacturability or priced as manufactured outputs. They follow the benchmark motion contract when the benchmark contract explicitly says so. Manufacturability validation starts at engineer-planned manufactured parts and selected imported components only.

Benchmark-owned authored labels are part of that read-only contract too: `payload.label` and any top-level build123d object label in the benchmark handoff must be non-empty and stable, and runtime must not invent fallback labels when one is missing.

Additionally, the engineering agent will be supplied with render evidence when the current revision has explicitly generated renders. Treat that preview as stage-local scratch under `renders/current-episode/` while it is being authored, but only the persistent handoff bundles are promoted for downstream reuse. Benchmark handoff evidence lives under `renders/benchmark_renders/`, engineer planner handoff evidence lives under `renders/engineer_plan_renders/`, and final solution submission evidence lives under `renders/final_solution_submission_renders/`. Handover and submission collectors recurse through the selected persistent bucket directory, so nested render files and the bundle-local `render_manifest.json` survive the payload assembly step unchanged. `renders/current-episode/` is deleted at handoff and never enters the persisted bundle index. The exact role-level render consumption policy stays config-driven in `config/agents_config.yaml`, and the node-entry gate consumes `visual_inspection.entry_expects_render_buckets` as the exact persistent bucket set for the entered role.

These renders are not only passive assets in storage. Reviewer and other vision-using nodes must inspect existing render evidence through the dedicated media-inspection tool (`inspect_media(...)`) when visual evidence is required. When a fresh view needs to be materialized first, the same roles use `render_cad(...)` to generate it into `renders/current-episode/` and then inspect the result. For moving-solution reviews, `render_cad(..., payload_path=True)` may be used to materialize the finest available motion overlay into the scratch preview before inspection. Merely listing files in `renders/` or reading text artifacts that mention render paths is not treated as image review.

Each role's expected render state is defined by its `visual_inspection` policy in `config/agents_config.yaml`, including `visual_inspection.entry_expects_render_buckets`. Validation is fail-closed against that expected state: if a role policy expects render assets for the current node/revision, the workspace must contain the exact persistent buckets named by that list, each expected bundle must carry a valid bundle-local `render_manifest.json`, and the role must inspect them before completion or approval; if the role policy does not expect them, absence is correct.

#### Render input contract

- Benchmark Planner: the role policy defines whether render media are expected for the current node/revision; expected assets must exist and be inspected before completion.
- Benchmark Plan Reviewer: the role policy defines whether render media are expected for the current node/revision; expected assets must exist and be inspected before approval.
- Benchmark Coder: the role policy defines whether render media are expected for the current node/revision; expected assets must exist and be inspected before completion.
- Benchmark Reviewer: receives the latest benchmark render evidence for the approved revision, which includes any benchmark preview outputs under `renders/benchmark_renders/` and the latest simulation video when benchmark-owned motion exists.
- Engineering Planner: receives the same latest benchmark render evidence under `renders/benchmark_renders/` as read-only handoff context. Its own policy determines whether render evidence under `renders/engineer_plan_renders/` is also expected before completion.
- Engineering Coder: receives the same latest benchmark render evidence under `renders/benchmark_renders/`, the latest simulation video when benchmark-owned motion exists, and any engineer-owned inspection previews under `renders/engineer_plan_renders/` as read-only context. Its own policy determines which render evidence is expected before completion.
- Engineering Plan Reviewer: receives the benchmark render evidence under `renders/benchmark_renders/`, the engineer-plan evidence under `renders/engineer_plan_renders/`, the final solution submission evidence under `renders/final_solution_submission_renders/` when it exists, and any scratch renders under `renders/current-episode/` for the current review attempt; it is the only engineering role with read access to all three persistent render buckets. Its own policy determines which of those buckets are required for approval.
- Engineering Execution Reviewer: receives the same benchmark render evidence under `renders/benchmark_renders/` plus the latest final solution submission evidence under `renders/final_solution_submission_renders/` and the latest simulation video evidence when present, and must inspect the media its policy expects before approval.

The source of truth for which roles must perform visual inspection and which render buckets they expect is `config/agents_config.yaml` under each role's `visual_inspection` policy, specifically `visual_inspection.required` and `visual_inspection.entry_expects_render_buckets`. Current required roles in engineering/benchmark handoff flow are:

1. `benchmark_plan_reviewer`
2. `benchmark_reviewer`
3. `engineer_planner`
4. `engineer_coder`
5. `engineer_plan_reviewer`
6. `engineer_execution_reviewer`

The requirement is fail-closed against the render state expected for the current role and current node/revision. If the role policy expects render assets, the workspace must contain them and they must be inspected; if the role policy does not expect them, absence is correct.

The engineer will also receive YAML files with:
1\. Exact positions (boundaries) of objectives.
2\. "Runtime" randomization, i.e. the randomization of the starting positions this environment will use. Note that it's different from the "static" randomization which is stronger.
3\. Maximum prices and weight. Prices should be estimated by the planner to be relatively challenging but feasible by the planner (feasible but challenging related to *our* pricing sheet, as defined in planner.md). I suggest initially giving 50% safety margin in pricing and weight.
Note that the maximum price and weight are also set by the planner later internally. However, the planner sets their own constraints *under* the maximum price. Here the "maximum prices and weight" are a "customer-specified price and weight" (the "customer" being the benchmark generator), and the planner price and weight are their own price and weight.
    <!-- (in future work) Later on, we will challenge the agent to optimize its previous result. It would have to beat its own solution, by, say, 15%.  -->

The positions of objectives (including a build zone) and runtime randomization are in `benchmark_definition.yaml`. The Benchmark Planner's `benchmark_assembly_definition.yaml` is a required benchmark-owned handoff artifact copied into the engineer session as read-only context. The benchmark-owned assembly geometry is materialized in `benchmark_script.py` by `Benchmark Coder` after plan approval through `build()`, and preview callers compose that assembly output with the objective overlays reconstructed by the importable `utils.objectives_geometry()` helper from the `objectives` section of `benchmark_definition.yaml` before rendering benchmark context. The benchmark planner evidence script is copied into downstream engineer workspaces as read-only benchmark planning context.

Engineering may read `benchmark_assembly_definition.yaml`, reason about it, and design against it, but must not modify benchmark-owned fixtures or benchmark motion definitions. Missing `benchmark_assembly_definition.yaml` is a handoff failure, not an optional omission, and the file remains benchmark-owned read-only context rather than an engineer-owned planning artifact. `benchmark_script.py` and `benchmark_plan_evidence_script.py` are also read-only context for engineering intake once they exist.

If the benchmark includes moving benchmark-owned fixtures, the engineer intake still needs motion-visible facts. Those facts may live in `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml`. The minimum contract for each moving benchmark fixture is:

1. stable fixture identity,
2. motion profile,
3. motion kind (`fixed`, `passive`, `motorized_revolute`, `motorized_prismatic`, or other explicitly supported type),
4. motion axis or path reference, when applicable,
5. motion bounds, period, or controller-visible operating range,
6. whether the motion is always-on, conditional, or externally triggered,
7. whether the engineer may assume that the motion is available during solution execution.

If a benchmark-owned fixture is meant to be interactable by engineering, the relevant component must declare `allows_engineer_interaction: true`. Supported examples include:

1. plugging into a benchmark-owned PSU or power connector,
2. toggling a benchmark-owned switch or relay input,
3. inserting a part into a benchmark-owned slot, socket, rail, or guide,
4. mechanically actuating a benchmark-owned control feature such as a lever, latch, or trigger.

That flag is a permission, not transfer of ownership. The engineer may interact with the intended benchmark-owned surface, but may not redefine benchmark-owned components.

The benchmark-owned geometry source is created in `benchmark_script.py` by `Benchmark Coder` and is copied read-only into downstream engineer workspaces and benchmark execution review. The engineer-owned solution source lives in `solution_script.py`. Benchmark assembly geometry comes from `build()`, while the shared `utils.objectives_geometry()` helper reconstructs the objective overlays declared in the `objectives` section of `benchmark_definition.yaml`. Planner-authored evidence scripts are separate read-only inputs:

- benchmark side: `benchmark_plan_evidence_script.py`
- engineer side: `solution_plan_evidence_script.py`

#### Renders

These preview renders are static context artifacts. The default generation policy is:

1. render evidence is generated explicitly, not by `/benchmark/validate`,
2. that preview path uses the renderer worker's selected backend by default,
3. preview jobs may materialize multiple requested views in one bundle, but the
   caller still inspects the persisted files through `inspect_media(...)`,
4. the images are not a proof that Genesis runtime behavior was exercised during validation (intentionally so, as Genesis runtime behavior stays on the simulation path rather than the preview path),
5. Genesis parity is covered by dedicated backend parity tests and by actual Genesis simulation runs where Genesis behavior is required.

Reviewer evidence contract for renders:

1. If render assets exist for the latest revision, review stages that claim visual inspection must call the media-inspection tool on those assets.
2. The review decision must be attributable to the exact latest-revision render assets, not stale prior-run images.
3. Text summaries such as `simulation_result.json` complement but do not replace visual inspection where the review contract says images must be checked.
4. The required number of distinct images inspected is config-driven (`visual_inspection.min_images`); current production policy is `1`, but this must remain adjustable without code changes.
5. Runtime reminder messages may be injected during long-running tool loops when required visual inspection has not yet been satisfied; these reminders are deterministic policy enforcement, not free-form prompt advice.

For moving benchmarks, dynamic evidence is a separate requirement:

1. static preview images remain required context artifacts,
2. they are not sufficient evidence for benchmark-owned motion or powered fixture behavior,
3. benchmark approval for moving benchmarks requires latest-revision simulation evidence, normally video,
4. benchmark approval does not require benchmark-side goal completion,
5. the `Benchmark Reviewer` must inspect that dynamic evidence before approval when it exists.

### A benchmark is reused multiple times

Notably, the benchmarks are randomized and reused multiple times under different variations. The Engineering agent only receives a "runtime" randomization - (as in the list of the relevant heading) currently only a (relatively) small jitter in the environment.

### What if the benchmark (planner/coder) agent set the price too low?

For now, nothing. I'll filter it out via SQL or similar later and make a "price discussion" between agents - probably. Or a human-in-the-loop method. Anyway, this is a non-priority item for now.

## Engineer Planner and "Coder" interaction

Engineering handoff includes two review gates:

1. Planner gate (`Engineering Plan Reviewer`): validates planner artifacts before coder entry.
2. Execution gate (`Engineering Execution Reviewer`): validates latest implementation handoff after validation/simulation success.

Engineer sends the planner handoff files to the coder agent who has to implement the plan:

1. A `engineering_plan.md` file. `engineering_plan.md` is a structured document (much like the benchmark generator plan) outlining:
2. A stripped down `benchmark_definition.yaml` file, except the max price and weight are set by the planner now and remain under the benchmark/customer caps.
3. A `todo.md` TODO-list.
4. A `assembly_definition.yaml` file with per-part pricing inputs, `final_assembly` structure, assembly totals produced by `validate_costing_and_price.py`, and a planner-authored `motion_forecast` section for the engineering handoff. For Engineer Planner seed workspaces, this file must begin from the checked-in starter-template baseline before the planner rewrites it. That forecast describes the payload trajectory: it must start at the payload spawn position, name explicit `rot_deg` orientation on every anchor, end at the goal-zone center, and never climb above the spawn height. `motion_forecast` is the historical field name for the planner-owned coarse payload trajectory; in prose, `coarse_payload_trajectory` is the clearer alias for the same low-resolution contract.
   - `payload_part_names` is the exact list of payload solid labels covered by that coarse trajectory. A one-part payload still uses a one-item list, and the list must match the solid labels in the authored geometry, not a generic payload count.
5. A `payload_trajectory_definition.yaml` file. It is required for every engineer handoff, refines the coarse `motion_forecast` rather than replacing it, and must keep the same explicit-orientation contract, the same spawn-position start, the same goal-center finish, and the same spawn-height ceiling while proving swept clearance.
6. A `solution_plan_evidence_script.py` file that captures the build123d planning evidence for the proposed solution geometry.

The planner forecast in `assembly_definition.yaml` is intentionally coarse and config-driven, while the engineer-coder must materialize `payload_trajectory_definition.yaml` during implementation for backend-specific precision. The engineer-planner handoff also runs the swept-clearance checker against the approved coarse payload trajectory so the coarse path is reviewed before coder refinement. The coder-owned precise path must remain consistent with the approved coarse forecast, including the same moving parts and a denser cadence that does not loosen the approved endpoint proof. That coarse forecast is retained; the publication prune only removes the technical-drawing companion scripts and preview rendering.
This planner-evidence and payload-path contract remains in force even though the publication prune removes the separate technical-drawing companion scripts and preview rendering.

Planner gate requirements (`Engineering Plan Reviewer` / coder entry contract):

- Source of truth contract: `ENGINEER_PLANNER_HANDOFF_ARTIFACTS` in node-entry validation.
- Required artifacts: `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `solution_plan_evidence_script.py`
- Those planner-authored scripts must preserve the same labels, repeated quantities, and selected component identities as the approved inventory, and the planner must self-validate that exactness before `submit_benchmark_plan()`.
- Engineering handoffs must carry a reviewable `motion_forecast` section with ordered world-frame anchors, explicit `rot_deg` pose data, a build-zone-valid first anchor, an explicit goal-zone terminal proof, tolerance bands, and first-contact order.
- Reviewer-stage manifest: `.manifests/engineering_plan_review_manifest.json` (planner handoff materialization for the plan-review stage)
- Entry guard behavior:
  - Reject when the manifest is missing, stale for the latest planner revision, or schema-invalid.
  - Use node-entry validation with an engineering-plan-review custom check (parity with execution-review stale-revision checks).
- For seeded/direct starts, the controller-owned node-entry validation layer must schema-validate all present schema-backed handoff artifacts in the workspace (not only required-file presence) and fail closed on any typed-parse/contract error.
- For planner submission/review handoffs, the controller validation path must also run the corresponding planner cross-contract semantic checks before approval (engineering: `benchmark_definition.yaml` + `assembly_definition.yaml` attachment/cost checks plus planner handoff inventory consistency; benchmark: benchmark planner handoff semantic checks plus benchmark handoff inventory consistency).
- For seeded/direct starts in any seed-backed row with writable authored files, the controller validation path must also confirm that the writable starter files for that agent still match the checked-in starter template baseline rather than a pre-solved output; for Engineer Planner, that baseline includes `assembly_definition.yaml`.
- Evals may trigger seeded preflight, but they must call the controller validation path instead of re-implementing schema/handoff logic inside eval modules.
- Plan reviewer responsibilities:
  - Reject unsupported/invented system components or mechanisms.
  - Reject inconsistent, infeasible, ambiguous, or incomplete plans, including planner evidence scripts that drift from the approved label/quantity/component-identity inventory.
  - Reject missing, contradictory, or unsupported motion forecasts; motion must be explicit and reconstructable from the handoff artifacts, not minimized for convenience.
  - Re-run `.agents/skills/manufacturing-knowledge/scripts/validate_and_price.py` (or equivalent wrapped validator tool) and reject on pricing/weight/schema mismatch.
  - Keep cost/weight target scrutiny as a mandatory realism check.
  - Optional future work: propose weight/cost optimization opportunities.

Unified coder contract:

- `Engineering Coder` reads the combined planner handoff, including any planner-owned `assembly_definition.yaml` sections, benchmark `benchmark_definition.yaml`, read-only benchmark geometry context from `benchmark_script.py`, read-only benchmark evidence context from `benchmark_plan_evidence_script.py`, and read-only planner evidence context from `solution_plan_evidence_script.py`.
- `Engineering Coder` owns all implementation changes to `solution_script.py` and helper implementation modules for the current revision.

### `engineering_plan.md` structure for the engineering plan

```markdown
# Engineering Plan
## 1. Solution Overview
A brief description of the approach to solve the benchmark objective (e.g., "A gravity-fed ramp with a deflector plate to redirect the ball into the goal bin").
## 2. Parts List
For each part:
- **Part name**: e.g., `ramp_main`
- **Function**: What role it plays
- **Geometry**: An overview of geometry
    - **Mating points** with other connectors (list)
- **Manufacturing method**: CNC / Injection Molding / 3D Print
- **Material**: e.g., `aluminum-6061`, `abs-plastic`
- **Estimated dimensions**: Rough sizing
## 3. Assembly Strategy
- How parts connect
- Mounting points to environment
<!-- - Order of assembly --> 
<!-- Order of assembly is partially unnecessary because we kind of work in CAD. However, it's a good thing to think of. -->
## 4. Assumption Register
- Stable assumption IDs such as `ASSUMP-001`, `ASSUMP-002`, etc.
- Non-obvious inputs and their sources, such as friction coefficient, motor stall torque, gearbox efficiency, cable drop, or safety factor.
- Each assumption should state what calculation or constraint depends on it.
## 5. Detailed Calculations
- The section starts with a compact index table whose columns are `ID`, `Problem / Decision`, `Result`, and `Impact`.
- Each index row must map to a matching `### CALC-001: <short title>` subsection below; the `CALC-*` heading is required, not optional.
- The CALC subsections must stay in the same order as the summary-table rows. If the headings are shuffled but still complete, validation fails with an explicit order-mismatch error rather than a generic missing-heading message.
- Each calculation subsection should include a problem statement, assumptions, derivation, worst-case check, result, design impact, and cross-reference.
- For geometry-, volume-, weight-, or shape-derived claims, a short reproducible `build123d` script or CAD probe may provide the derivation; include the script or probe reference and the resulting numeric value in the subsection.
## 6. Critical Constraints / Operating Envelope
- Derived numeric limits that the mechanism must satisfy, such as minimum slope, maximum torque, minimum current, or clearance bounds.
- Each derived limit should be traceable back to one or more calculation IDs.
- The operating envelope is the distilled output of the detailed calculations.
## 7. Cost & Weight Budget
- `max_unit_cost`: $X (from benchmark_definition.yaml, planner's allocation)
- `max_weight`: Y kg
- Assembly breakdown per part
## 8. Risk Assessment
- Potential failure modes (e.g., "ball bounces off ramp edge")
- Mitigations for each risk
- Runtime randomization considerations (position jitter handling)
<!-- ## 6. Build123d Strategy
- CSG vs sketch-based approach
- Key operations (fillets, chamfers, patterns)
- Reference skills to consult -->
<!-- Note: the planner explicitly doesn't specify the CAD approach. It doesn't need to think about plans, it's about the geometry. -->
```

The Assumption Register captures the source-backed inputs that make the plan auditable. The Detailed Calculations section proves the binding numeric claims by pairing an index table with matching `CALC-*` subsections. The Critical Constraints / Operating Envelope section distills those proofs into reviewable pass/fail limits that the budget and drawing intent must respect.

### `benchmark_definition.yaml`

`benchmark_definition.yaml` is a central data exchange object to the system. To centralize its structure:

```yaml
# =============================================================================
# BENCHMARK_DEFINITION.YAML - Your Task Definition
# =============================================================================
# This file defines WHAT you must achieve and which benchmark-owned fixtures
# and metadata are part of the task. Read it carefully before planning.
#
# YOUR MISSION: Guide the `payload` into the `goal_zone` while:
#   1. Staying WITHIN the `build_zone` (you cannot build outside it)
#   2. AVOIDING all `forbid_zones` (contact = failure)
#   3. Respecting runtime-derived `max_unit_cost` and `max_weight` caps
#
# Benchmark-owned environment geometry and metadata in this file are READ-ONLY.
# Engineering assembly motion metadata is stored under engineering
# assembly_definition.yaml final_assembly.parts and is also READ-ONLY once
# written.
# =============================================================================

objectives:
  # SUCCESS: The payload center enters this volume
  goal_zone:
    min: [x_min, y_min, z_min]
    max: [x_max, y_max, z_max]

  # FAILURE: Any contact with these volumes fails the simulation
  forbid_zones:
    - name: "obstacle_collision_zone"
      min: [x1, y1, z1]
      max: [x2, y2, z2]
    # Additional forbid zones may be listed here

  # CONSTRAINT: Your entire design MUST fit within these bounds
  # Parts placed outside will fail validation
  build_zone:
    min: [x, y, z]
    max: [x, y, z]

benchmark_parts:
  - part_id: "environment_fixture"
    label: "environment_fixture"
    metadata:
      fixed: true
      material_id: "aluminum_6061"
# Hard simulation boundaries - objects leaving this volume = failure
simulation_bounds:
  min: [-50, -50, 0]
  max: [50, 50, 100]

# -----------------------------------------------------------------------------
# THE OBJECT YOU MUST DELIVER
# -----------------------------------------------------------------------------
# This object spawns at `start_position` (with runtime jitter applied).
# Your design must reliably guide it to the goal_zone.
payload:
  label: "projectile_ball"
  shape: "sphere"
  material_id: "abs"
  # Static randomization: shape varies between benchmark runs
  static_randomization:
    radius: [5, 10]  # [min, max] - actual value chosen per benchmark variant
  start_position: [x, y, z]
  # Runtime jitter: small position variation per simulation run
  # Your solution must handle ALL positions within this range
  runtime_jitter: [2, 2, 1]  # [±x, ±y, ±z] mm

# -----------------------------------------------------------------------------
# YOUR CONSTRAINTS
# -----------------------------------------------------------------------------
# Benchmark planner authors realistic estimate fields.
# Runtime derives max caps as `1.5x` those estimates during `submit_engineering_plan()`.
constraints:
  estimated_solution_cost_usd: 33.33
  estimated_solution_weight_g: 800.0

# Randomization metadata (for reproducibility)
randomization:
  static_variation_id: "v1.2"  # Which static variant this is
  runtime_jitter_enabled: true
```

`benchmark_definition.yaml` ownership rules:

1. It owns benchmark/task geometry, randomization, benchmark/customer caps, benchmark planner estimates, and benchmark-owned fixture metadata.
2. `benchmark_parts[].metadata` is benchmark-side metadata only. It describes read-only benchmark fixtures such as `fixed`, `material_id`, and `part_id`.
   - Benchmark-owned fixtures remain read-only context for engineering intake.
   - The benchmark planner may describe fixture motion visibility and evidence needs, but not engineer-owned manufacturability details.
3. It does not own engineer solution metadata, part costing inputs, or engineer motion/control metadata.
4. Engineer solution metadata stays in `assembly_definition.yaml` and runtime CAD `.metadata`.
5. `payload.material_id` is mandatory and must be a known material ID from `manufacturing_config.yaml`, and for benchmark-planner handoff `constraints.estimated_solution_cost_usd` and `constraints.estimated_solution_weight_g` are planner-authored while runtime derives `max_unit_cost` and `max_weight_g` from those estimates during `submit_benchmark_plan()`.

<!-- Note: we are using metric units and degrees. -->

### `assembly_definition.yaml`

To reduce cost guessing, the Engineering Planner outputs a machine-readable estimate file that also serves as an assembly plan: it captures all pricing inputs per part plus the assembly structure used to derive quantities and reuse.

Expected flow:

1. Planner drafts entries for all planned manufactured parts and imported components.
2. Planner defines `final_assembly` (subassemblies, part membership, and joints); under the hood we:
   - Calculate as much as possible to prevent the planner from needing to think (e.g.: cooling time in injection molding is autocalculated from wall thickness, 3d print time is autocalculated from volume, setup time is autocalculated etc.)
   - Estimate part reuse - if the part/subassembly is reused, unit costs go down as per manufacturing rules (making 2 equal parts is cheaper than making 1 due to economics of scale).
3. Planner runs `.agents/skills/manufacturing-knowledge/scripts/validate_and_price.py`.
   - The script is the canonical calculator for `assembly_definition.yaml`: it validates schema consistency, computes assembly totals to cent precision, and writes normalized numeric totals back into the workspace file.
   - The planner does not hand-author the final aggregate cost/weight values; those values come from the script output.
4. If totals exceed `max_unit_cost` (or other numeric constraints), or if node-entry revalidation does not reproduce the same cent-precision totals exactly, planner must re-plan before handoff.
5. Planner may restate the validated totals in prose, but the written YAML totals remain the source of truth and must match the script output exactly on node entry.
6. The approved planner handoff is a binding inventory for the implemented solution. The Engineering Coder must realize the same planner-declared manufactured-part and component inventory as a multiset: labels and quantities must match, including repeated references in `final_assembly`.
7. Declared imported components are not advisory. Declared component `part_id`s, labels, and quantities must be instantiated in authored geometry with the same counts; missing, extra, relabeled, or pair-swapped components are handoff failures, even if the solution still solves the task.
8. Internal construction details may change only when the approved inventory and drawing intent remain unchanged.

Minimum per-manufactured-part fields:

- `part_name`, `part_id`, `description`, `manufacturing_method`, `material_id`
- `part_volume_mm3`
- method-specific costing inputs:
  - CNC: `stock_bbox_mm`, `stock_volume_mm3`, `removed_volume_mm3`
  - Injection molding / 3D print: required process-specific volume/thickness/time fields per validator contract

<!-- - `estimated_unit_cost_usd` - auto-calculated. The planner does not need to calculate each. However, it may be populated automatically by the script if it runs successfully? Again, the goal is to offload agent work and guessing (for performance reasons). -->

- \`pricing_notes <!-- User review - maybe. Maybe for "confidence" scores or similar. -->

Minimum per-component fields:

- `part_id`, `manufacturer`, `unit_cost_usd`, `source`

Note: I will restate: any field that can be autopopulated is autopopulated. E.g. here the mandatory fields are only `part_id`, `manufacturer`, `source`, the `price` can be pulled from DB (errors are not triggered during validation too, however if it mismatches, the fields must be overwritten and the right price used.)
Final cost and weight totals are never LLM-authored; they are derived by script, rounded to cents, persisted, and rejected on node entry if the persisted values drift from the deterministic calculation.

Required assembly fields:

- `final_assembly` containing subassemblies/parts/joints
- repeated part references are allowed and used by pricing logic to compute quantity effects

```yaml
version: "1.0"
units: #pre-populated in template.
  length: "mm"
  volume: "mm3"
  mass: "g"
  currency: "USD"
# constraints: # user review - no, unit constraints are written in benchmark_definition.yaml. 
#   benchmark_max_unit_cost_usd: 50.0
#   benchmark_max_weight_kg: 1.2
#   planner_target_max_unit_cost_usd: 34.0
#   planner_target_max_weight_kg: 0.9
manufactured_parts:
  - part_name: "ramp_main"
    part_id: "ramp_main_v1"
    description: "Primary sloped ramp for ball redirection"
    manufacturing_method: "CNC"
    material_id: "aluminum-6061"
    part_volume_mm3: 182340.0
    stock_bbox_mm: {x: 220.0, y: 120.0, z: 12.0}
    stock_volume_mm3: 316800.0
    # removed_volume_mm3: 134460.0 # no need to calculate, have script calculate it.
    estimated_unit_cost_usd: 18.70 # estimated automatically
    pricing_notes: "3-axis; no undercuts"
  - part_name: "guide_clip"
    part_id: "guide_clip_v1"
    description: "Guide clip holding edge trajectory"
    manufacturing_method: "INJECTION_MOLDING"
    material_id: "abs-plastic"
    part_volume_mm3: 24100.0
    wall_thickness_mm: 2.0
    cooling_time_s_estimate: 11.0
    estimated_unit_cost_usd: 0.82
    pricing_notes: "tooling amortized at target quantity"
final_assembly:
  - subassembly_id: "frame_and_ramp"
    parts:
      - name: "ramp_main_v1"
        config: {}
      - name: "guide_clip_v1"
        config: {}
      - name: "guide_clip_v1"
        config: {}
      - name: "feeder_motor_env_v1"
        config: {}
      - name: "passive_slider_env_v1"
        config: {}
    joints:
      - joint_id: "j1"
        parts: ["ramp_main_v1", "guide_clip_v1"]
        type: "rigid_joint"
totals:
  estimated_unit_cost_usd: 31.46
  estimated_weight_g: 742.0
  estimate_confidence: "medium"
```

Validation requirement:

- Submission is blocked if `assembly_definition.yaml` is missing, malformed, still template-like, fails `validate_costing_and_price.py`, or contains non-numeric values for required numeric fields (doesn't match schema in general)

## Coder and Execution Reviewer interaction

The Execution Reviewer (`Engineering Execution Reviewer`) is a post-validation/post-simulation stage.

1. Entry is blocked unless latest-revision reviewer handoff artifacts are valid (`solution_script.py`, `validation_results.json`, `simulation_result.json`, `.manifests/engineering_execution_handoff_manifest.json`).
   - Source of truth contracts: `REVIEWER_HANDOFF_ARTIFACTS` + execution-review custom handover check in node-entry validation (using reviewer-scoped manifest filenames from this document).
2. The Execution Reviewer has read-only access to implementation and evidence files, plus write/edit only to its stage-specific YAML review pair in `reviews/`.
3. Primary review is robustness and realism: this node runs only after validation + simulation success paths have completed (including minor runtime-randomization pass criteria), then verifies the result is not flaky and is likely repeatable.
4. Verify execution follows the approved plan or clearly justified deltas, including planned motion details.
5. Optional code-quality review is secondary and should only block for concrete correctness/safety risks.

The goal is to persist reviews into stage-specific YAML artifacts that agents can reference in later rounds, without routing free-form review text through in-memory-only state.

Notably the Engineer will at this point already have passed the manufacturability constraint, cost constraint, and others.

<!-- and others - I need to ideate/remember what else it should review for.  -->

The review artifact pair is strictly typed.

The decision YAML is minimal and routing-owned:

```yaml
reviewer_stage: engineering_execution
round: 2
reviewed_revision_id: rev_0021
decision: REJECT_CODE # [APPROVED, REJECTED, REJECT_PLAN, REJECT_CODE, CONFIRM_PLAN_REFUSAL, REJECT_PLAN_REFUSAL]
reason_codes:
  - robustness
confidence: high
```

The comments YAML is structured and reviewer-authored:

```yaml
summary: >
  The implementation passes a single run but is not robust enough for approval.
checklist:
  latest_revision_verified: pass
  validation_success: pass
  simulation_success: pass
  visual_evidence_checked: pass
  dynamic_evidence_checked: pass
  plan_fidelity: pass
  robustness: fail
  cost_weight_compliance: pass
  manufacturability_compliance: pass
comments:
  - "Fails robustness requirement under jitter."
  - "Introduces motion not present in the approved plan."
required_fixes:
  - "Increase robustness under runtime jitter."
  - "Resolve the motion mismatch or request replanning."
```

Checklist values are typed as `pass | fail | not_applicable`.

Checklist keys are reviewer-stage-specific:

1. Plan reviewers use planning keys such as `cross_artifact_consistency`, `feasible_mechanism`, and `budget_realism`.
2. Execution reviewers use implementation keys such as `latest_revision_verified`, `simulation_success`, `plan_fidelity`, `robustness`, and `dynamic_evidence_checked`.
3. The checklist keys are canonical and schema-owned. They replace ad hoc issue identifiers for current reviewer evals.

## Clarification - definition of constraints in planning

1. Constraints are set first at the application level; e.g. the timeout of simulation is always 30 seconds
2. Then the Benchmark Planner/Benchmark Coder set a more realistic constraint for them (e.g., they set a max cost, max weight for the simulation, similarly to how a "customer" would do it for an engineering company)
3. Engineering Planner can set an even lower constraint to force Engineering Coder to think on how to achieve a certain goal cost-effectively. Engineering Coder won't pass the cost metric until it is done.

## Clarification: agents outputs will *never* be parsed via text heuristics.

Code is not to fall back to heuristic text parsing from agents; except of tools.

If the agent is to record structured output or an enum, it'll record it in the typed YAML artifacts above.

## Agents hard fail cases

The agents will fail on the following cases:

1. Timeout (configurable per agent, mostly 300s)
2. Max turns reached (for example, 150 turns (realistic with modern LLMs))
3. Exceeded some credits usage (e.g. 400k tokens input and output).
4. LLM loop-detection guard triggered:
   - If the same normalized failure fingerprint repeats for `N` consecutive retries, fail the stage.
   - Fingerprint is based on exception class/message plus latest LM output preview (or empty preview).
   - This guard is local to the node runtime and does not depend on DB episode counters, so local/CLI runs also terminate deterministically.

The user is able to have the agent continue for another number of turns.

All settings are configurable per-agent in @config/agents_config.yaml and should be rather permissive.

## LLM retries vs tool-call system retries

Clarification: LM generation retries and system tool-call retries are separate policies.

1. LM generation may continue until LM hard-fail limits are reached (turn budget, token budget, timeout, loop-detection guard).
2. Agent-failed tool errors are surfaced to the LM as observations; the LM may continue trying within LM hard-fail limits.
3. System-failed tool execution retries are capped at 3 attempts for the same tool request in the same stage.
4. System-failed retries do not consume LM tool-call budget, but do consume episode wall-clock time.
5. Repeated identical failures still fail closed via loop-detection and hard-fail guards; no infinite spin is allowed.

## Hard constraints on Agent output

We should give agents less chances to fail (our) system, and fail the execution of our tasks.
While we don't enforce strict Pydantic schemas, we effectively validate all inputs as such.

E.g., if a part doesn't have a `material` custom property on it, we fail the script; we don't substitute to a default Aluminum.
