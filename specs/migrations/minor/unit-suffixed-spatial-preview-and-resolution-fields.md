---
title: Unit-Suffixed Spatial, Preview, and Resolution Fields
status: investigation
agents_affected:
  - benchmark_planner
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_coder
  - engineer_plan_reviewer
  - engineer_execution_reviewer
added_at: '2026-04-17T00:00:00Z'
---

# Unit-Suffixed Spatial, Preview, and Resolution Fields

<!-- Investigation doc. No behavior change yet. -->

## Purpose

This migration makes the repo's application-facing numeric field names carry
their units explicitly instead of relying on context.

The target contract is:

1. benchmark geometry and motion fields use `_mm` for length values,
2. preview and camera fields use `_deg` for angles,
3. render resolution and pixel-space fields use `_px`,
4. the Python models and YAML fixtures agree on the same field names,
5. temporary compatibility aliases may exist during transition, but the new
   suffixed names are the canonical serialization surface.

The repo already uses explicit suffixes in a number of places, such as
`pos_mm`, `rot_deg`, `position_tolerance_mm`, and `rotation_tolerance_deg`.
This migration closes the remaining naming gaps so users do not need to infer
units from surrounding text.

## Problem Statement

The current contract mixes explicit unit suffixes with bare spatial and
preview names.

1. Benchmark YAML still exposes bare fields such as `simulation_bounds`,
   `goal_zone`, `build_zone`, `start_position`, `runtime_jitter`, and
   `radius`.
2. Supporting Python models still surface the same contract through names
   such as `min`, `max`, `pos`, `size`, `width`, `height`, `orbit_pitch`, and
   `orbit_yaw`.
3. Agent-facing preview and render request models also expose bare angle and
   pixel names, even though the values are already interpreted as degrees or
   pixels by the surrounding code.
4. The result is a contract that is numerically clear but semantically noisy:
   the values are measured, but the names do not say what the measurement is.
5. That inconsistency is especially costly in agent workflows, where the same
   field name must be copied between YAML, prompts, generated scripts, and
   validation code.

The correct state is to encode the unit in the field name wherever the value
represents a measurable quantity.

## Current-State Inventory

| Area | Current names | Why it must change |
| -- | -- | -- |
| `shared/models/schemas.py` benchmark contract | `BoundingBox.min`, `BoundingBox.max`, `ObjectivesSection.goal_zone`, `ObjectivesSection.build_zone`, `ForbidZone.min`, `ForbidZone.max`, `StaticRandomization.radius`, `Payload.start_position`, `Payload.runtime_jitter`, `BenchmarkDefinition.simulation_bounds` | These values are serialized into benchmark YAML and are currently unitless in the name even though they are physical lengths or length envelopes. |
| `shared/models/schemas.py` scene contract | `EntityDefinition.pos`, `EntityDefinition.min`, `EntityDefinition.max`, `EntityDefinition.size`, `CableDefinition.radius` | These fields describe geometry in world coordinates and must carry explicit length units in the model contract. |
| `shared/workers/workbench_models.py` | `BuildZone.min`, `BuildZone.max` | The helper model exposes the same geometry contract as the benchmark YAML and should use the same unit-bearing names. |
| `shared/agents/config.py` and `config/agents_config.yaml` | `RenderResolutionConfig.width`, `RenderResolutionConfig.height` | These are pixel dimensions in the agent render policy and should be named as pixel values, not generic widths and heights. |
| `shared/workers/schema.py` | `PreviewViewSpec.orbit_pitch`, `PreviewViewSpec.orbit_yaw`, `PreviewDesignRequest.orbit_pitch`, `PreviewDesignRequest.orbit_yaw`, `PreviewWorkflowParams.orbit_pitch`, `PreviewWorkflowParams.orbit_yaw`, `HeavyPreviewParams.orbit_pitch`, `HeavyPreviewParams.orbit_yaw`, `RenderBundlePointPickRequest.pixel_x`, `RenderBundlePointPickRequest.pixel_y`, `RenderBundlePointPickRequest.image_width`, `RenderBundlePointPickRequest.image_height`, and the matching result fields | These are agent-facing preview and render RPC fields that already carry degrees or pixels in practice, but the field names do not say so. |
| `shared/assets/template_repos/**` | `benchmark_definition.yaml`, `assembly_definition.yaml`, `benchmark_assembly_definition.yaml`, and preview snippets that still use bare spatial keys | Starter templates must reflect the canonical contract so new workspaces do not reintroduce the old names. |
| `dataset/data/seed/artifacts/**` | Seeded `benchmark_definition.yaml`, `assembly_definition.yaml`, and `benchmark_assembly_definition.yaml` files under benchmark and engineer datasets | Seed fixtures are executable contract examples. They must show the suffixed names, not the deprecated ones. |
| `tests/integration/mock_responses/**` | Mock response YAML that still uses the bare names | Integration fixtures must stay aligned with the canonical schema so contract tests continue to exercise the renamed fields. |
| `config/prompts.yaml` and related docs | Prompt text that still instructs agents to write `simulation_bounds`, `radius`, `runtime_jitter`, `start_position`, or bare preview fields | Prompted agent output is part of the public contract, so the wording must match the new serialized names. |
| `worker_heavy/utils/file_validation.py` and `worker_heavy/utils/validation.py` | Validation logic and error strings that reference the current bare names | The runtime gate must validate the renamed fields and continue to fail closed on malformed geometry. |

<!--Human note: I think pixel_x/y is straightforward?-->

## Proposed Target State

1. Every benchmark-facing physical length field is named with `_mm`.
2. Every benchmark-facing angle field is named with `_deg`.
3. Every agent-facing pixel coordinate or resolution field is named with `_px`.
4. Python models continue to accept the old names only as temporary aliases
   while the migration is in flight.
5. New YAML fixtures, templates, prompts, and validation errors serialize the
   suffixed names only.
6. No numeric values change during the rename; only the field names and their
   compatibility aliases change.

Example shape:

```yaml
objectives:
  goal_zone_mm:
    min_mm: [27.0, -6.0, 6.0]
    max_mm: [37.0, 6.0, 14.0]
payload:
  start_position_mm: [-30.0, 0.0, 24.0]
  runtime_jitter_mm: [2.0, 2.0, 1.0]
  static_randomization:
    radius_mm: [4.0, 6.0]
```

## Required Work

### 1. Rename the benchmark and scene schemas

- Update `shared/models/schemas.py` so the benchmark and scene models expose
  suffixed field names for every measured quantity.
- Preserve backward compatibility with aliases only while the migration is in
  flight.
- Keep the validation rules unchanged apart from the new field names and
  error messages.

### 2. Rename the agent preview and render schemas

- Update `shared/workers/schema.py` so preview angles, pixel coordinates, and
  resolution values expose explicit unit suffixes.
- Update `shared/agents/config.py` so render resolutions use explicit pixel
  names in both the model and YAML loader.
- Keep the controller and worker RPCs aligned with the renamed fields so
  agent tool calls remain round-trippable.

### 3. Update runtime consumers

- Update `worker_heavy/utils/file_validation.py` and
  `worker_heavy/utils/validation.py` to read the renamed contract fields.
- Update any scene-building or render-query helpers that still read the bare
  field names.
- Keep geometric validation fail-closed during the rename.

### 4. Refresh templates, seeds, and mocks

- Update the starter repos under `shared/assets/template_repos/`.
- Update seeded benchmark and engineering artifacts under
  `dataset/data/seed/artifacts/`.
- Update integration mock responses under `tests/integration/mock_responses/`.

### 5. Refresh prompts and docs

- Update `config/prompts.yaml` to describe the renamed contract fields.
- Update any architecture or acceptance-criteria docs that still teach the
  bare names as canonical output.

### 6. Add compatibility coverage

- Add regression coverage proving that the old names still load through the
  temporary aliases.
- Add regression coverage proving that new serialized output uses the suffixed
  names.
- Add one negative case for each affected contract family so a bare old name
  does not become the new canonical output by accident.

## Non-Goals

- Do not change coordinate systems, unit scales, or numeric values.
- Do not change simulation physics, render behavior, or benchmark solvability.
- Do not rename unrelated counts, durations, percentages, costs, or token
  budgets that already have clear semantic units.
- Do not keep the compatibility aliases permanently; this migration is a
  transition, not a new dual-name contract.

## Sequencing

The safe order is:

1. Add suffixed field names and aliases in the Python models.
2. Update runtime consumers and validation logic to read the new names.
3. Rewrite templates, seeds, and mock fixtures.
4. Update prompt text and contract documentation.
5. Remove the old aliases only after the updated fixtures and tests are
   stable.

## Acceptance Criteria

1. Benchmark geometry and payload YAML serializes with explicit unit suffixes.
2. Agent-facing preview and render schemas serialize degrees and pixels with
   explicit suffixes.
3. The runtime accepts legacy names only through temporary aliases.
4. The starter templates and seeded fixtures no longer teach the bare names
   as canonical.
5. Validation errors and prompt text refer to the suffixed names.

## Migration Checklist

### Schema rename

- [ ] Rename benchmark and scene fields in `shared/models/schemas.py`.
- [ ] Rename preview and render fields in `shared/workers/schema.py`.
- [ ] Rename render resolution fields in `shared/agents/config.py`.

### Runtime consumers

- [ ] Update `worker_heavy/utils/file_validation.py` to validate the renamed
  benchmark contract.
- [ ] Update `worker_heavy/utils/validation.py` and any scene-builder helpers
  that still read the bare geometry names.
- [ ] Update any controller or worker request/response helpers that still
  surface the bare preview field names.

### Fixtures and docs

- [ ] Refresh `shared/assets/template_repos/**` to use the suffixed names.
- [ ] Refresh `dataset/data/seed/artifacts/**` to use the suffixed names.
- [ ] Refresh `tests/integration/mock_responses/**` to use the suffixed names.
- [ ] Refresh `config/prompts.yaml` and any affected architecture docs.

### Verification

- [ ] Add regression coverage for legacy-name compatibility.
- [ ] Add regression coverage for suffixed serialization.
- [ ] Run the narrowest relevant integration slice that exercises benchmark
  YAML validation and the agent preview/render contract.

## File-Level Change Set

- `shared/models/schemas.py`
- `shared/workers/workbench_models.py`
- `shared/workers/schema.py`
- `shared/agents/config.py`
- `worker_heavy/utils/file_validation.py`
- `worker_heavy/utils/validation.py`
- `shared/simulation/scene_builder.py`
- `shared/assets/template_repos/benchmark_generator/benchmark_definition.yaml`
- `shared/assets/template_repos/benchmark_generator/benchmark_assembly_definition.yaml`
- `shared/assets/template_repos/engineer/assembly_definition.yaml`
- `shared/assets/template_repos/engineer/benchmark_assembly_definition.yaml`
- `config/agents_config.yaml`
- `config/prompts.yaml`
- `dataset/data/seed/artifacts/**/benchmark_definition.yaml`
- `dataset/data/seed/artifacts/**/assembly_definition.yaml`
- `dataset/data/seed/artifacts/**/benchmark_assembly_definition.yaml`
- `tests/integration/mock_responses/**/benchmark_definition.yaml`
- `tests/integration/mock_responses/**/assembly_definition.yaml`
- `tests/integration/mock_responses/**/benchmark_assembly_definition.yaml`
