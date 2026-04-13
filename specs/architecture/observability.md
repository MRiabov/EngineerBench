# Observability

## Scope summary

- Primary focus: observability data model for traces, events, metrics, and debugging.
- Defines ID/linkage contracts (`user_session_id`, `episode_id`, and related run IDs) and event catalog requirements.
- Covers metric extraction strategy, lineage metadata, failure tracking, backups, and user-review signals.
- Use this file for telemetry schema decisions and observability pipeline behavior.

To track all agent movements and to persist data, we encode the following:

1. The agent pass/fail reasons
2. Error messages from script execution, linting,
3. All agent thoughts.
4. A mechanism to reconstruct those - e.g. we record the entire conversation and tool-calling structure, so how can we read it? How can we show it to users that use this prompt? How can we use it for debugging? basically, some order matters. Or, maybe just dump the conversation in/out to schema, that could also work.
5. Renders (visuals) of what the agent sees (optionally; if it doesn't take too much space; it may very well be more economical to reconstruct at runtime using scripts. So record what comes into the agent, all parameters, code, setup, etc, and rebuild at runtime.)
6. Feedback from the user.
7. All detailed metadata as required by "Evaluation" database, and more. All bits of data on what called when should be extracted.

These will be later used for querying, preproc and model training.

## LangFuse for observability, DB for deeper logs

We use LangFuse for LLM observability. We will use a Railway template for deployment / deploy a separate container on docker-compose locally.

Langfuse is deployed locally/on Railway.

For deeper observability, e.g. requirements like "fasteners were used in at least 70% of cases", store fastener usage in the application database.
Per-call LM usage is forwarded to Langfuse observations (`input_tokens`, `output_tokens`, `total_tokens`, model, and cost when available) for deterministic attribution.

### ID model and linkage

Use explicit IDs and link all observability data to them:

1. `user_session_id`: one user conversation/session.
2. `episode_id`: one agent workflow execution attempt within a user session.
3. `simulation_run_id`: one simulation invocation within an episode.
4. `cots_query_id`: one COTS query invocation within an episode.
5. `review_id`: one reviewer decision artifact.
6. `trace_id`: one observability trace record (with optional `langfuse_trace_id` linkage).

Current implementation note (explicit bug):

- We currently conflate `session_id` and `episode_id` in parts of the runtime/observability flow.
- This is a bug, because user session scope and workflow execution scope are different concerns.
- Required fix direction: keep `episode_id` as workflow-run identity, introduce/propagate `user_session_id`, and store both on traces/events/assets for deterministic joins.

### Machine-readable error stream

Backend logging supports a machine-readable sidecar stream for error-level events.

Contract:

1. When `EXTRA_ERROR_JSON_LOG` is configured, services append JSON Lines records for `error`/`exception`/`critical` events.
2. Each record includes `service` and must include at least one run-correlating identifier: `session_id` or `episode_id` (preferably both where available).
3. This stream is used by integration/runtime triage tooling for deterministic early-stop/fail-fast behavior on non-allowlisted backend errors.
4. Failure to write the sidecar stream must never block primary application logging.

<!--Note: this is mostly integration test logic.-->

### All collected events

We track the following structured domain events to compute the evaluation metrics defined in the [Metrics](#metrics) section:

01. Component usage,

02. Tool invocation,

    - separate events for each tool call - easier to track later.

03. Manufacturability and price check (engineer)

    - store all metadata too - verified which part, for which manufacturing method, result(pass/fail; weight price, etc.)

04. Scene validation (Benchmark Coder)

05. Benchmark motion contract validation (Benchmark Planner / Benchmark Reviewer)

    - store declared fixture motion topology, DOF profile, actuation mode, evidence linkage, and validation result

06. Render request (engineer)

07. Render request (benchmark)

08. Simulation request (engineer)

09. Simulation result (engineer)

    - Failure/pass reason -
      - Success: hit green zone
      - Failure in the [tracking failures](#tracking-failures) section:
        - Timeout,
        - Out of bounds
        - Forbid zone hit
        - Part breakage
    - Simulation time elapsed
    - Computing time

10. COTS search (engineer/planner?)

11. Plan submission (benchmark)

12. Plan submission (Engineer)

13. Price/weight failure escalation request (Engineering Coder)

14. Price/weight failure escalation decision (reviewer)

15. Lint failure - code

16. Lint failure - Markdown/YAML

17. Logic/constraint failure - YAML

18. Skill edit (skill editing agent)

19. Skill file read (any agent) (note: track reading of skills or even particular files or even lines may link to success rates.)

20. Instability in the simulation (if an agent produced an instable solution, or a NaN somehow and we didn't catch it)

21. Submission attempt without creating all necessary files.

    - if planner tried submitting the result without `benchmark_plan.md`, `benchmark_definition.yaml`, or benchmark-owned `benchmark_assembly_definition.yaml`, or if they were left equal to their templates (don't allow submission), and note an event.

22. Submission from reviewers - Review decision events for every reviewer stage (Benchmark Plan Reviewer, Benchmark Reviewer, Engineering Plan Reviewer, Engineering Execution Reviewer) with decision, reason category, reviewer manifest filename, persisted review decision filepath, persisted review comments filepath, and evidence used (images viewed count, video viewed, files checked).

23. Plan refusal events with explicit refusal reasons (array), `agent_role`, and proof-of-impossibility evidence from `plan_refusal.md`

24. Forbidden joint creation/adding logic.

25. Excessive/unjustified engineering DOF detection event from reviewer stages (`excessive_dof_detected`) with evidence payload (`part_id`, proposed `dofs`, `dof_count`, expected-minimal engineering `dofs`, `reviewer_stage`, `dof_count_gt_3`).

26. `conversation_length_exceeded` event with compaction metadata (threshold and before/after conversation size).

27. Plan-reviewer deterministic validator execution (`plan_review_validation_run`) with reviewer stage, input artifact revision, validator status, and mismatch reasons when rejected.

28. Reviewer manifest gate failures (`reviewer_manifest_gate_failed`) with reviewer stage, manifest filename, failure class (`missing`, `stale`, `invalid_schema`, `revision_mismatch`), and blocked node id.

29. Preview render request (`preview_render_requested`) with requested modalities, normalized orbit angles, requested view count, selected preview backend, and render purpose (`benchmark_preview`, `engineer_preview`, or `final_preview`). If the job is queued, include queue position or estimated wait where available.

30. Preview render completion (`preview_render_complete`) with preview backend, modalities, view count, image count, elapsed render time, and artifact paths. Streaming view-ready updates remain trace-visible through the same episode/session trace even when they are not promoted to a separate event family.

31. Media inspection event (`media_inspection`) for every agent media-view action, with node/reviewer stage, requested path, resolved artifact path, media kind (`image`, `video_frames`), attached image/frame count, and attach result (`attached`, `missing`, `unsupported_format`, `failed`).

32. LLM media attachment event (`llm_media_attached`) whenever a model request includes media parts, with node name, provider/model, attachment count, media kinds, and source artifact paths.

33. CLI-provider skill-loop self-reflection event (`skill_self_reflection`) with the follow-up prompt path, output path, trigger reason, simulation/verification outcome, and the captured reflection text.

34. CLI-provider skill-loop skill-update event (`skill_update`) with the follow-up prompt path, output path, trigger reason, updated skill paths, simulation/verification outcome, and the captured skill-update text.

35. CLI-provider skill-loop skill-promotion event (`skill_promotion`) with the active overlay path, approved base commit, target repo or branch, merge strategy, outcome (`published`, `conflict`, `escalated`, `rejected`), PR or commit metadata, and any conflicting skill paths.

Submission helpers also snapshot the workspace in git on submission attempts that changed substantive workspace files, including rejected attempts that mutated the workspace. Runtime scratch files such as submission logs or local cache directories do not force a commit by themselves. This history is part of the reproducibility record and is intentionally separate from the stage manifests, which remain the routing source of truth.

Visual-inspection-policy enforcement must also be reconstructable from traces even if we do not persist dedicated reminder events:

1. When a role is subject to config-driven visual inspection (`config/agents_config.yaml`), the trace should make it possible to determine whether images existed, whether `inspect_media(...)` was called, and whether the configured minimum image count was satisfied.
2. Runtime-injected reminder messages and fail-closed completion/approval refusals for missing visual inspection should therefore remain visible in persisted conversation/tool traces (`submit_review` for reviewer native loops, `finish` for non-reviewer native loops).
3. `media_inspection` and `llm_media_attached` are the primary structured observability events for this path; reminder text may remain trace-visible rather than becoming a separate domain event unless later metrics require it.

<!-- 20. Metric for "Jamming Rate"
    - Definition: Object velocity = 0 for > X seconds while Actuator Force > 0.
    - Why: Distinguishes between "I didn't try" and "I tried but the mechanism jammed". Crucial for debugging friction/tolerance issues -->

<!-- Code quality: all events are enums and all events have models for strict schema.-->

#### Not just events, but numeric events

Notably, outside of just events, we want to track crucial numbers; especially for metrics below. E.g. cost/weight estimate events from planners and actual cost/weight from validation, for error analysis. *Technically*, we don't exactly *need* an event because we have the benchmark_definition.yaml in s3, but extracting the data from `benchmark_definition.yaml` and other numeric YAML artifacts (including reviewer checklist YAML) will make it very handy for downstream analysis (and would save time for analysis downstream.)

#### Tracking seeds

In addition, we track randomization seed and variant events for every run (static variant id, runtime seed). Needed for robustness/flakiness metrics.
We persist lineage fields in episode metadata and DB for both benchmark generation and engineer execution:

- `seed_id`: canonical source item id.
- `seed_dataset`: dataset/source path or identifier.
- `seed_match_method`: enum describing linkage strategy (`runtime_explicit`, `exact_task`, `no_exact_task_match`, `ambiguous_exact_task`).
- `generation_kind`: enum describing run origin (`seeded`, `derived`, `seeded_eval`, `integration_test`, `COTS Search`, `Skill Agent`).
- `parent_seed_id`: direct lineage parent (for derived runs).

Integration/test tagging is part of the same metadata contract:

- `is_integration_test`: boolean marker set by integration runtime mode.
- `integration_test_id`: canonical `INT-xxx` id inferred from task/session where available.

### Metrics

We define (a growing list of) (aggregate) metrics:

<!-- All below are LLM suggested, but are good. -->

01. Benchmark solvability rate: % of generated benchmarks solvable within constraints by the engineer (or baseline solver).
02. Benchmark diversity coverage: distribution across physics principles (gravity, friction, motors), object types, DOF counts, moving parts, and environment templates.
03. Robustness across seeds: success rate across runtime jitter seeds and static variants.
04. Plan adherence rate: how often CAD output matches plan (geometry, constraints, objectives).
05. Price/weight estimation error: planner estimated vs actual validated cost/weight, by agent and benchmark type.
06. Time-to-solution metrics: median time/tool-calls to first valid benchmark and first valid solution.
07. Reasoning trace capture rate: % of runs with stored traces; trace sufficiency score (presence of required sections).
08. Journal quality score: % of entries with intent/result/reflection/next-step; frequency per run; correlation with success.
09. Optimization capture rate: % of runs where notable optimization is logged (objective #5).
10. Skill effectiveness: performance delta before/after a new skill version.
11. Reviewer precision/recall: false accept/reject rate based on downstream outcomes.
12. Simulation stability rate: % of solutions with no instabilities, NaNs, penetrations, or joint violations.
13. Dataset readiness score: % of runs meeting training-dataset criteria (complete artifacts + verified solution + valid reasoning trace).
14. Cost/weight delta heuristic: if cheaper/lighter alternative was computed (simulated) but final solution is worse, log event.
15. On-demand preview latency by modality, purpose, and requested view count: median preview time split by requested modality, render purpose, and requested view count.
16. Visual-evidence usage rate: % of review attempts with available renders that actually called the media-inspection tool and attached media to the model.
17. Visual-policy compliance rate by role: % of runs where roles configured with `visual_inspection.required=true` satisfied their current `min_images` requirement when render images were available.
18. Skill publication latency: elapsed time from a `skill_update` event or overlay completion to successful promotion into canonical `.agents/skills/`.
19. Skill promotion conflict rate: % of promotion attempts that required conflict resolution or human escalation.
20. Skill overlay provenance: whether the retained session metadata captures the overlay root, approved base commit, and promotion outcome for later replay.

<!-- 1. Infrastructure/framework stability:
    - % of sessions completed successfully to their expected end and not failing under timeouts, container crashes, etc.LLM-suggested. -->

<!-- 2. Denser reward signal - track normalized distance to target, something like `Score = 1.0 - (min_distance_achieved / initial_distance)`. Ideally (not mandatory, probably skip for now), also measure a performance of simulation simply without any changes (what if we do nothing - how good is the result?)
    - it's a metric that was more used in RL, but it's infromative... sometimes. LLM-suggested. -->

<!-- LLM-suggested. -->

<!-- 11. Library growth and reuse: new build123d modules added per period and reuse rate across tasks. -->

## Tracking failures

It is desirable to understand why the simulation/model has failing, so I propose to introduce a more detailed tracking system:

1. `EpisodeStatus` stores the coarse lifecycle state (`RUNNING`, `PLANNED`, `WAITING_USER`, `COMPLETED`, `FAILED`, `CANCELLED`).
2. `EpisodeMetadata` stores detailed execution details:
   - `episode_phase` stores the current workflow phase (`BENCHMARK_PLANNING`, `BENCHMARK_PLAN_REVIEWING`, `BENCHMARK_CODING`, `BENCHMARK_REVIEWING`, `ENGINEERING_PLANNING`, `ENGINEERING_PLAN_REVIEWING`, `ENGINEERING_CODING`, `ENGINEERING_EXECUTION_REVIEWING`).
   - `terminal_reason` stores the concrete terminal cause (`APPROVED`, `REJECTED_BY_REVIEW`, `TIMEOUT`, `OUT_OF_TURN_BUDGET`, `OUT_OF_TOKEN_BUDGET`, `SYSTEM_TOOL_RETRY_EXHAUSTED`, etc.).
   - `failure_class` stores ownership classification (`AGENT_QUALITY_FAILURE`, `AGENT_SEMANTIC_FAILURE`, `APPLICATION_LOGIC_FAILURE`, `INFRA_DEVOPS_FAILURE`).

During agent debugging, manual or self-improvement via GEPA we'll be able to use it to guide on how to fix the system.

### Fail-closed terminalization

The system enforces fail-closed behavior for terminal states.

- Hard-fail limits terminalize episodes with `EpisodeStatus.FAILED` when turn, token, or time budgets are exceeded. Terminal reasons map to `OUT_OF_TURN_BUDGET`, `OUT_OF_TOKEN_BUDGET`, or `TIMEOUT`.
- Handoff validation gates transitions between nodes (for example planner to coder) through strict structural and semantic checks. Failed checks produce a `REJECTED` session state and terminalize as `FAILED` if unrecovered.
- Structured outcomes require `terminal_reason` for all terminal episodes. Failed terminal episodes also require `failure_class` for evaluation routing and infrastructure debugging.
- System retry exhaustion maps to `terminal_reason=SYSTEM_TOOL_RETRY_EXHAUSTED` and `failure_class=INFRA_DEVOPS_FAILURE`.

### Bulk uploading events

<!-- This part was LLM-suggested, but is OK -->

We decided on persisting a local `events.jsonl` file with all events for deeper observability instead of sending individual events or a sqlite DB. This would allow sending all the events in one go instead of dozens of small requests. For 100 events per a 3-5 minute session (if that), it is acceptable. In fact, it wins a bit of performance: opening DB a hundred connections is slower than opening one and batch uploading it.

CLI-provider skill-loop runs should emit self-reflection and skill-update records into a local `events.jsonl` sidecar under the run workspace, and the same records may later be promoted into the controller DB event stream when an episode-backed integration path exists. The full self-reflection text is intentionally retained for diagnostics and postmortem debugging.

The retained episode bundle should also preserve the workspace inputs and outputs that influenced the run, including `prompt.md`, `benchmark_plan.md`, `engineering_plan.md`, `todo.md`, `journal.md`, `logs/skill_loop/journal.md`, `logs/skill_loop/context_snapshot.md`, review YAML, validation/simulation outputs, `plan_refusal.md` when present, and render bundles so later training can reconstruct the failure context without relying on a separate journalling agent or lossy summary pass. A standalone training CLI such as `train_skills.py` or equivalent can consume that bundle later.
Bug-report archival follows the same reproducibility rule: when a runtime blocker is filed, the archive helper writes the copied `bug_report.md` and a manifest under `logs/bug_reports/` with the role, session or episode identifiers when available, the workspace path, the archive path, and a content hash so maintainers can join the report back to the run.
When the promotion arbiter publishes or rejects a skill diff, it should emit a traceable outcome record that links the originating session overlay back to the canonical skill-repo commit.

## Best practice: Give LLMs a way to complain

We have a "sidecar" model that checks where the agent was confused and updates skills.

We can reuse the same approach for debugging. A LLM that explicitly checks where the model got confused and sends a tool call if something was really wrong. The developer gets that into a DB/observability DB. **The developer can use the LLM output to debug.**
(ideally, we would also heap those and send them to Google Jules which will fix bugs/propose functionality/ etc.

<https://jules.google/docs/api/reference/>)

Create another sidecar model running async (maybe batch) that would read reasoning traces of the agent and populate the issues. Basically an agent that debugs. It saves me, a developer, a pain in the of debugging.

## Backups

In prod we will backup the database(s) daily.

<!-- Notably, the file could be quite big, as we persist sqlite text. Max compression it before backing up. -->

One way to do it is by sending a `cron` job daily. Thus, implement an endpoint which will accept a cron call, and will back up the SQLite folder to the s3. Again, this is in production.

## User Reviews

I want to track successful/failed reasoning via user thumbs up/down during:

1. Benchmark generation planning
2. Benchmark Generation implementation; specifically voting on individual file outputs and voting on the output "as a whole". Ideally, the users would also be able to input their feedbacks on individual subassembly parts, as defined by the assembly view in the frontend, by selecting them and pressing thumbs up/down and inserting a comment.
3. Implementation Planning
4. Implementation Generation.

We are using LangFuse and it has those capabilities natively.

### Training on user reviews

When user stores the review, first of all, store it in the observability DB, and then we'll also need to incorporate an automatic prompt improvement with powerful models like Claude 4.6 Opus with human review that will be merged/skipped.

We temporarily won't do auto-improvement through a model, though I bet we'll need it in the near future.

<!-- Note: I don't know why, but the Gemini models are good at coding but horrible at making prompts/interpreting desired prompt behavior; don't use them for this purpose. -->
