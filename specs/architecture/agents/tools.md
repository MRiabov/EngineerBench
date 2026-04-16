# Agent tools (ReAct and python importable functions)

## Scope summary

- Primary focus: the tool surfaces available to agent runtimes and Python-side execution helpers.
- Defines DSPy-native tool calling, filesystem permission expectations, and planner/reviewer submission utilities.
- Use this file when changing agent-accessible tools, validation hooks, or handoff gate functions.
- Helper surfaces that are real but intentionally secondary or experimental live in [auxiliary-agent-tools.md](./auxiliary-agent-tools.md). Keep this file focused on the core agent tool contract.

## "Agent-native" tools (callable by DSPy.ReAct runtime)

We use standard DSPy/LiteLLM *native* tool calls, as defined in the following snippet:

```py
import dspy

# Define your tools as functions
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    # In a real implementation, this would call a weather API
    return f"The weather in {city} is sunny and 75°F"

def search_web(query: str) -> str:
    """Search the web for information."""
    # In a real implementation, this would call a search API
    return f"Search results for '{query}': [relevant information...]"

# Create a ReAct agent
react_agent = dspy.ReAct(
    signature="question -> answer",
    tools=[get_weather, search_web],
    max_iters=5
)

# Use the agent
result = react_agent(question="What's the weather like in Tokyo?")
print(result.answer)
print("Tool calls made:", result.trajectory)
```

(from: https://dspy.ai/learn/programming/tools/)

We allow DSPy and LiteLLM do all manipulations over said files.
In the end, the models will write `write_file` and not `next_tool_write_file` or whatever.

### DSPy adapter preference for tool-calling nodes

For DSPy ReAct nodes in this architecture:

1. Use `dspy.ChatAdapter` by default.
2. Prefer `ChatAdapter` over `JSONAdapter` as the standard runtime setting.
3. Use `JSONAdapter` only for explicitly scoped cases where strict whole-response JSON is required and cannot be enforced by downstream validators/parsers.
4. Adapter choice is part of node runtime configuration and should be observable (logged in trace metadata).
5. Do not add permissive fallback logic from `ChatAdapter` failures to `JSONAdapter` (or vice versa) inside a run; treat adapter/runtime mismatch as a deterministic error and route fail-closed.

## Filesystem permissions

Actual read/write/edit access is enforced per-role via `config/agents_config.yaml` path rules. A tool call targeting a forbidden path is rejected by policy (deterministic permission error).

The canonical workspace contract uses workspace-relative paths. `/workspace` aliasing may still exist in runtime plumbing as a compatibility fallback, but it is not the preferred API contract; see `architecture/agents/agent-harness.md` for the rationale and cleanup intent.

There is a mechanism for privileged filesystem-policy bypass, which is explicitly system-only and requires both:

1. Request payload field `bypass_agent_permissions=true`.
2. HTTP header `X-System-FS-Bypass: 1`.

Header-only or payload-only requests remain policy-enforced (no bypass).
This is mostly for integration tests where such bypass is convenient (for system access, why not just access directly?).

## Tool definitions

- `execute_command` Execute a terminal shell command in the session workspace and return stdout/stderr/exit status.
- `list_files` Structured listing with file metadata.
- `read_file` Read UTF-8 text file content.
- `write_file` Create or overwrite a file.
  Reviewer roles use this same tool, but filesystem permissions narrow it to the stage-owned review paths.
- `edit_file` Edit a file by replacing string occurrences.
- `grep` Structured text search.
- `inspect_media` Read visual evidence (`.png`, `.jpg`, `.jpeg`, and supported video frame bundles) and attach it to the model as media input for the current tool step.
- `inspect_topology` Inspect assembly/topology metadata.
- `submit_benchmark_plan` Validate and submit benchmark planner handoff artifacts.
- `submit_engineering_plan` Validate and submit engineering planner handoff artifacts.
- `save_suggested_skill` Persist skill-agent suggested skill output.

Importantly, we have all these methods as async functions, their names with `aread`, `awrite`, `aedit`, etc. This is likely the preferred way to call all these functions.

`execute_command` is a shell-command tool. The agent contract is terminal execution from the session workspace root, not a raw-Python special case.

Rules:

1. The command string is interpreted as a shell command, exactly as an agent would type it in a terminal.
2. Workspace-relative paths such as `solution_script.py`, `benchmark_script.py` once created by `Benchmark Coder`, `benchmark_plan.md`, `engineering_plan.md`, and `renders/` remain the canonical path contract inside that shell session.
3. Shell usage such as `python -c ...`, `python solution_script.py`, `python benchmark_script.py` once created by `Benchmark Coder`, `bash -lc ...`, `uv run ...`, `ls`, `cat`, and similar terminal invocations is valid if it stays within filesystem policy.
4. Any implementation that accepts only raw Python source for `execute_command(...)` is a runtime bug or temporary drift, not the intended architecture contract.
5. If we want a raw-Python helper in the future, it should be a separate tool with a separate name and spec, not an overload of `execute_command(...)`.

### Shell-script bridge for missing tools

When the architecture needs a command-like capability but does not expose it as a native tool call, the repo exposes that capability as a checked-in `.sh` script instead. That shell-script bridge is the canonical surface for custom command-like behavior, not ad hoc pseudo-tools in prompts and not newly invented ReAct tool endpoints.

The shell script is the canonical command surface for that capability.
It preserves the same runtime intent as a direct tool call, but it keeps the contract visible in the repository and callable from the workspace shell.
Reviewer submission and planner/coder submission both use this shell-script pattern when a role needs an explicit command-like completion gate.
For planner roles, the local bridges are `scripts/submit_benchmark_plan.sh` and `scripts/submit_engineering_plan.sh`.
For coder review submission, the local bridges are `scripts/submit_benchmark_for_review.sh` and `scripts/submit_solution_for_review.sh`.
For reviewer roles, the local bridge is `scripts/submit_review.sh`.
Prompts may also reference the underlying Python utilities (`utils.submission.submit_benchmark_plan(...)`, `utils.submission.submit_engineering_plan(...)`, `utils.submission.submit_benchmark_for_review(...)`, and `utils.submission.submit_solution_for_review(...)`) as alternative completion paths when a supporting script is clearer for the role; the shell bridge remains the default command-like surface.
These submission bridges read `.manifests/current_role.json` to decide which stage contract is active; they do not infer role from `AGENT_NAME` or workspace file shape.

Input handling follows a simple split:

1. Short inputs use handles, IDs, or other compact scalar tokens.
2. Larger inputs use file references, typically a YAML or JSON file already materialized in the workspace.
3. YAML submission payloads are passed by path, not inlined as long command arguments.
4. The script validates the referenced file content itself and returns deterministic exit status plus machine-readable stdout/stderr when needed.
5. This bridge is the intended replacement for inventing pseudo-tools in prompt text when the runtime does not have a direct callable tool for the capability.

`read_file` is a text-only contract. It must not be overloaded to return image bytes, base64 blobs, or multimodal payloads for binary assets. Agents that need model-attached visual evidence must use `inspect_media(...)` instead. If a binary/media path is passed to `read_file`, runtime should fail closed with a deterministic error.

The rest (submitting the work, testing for design validity, etc) is called via and calling python functions in the code. (as described below)

Note: runtime is DSPy.ReAct-first with LangGraph-managed architecture. We do not use LangChain `create_agent`; orchestration is implemented in our LangGraph workflows and Python runtime wrappers. However, we *do* use native tool calls. We do *not* have tool calls as python objects, they are simply functions with a signature passed into DSPy as in the code snippet above.

ReAct is the first-line correction loop:

1. The model produces output and calls tools.
2. If a tool/validation response is not acceptable, ReAct continues the same node loop and retries.
3. The agent converges on valid handoff output or exits due to hard limits (timeout/turn budget/token budget).

Native completion-call naming contract:

1. Native tool-loop reviewer nodes terminate by writing the stage-owned review artifacts with `write_file` and then running `bash scripts/submit_review.sh` exactly once.
2. Native tool-loop non-reviewer nodes terminate by calling `finish(...)` exactly once with required signature output fields.
3. Planner nodes still require `submit_benchmark_plan()` or `submit_engineering_plan()` success before their final completion call.

### Config-driven anti-stall reminder policy

For native tool-loop nodes, if the model produces more than 5 consecutive no-tool turns, runtime injects a configured nudge telling it to stop narrating and actually act.

### The "tools" as Python functions - Utils

For submission scripts, the canonical import surface is a top-level `utils` package exposed in the runtime environment. Agent code should import helper functions and metadata types from that package, not from `shared.*` implementation paths.

Canonical submission-script imports:

```py
from utils.submission import (
    validate_benchmark,
    simulate_benchmark,
    submit_benchmark_for_review,
    validate_engineering,
    simulate_engineering,
    submit_solution_for_review,
)
from utils.metadata import PartMetadata, CompoundMetadata
```

`shared.utils.agent` and `shared.models.schemas` remain implementation modules inside the repo, but they are no longer the agent-facing contract. If runtime internals still route through those paths, that is compatibility plumbing rather than the intended submission script API.

I propose the following set of tools (their usage is below). Notably, the tools are python imports and functions, called right in one of the edited files!

#### Engineering tools

- `validate_and_price(component: Part|Compound) -> float|dict[str, float]`: validates a part by for manufacturability, then prices it if valid using its workbench's cost calculation interface, or returns an error with a description and a location
- `simulate_engineering(Compound) -> SimulationResult` - Submits a model for a simulation. Robustness checking uses runtime randomization by executing one heavy-worker job with one backend scene build/load and `num_scenes` parallel jittered scene instances inside that one backend run. `num_scenes` is batch width, not permission for serialized whole-scene reruns or multiple heavy jobs on one worker; nor multithreaded implementation - only batch width.

<!-- dev note: assert against submitting a BuildPart builders, or other types. -->

<!-- should it contain its environment model or only the generated model?  -->

- `submit_solution_for_review(Compound)` - submits the whole assembly for a review to `Reviewer` agent node, which can later approve it and submit return the final design to the user.

<!-- Same: what's in the compound? -->

- `render_cad(component: Part|Compound, orbit_pitch: float|list[float] = 45.0, orbit_yaw: float|list[float] = 45.0, rgb: bool = True, depth: bool = True, segmentation: bool = False, payload_path: bool = False) -> PreviewJobAck` - async on-demand preview submission for benchmark, engineer, and reviewer nodes. The runtime normalizes scalar camera inputs to lists, zip-pairs views by index, enforces the 64-view cap, and streams queued/view-ready/completed status over the worker-light control path while `worker-renderer` materializes the images into `renders/current-episode/`. When `payload_path=True`, the render bundle also includes a static payload-path overlay rendered from the finest available payload-trajectory artifact for the current workflow, using engineer-coder `payload_trajectory_definition.yaml` for engineering workflows and benchmark motion evidence for benchmark workflows. The helper returns a structured job ack; controller/API-backed multimodal runs use `inspect_media(...)` to view the resulting images. Benchmark callers compose benchmark `build()` output with objective overlays from `utils.objectives_geometry()` before previewing benchmark context.
- `objectives_geometry()` - a zero-argument utility re-exported by the public `utils` package, alongside `render_cad()` and `validate_benchmark()`, that reconstructs the benchmark objective overlay geometry from the `objectives` section of the canonical `benchmark_definition.yaml` path for the current workspace. It is shared runtime utility, not agent-authored geometry code. Preview callers combine its output with benchmark `build()` output before rendering benchmark context.

#### Reviewer / media-inspection tool

- `inspect_media(path: str) -> dict` is the explicit visual-evidence tool.
  - Controller/API-backed multimodal runs use it to attach images/video-derived frames back into the model.
  - CLI-provider-backed agents do not need `inspect_media(...)` to inspect local workspace image files.
  - It is the only agent-facing tool allowed to feed images/video-derived frames back into the model.
  - Supported first-line inputs are image files (`.png`, `.jpg`, `.jpeg`).
  - For videos such as `simulation.mp4`, runtime may expose representative extracted frames through the same tool contract when `config/agents_config.yaml render.split_video_renders_to_images=true`. Frame cadence is controlled by `render.video_frame_attachment_stride`, so the tool attaches every Nth frame rather than a fixed cap. That remains a media-inspection action, not a text-file read.
  - The tool returns structured metadata (for example path, media kind, frame/image count, attach success), while the actual image/frame content is attached to the LLM call through the runtime's multimodal message path.
  - When the inspected file is a render artifact under `renders/benchmark_renders/`, `renders/engineer_plan_renders/`, or `renders/final_solution_submission_renders/`, the tool should also return persisted render metadata from the bundle-local manifest for that render bundle. If the inspected file is under `renders/current-episode/`, the runtime may return scratch metadata when available, but that tree is not a published bundle. The global `renders/render_manifest.json` path remains a compatibility alias for current-bundle tooling when available.
  - For segmentation renders, that metadata must include a color legend mapping rendered colors to object identity.
  - Segmentation legend entries must expose both:
    1. a semantic label the model can reason about (`semantic_label`),
    2. a unique instance identifier (`instance_id` / `instance_name`) so repeated parts in an assembly remain distinguishable.
  - Repeated parts are therefore represented as repeated semantic labels with distinct instance identifiers, not collapsed into one legend row.
  - Merely listing `renders/` or reading `simulation_result.json` does not count as visual inspection.

#### Config-driven visual-inspection policy

- Visual-inspection requirements are configured in `config/agents_config.yaml`, not hardcoded in prompts alone.
- Policy shape:
  - `visual_inspection.required`: whether the role must inspect render images when available.
  - `visual_inspection.min_images`: minimum number of distinct render images the role must inspect.
  - `visual_inspection.reminder_interval`: how often runtime injects reminder messages while the role keeps operating without satisfying the image requirement.
  - When a role keeps failing the same blocker, it should inspect the exact render or video evidence before the next attempt; after three consecutive failures on the same issue, inspect render evidence on every subsequent retry until the blocker changes. This is the visual-inspection discipline expected by the render-evidence skill, not a substitute for the config gate.
- Current required roles are:
  - `benchmark_plan_reviewer`
  - `benchmark_reviewer`
  - `engineer_planner`
  - `engineer_coder`
  - `engineer_plan_reviewer`
  - `engineer_execution_reviewer`
- `min_images` is policy-driven. Current implementation uses `1` for the roles above.
- The gate is conditional on actual image availability in `renders/**`. If no render images exist for the current node/revision, the media requirement does not trigger.
- Runtime behavior is fail-closed:
  - for required non-reviewer roles in native tool-loop mode, `finish` is blocked until the configured image minimum is satisfied
  - for reviewer roles, approval is invalid unless required media inspection occurred during the current review attempt (enforced before accepting `submit_review.sh`)
- `read_file(...)` never satisfies visual-inspection policy, even if it points at a render path.

#### Benchmark tools

- `validate_benchmark(Compound) -> bool` the benchmark is validated to not be out of bounds, and not have intersecting:

  - Input object with environment
  - Goal objective with forbid objective
  - Input objective with goal or forbid objectives.
  - Top-level authored part labels must be non-empty, unique, and must not be `environment` or start with `zone_`, because the runtime reserves those names for the scene root and generated objective bodies.
  - `validate_benchmark()` fails closed on missing or blank authored labels and does not invent fallback names for unlabeled parts.
  - Benchmark-owned moving fixtures must declare their motion contract explicitly; `validate_benchmark()` rejects missing, contradictory, or unsupported motion metadata.

  Validated under all environment randomization.

  - `utils.objectives_geometry()` returns benchmark objective overlay geometry for the current workspace. It takes no arguments because the benchmark objective zones are defined in the `objectives` section of the canonical `benchmark_definition.yaml` path for the current workspace, and preview callers compose the returned geometry with the benchmark `build()` output before rendering. The helper is a shared importable utility, not benchmark-authored geometry logic.

  - `validate_benchmark()` is therefore a fast geometry gate, not a render gate, benchmark-success gate, or Genesis-runtime parity gate.

  - Current implementation bug to eliminate: `validate_benchmark()` must fail closed if the compound being validated can only be reproduced from transient shell state and not from the persisted script/workspace snapshot. A minimal fix is to derive a canonical semantic signature from the compound's child/component history, using primitive/component types, authored parameters, label, bounding box, rounded volume, face count, and wire length with tolerance-aware normalization, and compare it against the persisted authored script state; any mismatch is a fail-fast validation error. Raw mesh equality and direct volume equality are too brittle for this gate.

- `simulate_benchmark(Compound) -> BenchmarkToolResponse` - the benchmark-side stability/evidence simulation. It may fail on invalid benchmark motion metadata, physics instability, or other simulation errors, but it does not use goal completion as the benchmark-side success criterion. It uses the benchmark payload observation window from `config/agents_config.yaml` (`benchmark_payload_observation.window_s`, default `1.5s`) so payload out-of-bounds before the window is a hard failure and payload out-of-bounds after the window is recorded as benchmark evidence rather than a benchmark-simulation failure.

- `submit_benchmark_for_review(Compound)` - submits the whole benchmark compound for a review to `Reviewer` agent node, which can later approve it and pass it to the engineering graph. This call is valid only after current-revision validation and benchmark-stability simulation succeed.

#### Shared preview tools

- `render_cad(component: Part|Compound, orbit_pitch: float|list[float] = 45.0, orbit_yaw: float|list[float] = 45.0, rgb: bool = True, depth: bool = True, segmentation: bool = False, payload_path: bool = False) -> PreviewJobAck` - async on-demand preview submission for benchmark, engineer, and reviewer nodes. The runtime normalizes scalar camera inputs to lists, zip-pairs views by index, enforces the 64-view cap, and streams queued/view-ready/completed status over the worker-light control path while `worker-renderer` materializes the images into `renders/current-episode/`. When `payload_path=True`, the render bundle also includes a static payload-path overlay rendered from the finest available payload-trajectory artifact for the current workflow, using engineer-coder `payload_trajectory_definition.yaml` for engineering workflows and benchmark motion evidence for benchmark workflows. The helper returns a structured job ack; controller/API-backed multimodal runs use `inspect_media(...)` to view the resulting images. Benchmark callers compose benchmark `build()` output with objective overlays from `utils.objectives_geometry()` before previewing benchmark context.
- `objectives_geometry()` - a zero-argument utility re-exported by the public `utils` package, alongside `render_cad()` and `validate_benchmark()`, that reconstructs the benchmark objective overlay geometry from the `objectives` section of the canonical `benchmark_definition.yaml` path for the current workspace. It is shared runtime utility, not agent-authored geometry code. Preview callers combine its output with benchmark `build()` output before rendering benchmark context.

#### Engineering tools

- `validate_and_price(component: Part|Compound) -> float|dict[str, float]`: validates a part by for manufacturability, then prices it if valid using its workbench's cost calculation interface, or returns an error with a description and a location
- `validate_engineering(Compound) -> tuple[bool, str | None]` - the engineering geometry gate. It validates the approved solution assembly against the current revision, uses `validate_and_price(...)` for manufacturability and pricing prechecks, and fails closed if the assembly cannot be reproduced from the persisted workspace snapshot or does not satisfy the engineering constraints.
- `simulate_engineering(Compound) -> BenchmarkToolResponse` - Submits a model for a simulation. Robustness checking uses runtime randomization by executing one heavy-worker job with one backend scene build/load and `num_scenes` parallel jittered scene instances inside that one backend run. `num_scenes` is batch width, not permission for serialized whole-scene reruns or multiple heavy jobs on one worker; nor multithreaded implementation - only batch width.
- `submit_solution_for_review(Compound)` - submits the whole assembly for a review to `Reviewer` agent node, which can later approve it and submit return the final design to the user.

### Planner tools

`validate_costing_and_price`. Will:

1. Validate the pricing YAML file.
2. Deterministically compute and normalize cost/weight totals to cent precision from the declared parts and manufacturing inputs.
3. Overwrite the workspace file with the normalized numeric totals so the file on disk is the exit-time source of truth, not the LLM's draft.
4. Reject handoff if a later node-entry equality check would not reproduce the same totals exactly.

<!-- Future: will also add some basic planning suggestions. e.g.: i"t appears you are trying to CNC away over 80% of the stock. Consider picking a planning to use a smaller stock if possible."-->

`submit_benchmark_plan()` / `submit_engineering_plan()`. Will:

01. Validate planner-required files for the planner role (Engineering Planner/Benchmark Planner).
02. Return structured submission status (`ok`, `status`, `errors`) to the ReAct loop.
03. Be mandatory before planner completion/handoff.
04. Be the only valid planner completion gate: planner transitions are `PLANNED` only when `ok=true`.
05. Persist the stage-specific plan-review manifest for the next reviewer gate:
    - Benchmark Plan Reviewer: `.manifests/benchmark_plan_review_manifest.json`
    - Engineering Plan Reviewer: `.manifests/engineering_plan_review_manifest.json`
06. For `Benchmark Planner`, canonicalize benchmark constraints before final validation:
    - require planner-authored `constraints.estimated_solution_cost_usd` and `constraints.estimated_solution_weight_g`,
    - derive `constraints.max_unit_cost` and `constraints.max_weight_g` as `1.5x` those estimate fields,
    - reject planner handoff if those estimate fields are missing, non-numeric, or non-positive.
07. For `Benchmark Planner`, also reject handoff when `moved_object.material_id` is missing, empty, or not a known material in `manufacturing_config.yaml`, or when `benchmark_assembly_definition.yaml` is not a schema-valid full `AssemblyDefinition` artifact.
08. For `Benchmark Planner`, reject handoff when moving benchmark fixtures lack explicit motion metadata, when the motion contract is contradictory or unsupported, or when the fixture motion cannot be reconstructed from the benchmark handoff artifacts and evidence. The benchmark planner uses the coarsest course-setting layer, with its cadence and tolerance budget sourced from `config/agents_config.yaml` or benchmark motion metadata rather than hardcoded behavior.
09. For `Engineering Planner`, reject handoff when the approved solution includes moving engineer-owned parts but `assembly_definition.yaml` lacks a reviewable `motion_forecast` section describing the payload trajectory with ordered world-frame anchors, explicit `rot_deg` pose data, a build-zone-valid first anchor, an explicit goal-zone terminal proof, and first-contact order, or when its cadence/tolerance envelope conflicts with the planner policy declared in `config/agents_config.yaml`.
10. For `Engineering Coder`, reject `payload_trajectory_definition.yaml` when a step omits explicit rotation, when the terminal proof is ambiguous, or when the swept-clearance validator cannot prove the payload stays clear of fixed geometry for the full admissible rotation envelope. The artifact is mandatory and must be present on every engineering handoff.
11. For planner handoffs with machine-readable pricing totals, the persisted file must exactly match the script-normalized values at node entry; any cent-level drift is a hard failure even when the YAML remains schema-valid.
12. If planner handoff validation still fails when the planner node exits, orchestration routes back to planner with `REJECTED` state plus validation logs (fail-closed loopback).

Structured-output validation contract for planner/reviewer YAML artifacts:

1. Schema validation is strict by default: unknown/extra fields are rejected.
2. The strictness applies to nested models as well as top-level fields.
3. Validation failures from unknown/extra fields are hard gate failures (`ok=false` for planner submission, invalid reviewer output for review persistence/routing).
4. Any intentionally open-ended structure must be explicitly typed as such (for example, a specific metadata map). Runtime must not rely on parser permissiveness to accept unknown fields.

### Exact tools logic

I will define exact tool (function) logic to avoid confusion.

#### `validate_and_price(component: Part|Compound)`

Run the workbench interface to validate the part for manufacturability; if passes - also run the pricing, if not, return a validation error with fix suggestions. Detects both assemblies and individual parts.

1. Check cache for if we need to reverify the solution, early exit if not,
2. If there is the environment in the assembly (as required by `simulate_engineering` command), assert that it is in the correct position,
3. Split the assembly into benchmark-owned read-only fixtures versus engineer-owned manufactured parts / imported parts.
4. Validate manufacturability as per the Workbench interface only for engineer-owned manufactured parts. Do not reject because benchmark environment/input-objective fixtures lack manufacturing metadata.
5. Validate full-assembly placement and build-zone bounds, including interactions with the benchmark environment/objectives.
6. Determine cost for engineer-owned manufactured parts and selected imported parts only. Benchmark-owned fixtures never flow into engineer solution pricing,
7. Validate for cost,
8. Validate for weight.

##### `simulate_engineering(Compound)`

Simulate the compound. Must have the environment at the exact point where we it was defined in the task. Must have price and manufacturability checked
So:

1. Validate the solution assembly as in `validate_and_price(...)`
   - if valid, pass, if not valid, fail.
2. Git commit all files.
3. Start simulation, locally.
4. If simulation passes, notify the engineer via logs. (don't ask the agent to improve for now, though it could be well cost-efficient and useful). The agent will then run a `submit_solution_for_review(final_compound)`.
   - Don't render the video yet! If the simulation didn't pass, maybe we don't need to render the video. We can instead print positions (probably just final positions) of all parts in the simulation and let the agent introspect them.
     The simulation will produce video. The issue is, it's expensive to render.
5. If doesn't, retry the simulation.

#### submit_solution_for_review(compound: Compound)

The Engineering Coder calls `submit_solution_for_review(compound)` after validation and simulation pass for the latest code revision. This utility persists handover artifacts and marks the submission candidate as ready for review.

Submission-stage contract:

1. The submission call is reviewer-stage explicit; runtime must not guess a default reviewer stage when review submission is requested.
2. Benchmark submissions target `Benchmark Reviewer` and resolve `benchmark_assembly_definition.yaml` as the stage-correct assembly artifact.
3. Engineering submissions target `assembly_definition.yaml` as the stage-correct assembly artifact.

## Prompt vs skill guidance

Detailed role workflow recipes should live in runtime-loaded skills, not be continually expanded into long monolithic prompts.

Rules:

1. Prompts should carry only the minimum contract, safety, and role-goal information needed for the node.
2. Reusable authoring/debugging workflows belong in skills that the runtime mounts into the agent environment.
3. If a rule needs long examples, troubleshooting branches, or repeated operational reminders, prefer a skill update over appending more prompt text.

Manifest persistence contract:

1. No canonical/central reviewer manifest is persisted.
2. Exactly one reviewer-stage manifest is persisted per submission:
   - Benchmark Reviewer submission: `.manifests/benchmark_review_manifest.json`
   - Engineering Execution Reviewer submission: `.manifests/engineering_execution_handoff_manifest.json`
3. Planner `submit_benchmark_plan()` / `submit_engineering_plan()` persist the plan-review manifest:
   - Benchmark Plan Reviewer: `.manifests/benchmark_plan_review_manifest.json`
   - Engineering Plan Reviewer: `.manifests/engineering_plan_review_manifest.json`

Reviewer entry preconditions are explicit and fail-closed:

1. `submit_benchmark_for_review(compound)` or `submit_solution_for_review(compound)` must be called in the latest code revision (latest candidate script state), not in an earlier failed revision.
2. The latest validation artifacts must indicate success (`validate_benchmark()` in benchmark / `validate_engineering()` in engineering).
3. The latest simulation artifact must indicate success and objective completion (target payload reached the green/goal zone).
4. The reviewer-stage manifest must parse into a typed model (`ReviewManifest`) with `status=ready_for_review`, matching session/revision metadata, and correct `reviewer_stage`.
5. Reviewer model access to `.manifests/**` is denied by policy; reviewer eligibility is evaluated by deterministic system checks, not model-side reads of manifest files.

If any precondition is missing/invalid, it is a handoff invariant violation (not a reviewer decision). The system must:

1. Treat the handoff as invalid and route back to the producing agent with explicit validation feedback.
2. Keep this as fail-closed control flow (`REJECTED`/retry path), not as a successful transition into reviewer acceptance semantics.
3. Escalate to terminal `FAILED` when hard limits are reached (timeout/turn/token budget), rather than circling forever.

Reviewer output contract is strict:

1. Reviewer completion must produce a structured `review_decision`.
2. Missing structured reviewer output is invalid reviewer output and stays in fail-closed routing (with explicit logs), never auto-promoted to acceptance.
3. If renders/media are available for the current latest revision, reviewer approval is invalid unless the reviewer has called `inspect_media(...)` on that evidence during the current review attempt.
4. `list_files("/renders")` or equivalent text-only inspection does not satisfy the media-review requirement.
5. The exact minimum number of required inspected render images comes from the reviewer's `visual_inspection.min_images` policy in `config/agents_config.yaml`.

### Dealing with latency

All Python tools require all files to be uploaded. While this is a very rare edge case that an agent would run code tool before the file was edited, we should ensure that this doesn't happen.
