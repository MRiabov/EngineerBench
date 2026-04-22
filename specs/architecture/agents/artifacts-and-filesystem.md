# Agent artifacts and filesystem

## Scope summary

- Primary focus: runtime-agnostic workspace artifacts, file ownership, starter templates, and path permissions.
- Defines which files exist in an agent workspace and which roles may read or write them.
- Covers immutable control files, review manifest naming, and the static file-validation contract.
- Use this file for filesystem layout, artifact ownership, and permission-policy decisions.
- Runtime harness, debug CLI-provider mode, prompt generation, and skill loading live in [agent-harness.md](./agent-harness.md) and [agent-skill.md](./agent-skill.md).

## Filesystem

Agent workspaces live inside sandboxed container filesystems.

The filesystem rules are:

1. Agent access is sandbox-bound. An agent must not have read, write, or execution access outside its assigned sandbox/workspace root, except through explicitly mounted read-only runtime inputs that are part of that sandbox contract.
2. Path traversal outside the workspace root is a deterministic error.
3. Workspace-relative paths are the canonical file contract for paths inside the sandbox.

## Templates

Reusable starter files and prompt-context artifacts are defined once in `shared/agent_templates/`, which is part of the prompt-context contract.
The shared starter set includes `.admin/clear_env.py`, which resets the current
seeded workspace in place without changing the conversation context.
The shared starter set also includes `shared/agent_templates/common/.gitignore`, which is copied into each materialized workspace as read-only workspace metadata so the ignore policy stays inspectable without being agent-writable. That ignore file ignores the workspace `renders/` tree while re-including `*.json` files, so render parquet and other binary artifacts stay out of git history but JSON manifests remain visible.
PromptManager consumes these prompt-context inputs when it materializes the runtime prompt.
For CLI-provider-backed sessions, the runtime reads the checked-in `.agents/skills/` tree directly from the workspace checkout. That content is read-only runtime context, not canonical source. Controller-backed runtime surfaces may also expose it through the `/skills` mount. See [agent-skill.md](./agent-skill.md) for the source-tree and promotion contract.

Skill-training sessions may additionally materialize `suggested_skills/` as a writable session-local worktree/checkpoint seeded from the approved `.agents/skills/` tree. That overlay is session-scoped, not canonical source, and the training loop should read it first when it exists. Publication back into canonical `.agents/skills/` happens through a separate promotion flow.

Role-specific planner scaffolds remain in `shared/assets/template_repos/` and are copied into each workspace before node entry.
That runtime bootstrap surface is separate from `dataset/data/seed/**`, which stores only the seed corpus and the read-only handoff inputs. For Engineering Planner, the copied scaffold includes `assembly_definition.yaml` and `solution_plan_evidence_script.py` as runtime starter files. The render buckets a role expects follow the same `visual_inspection` policy contract described in [handover-contracts.md](./handover-contracts.md).
`worker_light/agent_files/` is a legacy compatibility mirror for bootstrap and local inspection, not the canonical source of truth.

Template files are intentional source artifacts, not ad hoc runtime defaults
or symlinks.

## Artifact Contract Library

Detailed per-file acceptance criteria live in [agent-artifacts/README.md](./agent-artifacts/README.md).
Use that library when you need the file-specific hard checks, quality bar, or reviewer look-fors for a seeded eval artifact.

## Initial files for each agent and read-write permissions

The agent-specific workspace surface is role-scoped.

Representative examples:

- Engineering Planner:
  - read: `.agents/skills/**`, `utils/**`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_script.py`, `benchmark_plan_evidence_script.py`, `solution_plan_evidence_script.py`, `engineering_plan.md`, `todo.md`, `journal.md`, `renders/benchmark_renders/**`, `renders/engineer_plan_renders/**`, `renders/current-episode/**`
  - write: `engineering_plan.md`, `todo.md`, `journal.md`, `assembly_definition.yaml`, `benchmark_definition.yaml`, `solution_plan_evidence_script.py`, `renders/current-episode/**`
- Engineering Coder:
  - read: `.agents/skills/**`, `utils/**`, `benchmark_script.py`, `benchmark_plan_evidence_script.py`, `solution_plan_evidence_script.py`, `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `reviews/**`, `renders/benchmark_renders/**`, `renders/engineer_plan_renders/**`, `renders/current-episode/**`
  - write: `solution_script.py`, additional `*.py` implementation files, `todo.md`, `journal.md`, `renders/current-episode/**`, `plan_refusal.md`
- Benchmark Planner:
  - read: `.agents/skills/**`, `utils/**`, `benchmark_plan_evidence_script.py`, `benchmark_plan.md`, `todo.md`, `journal.md`, `renders/benchmark_renders/**`, `renders/current-episode/**`
  - write: `benchmark_plan.md`, `todo.md`, `journal.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_plan_evidence_script.py`, `renders/current-episode/**`
- Benchmark Coder:
  - read: `.agents/skills/**`, `utils/**`, `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_script.py`, `benchmark_plan_evidence_script.py`, `reviews/**`, `renders/benchmark_renders/**`, `renders/current-episode/**`
  - write: `benchmark_script.py`, additional `*.py` implementation files, `todo.md`, `journal.md`, `renders/current-episode/**`, `plan_refusal.md`
- Reviewer roles:
  - read:
    - Benchmark Reviewer: `renders/benchmark_renders/**`, `renders/current-episode/**`
    - Engineering Plan Reviewer: `renders/benchmark_renders/**`, `renders/engineer_plan_renders/**`, `renders/final_solution_submission_renders/**`, `renders/current-episode/**`
    - Engineering Execution Reviewer: `renders/benchmark_renders/**`, `renders/final_solution_submission_renders/**`, `renders/current-episode/**`
  - write: stage-scoped `reviews/*.yaml` files only; when a reviewer calls `render_cad(...)`, the scratch preview is written into `renders/current-episode/**`

Render-bucket policy: `renders/current-episode/` is the only agent-writable render tree. `renders/benchmark_renders/`, `renders/engineer_plan_renders/`, and `renders/final_solution_submission_renders/` are backend-owned read-only bundles.

## System-only metadata

`.manifests/**` is reserved for deterministic handover/state metadata written
by backend utilities.

The current role manifest belongs to the same system-owned bucket. It records
which agent role is actively running the workspace node and is rewritten by
backend utilities when a workspace is handed to a new node.

Manifest ownership summary:

| Artifact | Writer / owner | Trigger | Path |
| -- | -- | -- | -- |
| Render bundle index | rendering producer | Render job completion for a published preview or simulation evidence bundle | `renders/render_index.jsonl` |
| Render metadata manifest | rendering producer | Render job completion for a published preview or simulation evidence bundle | `renders/<bundle>/render_manifest.json` |
| Current role manifest | backend runtime utility | Workspace materialization and node-transition refresh | `.manifests/current_role.json` |
| Benchmark plan evidence script | Benchmark Planner | planner evidence submission | `benchmark_plan_evidence_script.py` |
| Engineering plan evidence script | Engineering Planner | planner evidence submission | `solution_plan_evidence_script.py` |

Scratch preview files in `renders/current-episode/` are not published bundles and do not create entries in `renders/render_index.jsonl`.

Published render bundles may also contain bundle-local `preview_scene.json` snapshots and, for video-backed evidence, `frames.jsonl` and `objects.parquet` sidecars. These files are backend-owned bundle contents and follow the render artifact contract in [renders acceptance criteria](./agent-artifacts/renders_acceptance_criteria.md).

| Benchmark plan-review manifest | backend runtime utility invoked by `submit_benchmark_plan()` | Successful `Benchmark Planner` `submit_benchmark_plan()` | `.manifests/benchmark_plan_review_manifest.json` |
| Engineering plan-review manifest | backend runtime utility invoked by `submit_engineering_plan()` | Successful `Engineering Planner` `submit_engineering_plan()` | `.manifests/engineering_plan_review_manifest.json` |
| Benchmark review manifest | backend runtime utility invoked by `submit_benchmark_for_review()` | Successful benchmark `submit_benchmark_for_review()` | `.manifests/benchmark_review_manifest.json` |
| Engineering execution-review handoff manifest | backend runtime utility invoked by `submit_solution_for_review()` | Successful engineering `submit_solution_for_review()` | `.manifests/engineering_execution_handoff_manifest.json` |

The agent-facing tools are the submission triggers. The actual manifest write
happens in the backend runtime utility, and `.manifests/**` remains
inaccessible to LLM roles.

The current role manifest is the authoritative active-role marker for the
workspace node. Backend utilities write it before a node starts and refresh it
when the same workspace is reused by a different role.

The engineering execution-review manifest is the same file on both sides of
the handoff:

- the coder writes it by successfully calling the matching role-scoped review submission helper (`submit_benchmark_for_review(...)` or `submit_solution_for_review(...)`)
- the Engineering Execution Reviewer later reads it as the latest-revision
  entry gate

## Bug report artifact

`bug_report.md` is a workspace-root debug artifact owned by the active role
when bug-report mode is enabled.

The mode does not change the default workspace layout. It only adds a
conditional write path for the current role when the blocker is caused by
infrastructure, harness, workspace materialization, prompt transport,
filesystem policy, render plumbing, eval orchestration, or other runtime
plumbing rather than by the task itself.

The artifact stays separate from `journal.md`, `plan_refusal.md`, and the
stage review YAML files. It is not a stop signal, and it does not replace the
normal handoff or review routing.

Maintainer-facing archives live under `logs/bug_reports/` and are populated by
the public archive helper, not by agent workspace writes.

Reviewer-stage manifest filenames are explicit and role-scoped:

1. `.manifests/benchmark_plan_review_manifest.json`
2. `.manifests/benchmark_review_manifest.json`
3. `.manifests/engineering_plan_review_manifest.json`
4. `.manifests/engineering_execution_handoff_manifest.json`

Reviewer persistence filenames are explicit and role-scoped:

1. `reviews/benchmark-plan-review-decision-round-<n>.yaml`
2. `reviews/benchmark-plan-review-comments-round-<n>.yaml`
3. `reviews/benchmark-execution-review-decision-round-<n>.yaml`
4. `reviews/benchmark-execution-review-comments-round-<n>.yaml`
5. `reviews/engineering-plan-review-decision-round-<n>.yaml`
6. `reviews/engineering-plan-review-comments-round-<n>.yaml`
7. `reviews/engineering-execution-review-decision-round-<n>.yaml`
8. `reviews/engineering-execution-review-comments-round-<n>.yaml`

## Locking rule

Before planner submission, planner roles may edit planner-owned files.

After planner submission is accepted:

1. benchmark-side `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml` become read-only for benchmark Coder/Reviewer,
2. `benchmark_plan_evidence_script.py` becomes read-only for benchmark Coder/Reviewer and is also available in engineer intake as read-only context,
3. the same `benchmark_assembly_definition.yaml` and `benchmark_script.py` are also available in engineer intake as read-only context,
4. engineer-side `assembly_definition.yaml` becomes read-only for engineering Coder/Reviewer,
5. `solution_plan_evidence_script.py` becomes read-only for engineering Coder/Reviewer and the Engineering Execution Reviewer,
6. only replanning can mutate planner-owned files.

## Template auto-validation

Where possible, templates have a validation schema.

YAML templates are schema-validated when they are materialized into a
workspace, so starter drift is caught at source rather than after a node has
already started.

Any seed-backed row with writable authored files must preserve the runtime
starter snapshot for the files the agent is expected to edit. For planner
workspaces, that starter snapshot includes the role-owned authored plan files
and planner evidence script. For coder workspaces, that starter snapshot
includes the role-owned authored source file plus `todo.md` and `journal.md`.
For reviewer workspaces, that starter snapshot includes the writable note
files the reviewer is expected to edit. Seed validation fails closed if the
stored seed corpus already contains a pre-solved output instead of the
expected non-template seed inputs.

For Engineering Planner, the runtime starter snapshot also includes the
checked-in `assembly_definition.yaml` template baseline and
`solution_plan_evidence_script.py`, and controller entry validation fails
closed if those runtime starter files are already solved or otherwise diverge
before planner edits.

## `agents_config.yaml` (path permissions policy)

To prevent permission drift between the static file contract and runtime behavior, we define a centralized policy file at `config/agents_config.yaml`.

The policy uses gitignore-style glob patterns (`*`, `**`, path prefixes) for filesystem access control.

Rules:

01. Every read/write/edit/upload/download operation is checked against this policy in `FilesystemMiddleware`.
02. `deny` takes precedence over `allow`.
03. If a path is not matched by `allow`, access is denied by default.
04. Agent-specific rules override `defaults`.
05. Reviewer roles get `write/edit` tools, but policy only allows writes to their stage-specific persisted review YAML pairs.
06. `.manifests/**` is non-overridable deny for all LLM agent roles; only backend runtime utilities may access it.
07. No agent role may be granted access to filesystem paths outside its sandbox/workspace root.
08. `config/agents_config.yaml` also owns preview-render modality policy under top-level `render: {rgb, depth, segmentation}`, the motion cadence/tolerance policy for benchmark planner, engineer planner, and engineer coder layers, and the benchmark payload observation window used by benchmark simulation.
09. Those flags control whether renderer-backed preview artifacts are emitted into `renders/current-episode/` during the active stage and into the stage-owned persistent handoff bundles for each modality; they do not change worker routing or backend selection policy. The motion policy controls waypoint frequency and tolerance budgets, while the benchmark payload observation window controls the initial payload out-of-bounds grace period. The persistent bundle subdirectory still reflects the workflow that produced it.
10. `renders/current-episode/` is the only agent-writable render tree. The persistent render bundle directories are backend-owned read-only paths and must not be writable by agent roles.

## Immutability validation

We assert that control files are not edited by coder agents and are edited only by planner agents.

Control-file ownership split:

01. `benchmark_definition.yaml` owns benchmark/task definition and benchmark fixture metadata (`benchmark_parts`).
02. `benchmark_assembly_definition.yaml` owns benchmark-owned fixture structure, motion metadata, and benchmark-side implementation details.
03. `benchmark_script.py` owns benchmark-owned geometry composition and read-only benchmark preview context.
04. `benchmark_plan_evidence_script.py` owns benchmark planner evidence geometry.
05. `benchmark_plan.md` owns benchmark planner narrative and exact inventory grounding.
06. `solution_script.py` owns engineer-planned solution geometry and implementation code.
07. `solution_plan_evidence_script.py` owns engineering planner evidence geometry.
08. `engineering_plan.md` owns engineering planner narrative, proof structure, and exact inventory grounding.
09. `assembly_definition.yaml` owns engineer-planned solution structure, costing inputs, and motion metadata; Engineer Planner workspaces materialize it from the starter template baseline before any planner edits.
10. `payload_trajectory_definition.yaml` is the required engineer-coder higher-resolution payload trajectory and contact proof; it refines the coarse planner forecast, must not contradict it, must declare explicit rotation on every step, must start at the payload spawn position, must end at the goal-zone center, must never rise above the spawn height, and must remain swept-clearance safe against fixed geometry.
11. We do not duplicate engineer solution metadata into `benchmark_definition.yaml`.

The publication prune for technical drawing removes only the companion
`*_technical_drawing.py` scripts and preview rendering. It does not change the
read-only status of `benchmark_plan_evidence_script.py` or
`solution_plan_evidence_script.py`, and it does not remove the coarse
`motion_forecast` in `assembly_definition.yaml`, `payload_trajectory_definition.yaml`,
or their validation paths.

## File updates

Files are written directly to the worker container and persisted to the observability database, not to the controller filesystem.

The controller parses the tool call locally and then dispatches the request to the worker that is responsible for the relevant file operation.

## Utils files

The agent has a set of utils - python scripts (files) that the agent can import from.

These are explicitly unwritable by the filesystem middleware.
