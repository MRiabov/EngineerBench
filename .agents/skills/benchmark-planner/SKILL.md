---
name: benchmark-planner
description: Benchmark planning and handoff authoring for Problemologist. Use when creating or revising benchmark planner artifacts (`benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_plan_evidence_script.py`), checking benchmark solvability or randomization, defining benchmark-owned fixture motion, enforcing exact-grounded inventory mentions, preparing the plan for `submit_benchmark_plan()`, or inspecting simulation evidence through frame-indexed `objects.parquet` sidecars.
---

# Benchmark Planner

Turn a benchmark brief into a complete handoff that the benchmark coder can implement without re-planning.

## Mission

1. Define one clear learning objective and the smallest benchmark that teaches it.
2. Keep the benchmark solvable, internally consistent, and easy for downstream roles to consume.
3. Prefer passive geometry first. Add benchmark-owned motion only when it is necessary for the objective.
4. Fail closed when required benchmark facts are missing, contradictory, or hidden behind placeholders.

## Workspace Note

Benchmark planning starts from the prompt and approved benchmark context. Do not expect writable handoff files at node entry.

## Canonical Preview Helpers

Use the shared preview helpers when evidence or objective overlays are part of the plan:

- `render_cad(...)` for live scene inspection and benchmark preview renders
- `objectives_geometry()` when a benchmark preview needs reconstructed objective overlays
- `list_render_bundles()` when the task depends on the exact bundle revision
- `query_render_bundle()` when you need compact bundle metadata or frame/object slices from a simulation bundle; use the sampled frame-indexed `objects.parquet` pose-history sidecar instead of treating `frames.jsonl` as pose data
- `pick_preview_pixel()` / `pick_preview_pixels()` when a render bundle needs click-to-world evidence
- Prefer `utils.preview` for new import paths; `utils.visualize` is compatibility-only

## Geometry Contract

- Base every size, offset, and clearance on declared geometry, declared dimensions, or an explicit formula.
- Do not guess a number. If the handoff is missing a needed value, treat the draft as incomplete instead of inventing one.
- If a volume, weight, or shape value needs derivation, use a short `build123d` script or CAD probe; a traceable script plus written result in `benchmark_plan.md` is sufficient proof.
- Treat weak geometry or physics derivations as a hard failure, not a minor gap. In practice, handoffs that cannot rigorously justify the motion or placement math have repeatedly failed downstream.
- When a fixture moves, derive its pose from the declared axis or joint frame instead of a world-coordinate guess.
- Prefer selector-driven placement over free-form XYZ positioning. Use face/axis selectors and explicit mates/joints to constrain parts to each other and to the environment; if an absolute 3-coordinate anchor is unavoidable, keep it to one or two top-level placements at most and treat it as fragile.
- Treat the planner handoff as YAML-backed: `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml` are the machine-readable contract, while `benchmark_plan_evidence_script.py` is the inspectable source of the approved geometry.

## Read First

Read these before drafting or revising the handoff:

- `references/handoff_contract.md`
- `specs/desired_architecture.md`
- `config/prompts.yaml`
- `specs/architecture/agents/roles.md`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/agent-artifacts/README.md`
- `../engineer-coder/SKILL.md`
- `../build123d-cad-drafting-skill/SKILL.md`
- `../render-evidence/SKILL.md` when render evidence already exists or preview judgment is needed
- `../mechanical-engineering/SKILL.md` when geometry or motion needs mechanical reasoning
- `../manufacturing-knowledge/SKILL.md` when explicit cost or quantity reasoning matters

## Working Rules

01. Design the benchmark for the engineer, not the solution.
02. Keep the challenge singular: one objective, one failure mode, one obvious path to success.
03. Keep `benchmark_definition.yaml` as the source of truth for objective geometry, randomization, and benchmark estimates.
04. Keep `benchmark_assembly_definition.yaml` as benchmark-owned fixture structure and motion contract.
05. Keep `benchmark_plan.md`, `todo.md`, the YAML files, and the benchmark evidence script mutually consistent.
06. Do not expect `benchmark_script.py` in the planner workspace before plan approval.
07. Treat benchmark-owned fixtures as downstream read-only context. Do not drift into engineer solution design.
08. Preserve exact part identity when a benchmark fixture is catalog-backed. Do not replace it with anonymous solids.
09. Use reserved names carefully: top-level authored labels must be unique and must not be `environment` or start with `zone_`.
10. Do not invent fallback labels, placeholder fields, or silent defaults to make a draft pass.

## Planner Loop

1. Reconstruct the objective, build zone, forbid zones, runtime jitter, and any benchmark-owned fixtures.
2. Choose the simplest benchmark family that still teaches the intended behavior.
3. Draft the benchmark geometry and any benchmark-owned fixture motion with explicit limits and clear visibility in the handoff.
4. Write `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, and `benchmark_plan_evidence_script.py`.
5. Cross-check labels, AABBs, motion, and script geometry against the YAML before submission.
6. Call `submit_benchmark_plan()` only after the handoff is coherent and placeholder-free.

## Handoff Rules

- Keep `benchmark_plan.md` narrative-first and specific enough that the benchmark coder can implement without re-deciding the benchmark shape.
- Keep `todo.md` actionable and ordered for the benchmark coder.
- Keep `benchmark_plan_evidence_script.py` aligned with the same geometry, labels, and repeated quantities as the approved inventory, and ensure every planner-declared inventory label appears in `benchmark_plan.md` at least once as an exact identifier mention.
- Keep every dimension formula-backed; if the handoff is missing a needed length, thickness, clearance, or placement datum, fix the source rather than guessing.
- Use `render_cad(...)` for live scene previews and objective-overlay evidence.
- Use `payload_path=True` on `render_cad(...)` when the live payload-path overlay is part of the inspection.
- Treat goal, build, and forbid zones as millimeter coordinates; any objective
  zone smaller than 3 mm on its largest axis fails closed instead of being
  auto-scaled.
- Keep the payload-to-goal bottom-center angle above the configured
  `benchmark_solvability.minimum_payload_to_goal_angle_deg` threshold so the
  benchmark is plausibly solvable with gravity-driven motion.
- After any significant blocker or repeated failure on the same issue, inspect the current render evidence before the next plan revision. If the same issue has failed more than three times in a row, keep inspecting render evidence on every subsequent retry until the blocker changes; use `../render-evidence/SKILL.md` as the visual-inspection playbook.
- If simulation evidence already exists, inspect the MP4 and the sampled frame-indexed `objects.parquet` pose-history sidecar together; `frames.jsonl` is sparse timing metadata, not pose history.
- If the review depends on bundle identity or a click-to-world answer, select the exact bundle with `list_render_bundles()` and inspect or query that bundle-local snapshot instead of assuming the newest visible render is the right one.
- Make the benchmark-owned motion contract explicit if any fixture moves. State the motion topology / DOF profile, the motion kind, and any axis or path reference when applicable; spell out the controller facts and limits.
- Keep the payload inside `build_zone` under static variation plus runtime jitter.
- Keep goal and forbid zones non-overlapping with the payload at spawn.
- Treat `submit_benchmark_plan()` as the final gate, not as a shortcut around an incomplete handoff.

## Common Failure Modes

- Goal or forbid zones overlap the payload path.
- Runtime AABB escapes the build zone.
- Labels collide with reserved names or with each other.
- The inventory is only semantically similar, not exact, across `benchmark_plan.md`, the YAML, and the planner scripts.
- The geometry or physics derivation is hand-wavy instead of formula-backed.
- A moving benchmark fixture is implied but not declared clearly.
- The evidence script drifts from the YAML geometry.
- The handoff assumes a downstream file that does not exist yet.
- The draft still contains placeholders, invented defaults, or ambiguous ownership.

## Boundary With Engineer Coder

Write the benchmark so `../engineer-coder/SKILL.md` can consume it as clean read-only context. If the downstream engineer would need to guess the benchmark intent, tighten the plan instead of handing off ambiguity.
