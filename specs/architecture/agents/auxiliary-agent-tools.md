# Auxiliary Agent Tools

## Scope summary

- This file records helper surfaces that are real in the runtime but intentionally outside the core contract in [Agent tools](./tools.md).
- The main tool contract stays in `tools.md`, `agent-harness.md`, `agent-skill.md`, and the runtime docs.
- This file owns secondary wrappers, diagnostic helpers, skill-loop utilities, and experimental functions that should not be duplicated in the main docs.
- When one of these helpers graduates into a stable cross-role contract, the durable rule moves to the owning main doc and this file keeps only a short reference.

## Contract boundary

- Auxiliary helpers do not invent new agent abilities. They expose narrower or more specialized ways to reach existing runtime behavior.
- Render-query helpers must resolve against an immutable bundle-local scene snapshot. Pixel coordinates are only input seeds, not stable identity.
- Bundle history and render-file layout are owned by the rendering architecture docs, not by this file.
- Helper names are not a stability guarantee. If a helper mutates benchmark state, it must say which artifact it mutates and whether the artifact is benchmark-owned, engineer-owned, or derived.
- Post-simulation helpers must require post-simulation artifacts.
- Skill-loop helpers must stay inside the active `suggested_skills/` worktree/checkpoint and must not assume the canonical `.agents/skills/` tree is mutable.
- Experimental helpers must fail closed when required artifacts are missing and must not create placeholder state.
- Prompt templates may mention an auxiliary helper, but the runtime contract is still owned by the source file that implements it.

## What belongs here

- This file does not repeat the core tool set already documented in [Agent tools](./tools.md).
- The core surfaces that remain documented elsewhere include `validate_benchmark`, `validate_engineering`, `simulate_benchmark`, `simulate_engineering`, `submit_benchmark_plan`, `submit_engineering_plan`, `submit_benchmark_for_review`, `submit_solution_for_review`, `inspect_media`, `inspect_topology`, `validate_costing_and_price`, `preview`, and `objectives_geometry`.
- This file instead tracks helper namespaces and functions that are secondary, role-specific, or experimental.

## Render-query helpers

- `worker_light.utils.render_query` is the planned worker-light helper family for bundle lookup and ray-pick.
- `pick_preview_pixel(...)` resolves a screen-space click through the persisted render snapshot and returns a structured world-space hit record. Stable calls should include `bundle_path`, `pixel_x`, `pixel_y`, `image_width`, `image_height`, and `view_index`; `bundle_id` and `manifest_path` are optional disambiguators. Use `pick_preview_pixels(...)` for multiple picks against the same snapshot.
- `list_render_bundles(...)` and `query_render_bundle(...)` are lookup helpers that sit on top of the render history contract owned by the rendering docs.
- These helpers are auxiliary. They fail closed when the bundle snapshot, render history, or requested artifact cannot be resolved.

## Current inventory

| Namespace | Current helper surface | Status | Ownership / notes |
| -- | -- | -- | -- |
| `shared.utils.agent` | `refuse_plan(reason)` | Auxiliary wrapper | Writes a refusal artifact or forwards to the heavy-worker refusal path. The other proxy wrappers in this module are core and stay documented in `tools.md`. |
| `controller.agent.tools` | `run_validate_and_price_script(fs)` | Internal bridge | Runs the checked-in planner pricing script. The exposed planner gate is `validate_costing_and_price()`, which uses this bridge. |
| `controller.agent.nodes.skills` | `save_suggested_skill(title, content)` | Skill-training staging helper | Writes staged skill drafts into the session-local `suggested_skills/` worktree/checkpoint for the standalone training loop. It is a compatibility write primitive, not evidence that a separate skill-promotion role is required by the target architecture. |

## Planned render-query surfaces

| Namespace | Proposed helper surface | Status | Ownership / notes |
| -- | -- | -- | -- |
| `worker_light.utils.render_query` | `pick_preview_pixel(...)`, `pick_preview_pixels(...)`, `list_render_bundles(...)`, `query_render_bundle(...)` | Planned / auxiliary | Worker-light render lookup and ray-pick helper family. Implementation may be re-exported through the public `utils` facade as thin wrappers. |

## Experimental surfaces

- The current experimental cluster is the render-query helper family in `worker_light.utils.render_query`.
- The next auxiliary cluster is the same render-query helper family, which depends on the render bundle contract owned by the rendering architecture docs.
- Those helpers are still opt-in. A benchmark or engineering task only uses them when the task needs bundle lookup or point-pick resolution.
- The prompt surface should not advertise them as universal capabilities for every task.

## Backend plumbing

- `controller.tools.fs.create_fs_tools(...)` and `worker_light.utils.filesystem.get_filesystem_middleware(...)` are backend plumbing for the filesystem tool surface, not additional model abilities.
- `worker_light.utils.assets.validate_asset_source(...)` is an asset-serving guard, not a general agent tool.
- `worker_light.utils.git.*` manages workspace repository state and skill sync/promotion bookkeeping. It supports the runtime, but it is not a separate tool contract for the model.
- `scripts/experiments/**` are evidence and measurement harnesses. They can justify a future helper contract, but they are not runtime tools themselves.

## Rules

1. If a helper writes a benchmark-owned file, the ownership must be explicit and the helper must fail closed on missing inputs.
2. If a helper depends on `simulation_result.json`, `benchmark_definition.yaml`, or `suggested_skills/`, the helper is not a general-purpose prompt primitive and usually belongs in the standalone training path, where it resolves the active overlay first.
3. If a helper reads render history, it must resolve a published bundle through the owning render contract, not through an unnamed latest alias alone.
4. If a helper is only useful for one role family, the role gate must be visible in the runtime config rather than inferred from prose.
5. If a helper needs a point coordinate from a render, it must validate the bundle snapshot before returning a world-space hit, and it must expose enough inputs to replay the exact bundle, view, and pixel choice later.
6. If a helper graduates into the main tool contract, this file keeps only a short cross-reference and removes the repeated detail.
7. If an experimental helper becomes a prompt default, it needs matching architecture documentation and observability coverage before it is treated as stable.

## Related docs

- [Agent tools](./tools.md)
- [Agent harness](./agent-harness.md)
- [Agent skills](./agent-skill.md)
- [Simulation and rendering](../simulation-and-rendering.md)
- [Observability](../observability.md)
