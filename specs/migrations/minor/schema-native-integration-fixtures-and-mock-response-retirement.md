---
title: Schema-Native Integration Fixtures and Mock-Response Retirement
status: investigation
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-17T00:00:00Z'
---

# Schema-Native Integration Fixtures and Mock-Response Retirement

<!-- Investigation doc. No behavior change yet. -->

## Purpose

This migration moves integration fixture authoring from handwritten YAML and
mock-response corpus files to typed schema instances that are serialized to
YAML only at the edge.

The target contract is:

1. Core fixture content is authored as schema objects, not as nested dict
   literals or string-concatenated YAML blobs.
2. `benchmark_definition.yaml`, `assembly_definition.yaml`, and
   `payload_trajectory_definition.yaml` are emitted from typed models through a
   code-native serializer.
3. `tests/integration/mock_responses/` stops being the canonical source of
   truth for fixture semantics. If the corpus remains during transition, it is
   replay material or generated compatibility material, not the place where new
   fixture meaning is authored.
4. Integration tests, seed helpers, and normalization utilities all consume the
   same typed model boundary, which keeps fixture renames and schema changes
   local to the model layer.
5. The same schema-first shape also reduces future migration cost if test
   materialization later moves to a database-backed fixture store.

This is an authoring-contract migration, not a new validation algorithm. The
runtime schema validators already exist in `shared/models/schemas.py`; the gap
is that too many tests still construct fixture YAML by hand or route through a
mock-response corpus as if it were the source of truth.

## Problem Statement

The current integration fixture path still mixes model-backed contracts with
hand-authored YAML snapshots.

1. Large fixture bodies are still assembled in test code from raw dict
   literals and then dumped to YAML.
2. The mock-response corpus is still treated as a canonical authoring surface
   for many integration cases, which makes fixture edits difficult to localize.
3. The same logical contract appears in several places as slightly different
   YAML text, dict shapes, and serializer choices.
4. That duplication makes renames, removals, and schema tightening more
   expensive than they need to be.
5. A future database-backed fixture store would inherit the same drift if the
   typed schema is not the actual source of truth now.

The problem is not YAML itself. The problem is that YAML is still the authored
form instead of a serialization artifact produced from typed schema objects.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `controller/agent/mock_scenarios.py` and `controller/agent/mock_llm.py` | Load `tests/integration/mock_responses/` as the canonical scenario corpus. | The mock layer is still anchored to corpus files instead of typed fixture builders. |
| `tests/conftest.py` | Enforces mock-response startup checks by loading the scenario corpus. | The startup gate should validate schema-backed fixture material, not a hand-authored corpus convention. |
| `tests/integration/agent/helpers.py` | Builds seed and reviewer fixtures from inline dicts and ad hoc `yaml.safe_dump(...)` calls. | The helper layer should own typed builders and a reusable YAML emission seam. |
| `tests/integration/architecture_p0/test_architecture_p0.py`, `tests/integration/architecture_p0/test_planner_gates.py`, `tests/integration/architecture_p1/test_infrastructure.py`, `tests/integration/architecture_p1/test_manufacturing.py` | Construct core benchmark and payload YAML directly in test bodies. | The same logical contracts should come from typed models so fixture edits stay local. |
| `scripts/normalize_integration_mock_responses.py` | Normalizes YAML after the fact inside `tests/integration/mock_responses/`. | Normalization is maintenance tooling, not the authored fixture contract. |
| `scripts/validate_integration_mock_response_preflight.py` | Validates the mock-response corpus and referenced payload files against current node-entry and handoff contracts. | The corpus gate must follow the new schema-first fixture contract instead of assuming the corpus is canonical authoring surface. |
| `tests/integration/mock_responses/README.md` | Documents the mock-response directory as the fixture authoring surface. | The README should describe a generated or compatibility role, not canonical ownership. |
| `shared/models/schemas.py` | Already defines the typed benchmark, assembly, and payload contracts. | The model layer exists, but the repo does not yet treat it as the only authored source. |

## Proposed Target State

1. Fixture semantics are authored as typed schema instances in Python.
2. YAML emission is a serialization step, not the place where fixture meaning
   is defined.
3. A shared code-native helper emits canonical YAML from those schema objects
   for tests and seed materialization.
4. New integration fixture definitions do not hand-author nested dict trees for
   `BenchmarkDefinition`, `AssemblyDefinition`, or
   `PayloadTrajectoryDefinition`.
5. `tests/integration/mock_responses/` is no longer the canonical place where
   new fixture semantics are written.
6. If the mock-response corpus remains during transition, it is generated or
   replay-only material and must stay in sync with the same typed schema
   source.
7. Integration assertions continue to deserialize emitted YAML back into the
   same Pydantic models before making claims about behavior.
8. The schema-first path is reusable enough that a later database-backed test
   store can materialize the same models without redesigning the fixture
   contract.

## Required Work

### 1. Define the schema-first fixture seam

- Add or consolidate a small serializer helper that accepts schema instances
  and emits deterministic YAML for integration fixtures.
- Keep the helper model-driven. Do not let tests hand-roll their own YAML
  string assembly when a schema instance already exists.
- Prefer strongly typed builders for the common benchmark and payload fixture
  families so the authored source is a model object, not a dict literal.

### 2. Move representative fixture authorship to typed models

- Update `tests/integration/agent/helpers.py` so benchmark and reviewer seed
  fixtures are built from schema instances before they are serialized.
- Update representative P0 and P1 integration tests so the benchmark and
  payload YAML they write comes from typed models rather than from inline dicts.
- Keep the tests asserting on the same serialized file content and model
  validation outcomes, but make the source of that content schema-native.

### 3. Demote the mock-response corpus

- Reclassify `tests/integration/mock_responses/` as compatibility or replay
  material instead of canonical fixture authoring.
- Update `scripts/validate_integration_mock_response_preflight.py` so it
  validates the same schema-first fixture contract rather than preserving the
  corpus as the authoring source of truth.
- Update the loader and startup checks so they enforce the new schema-first
  contract instead of treating corpus files as the only source of truth.
- Keep the scenario loader fail-closed on malformed content, but do not let it
  become the only place where fixture semantics are defined.

### 4. Refresh normalization and seed maintenance

- Update `scripts/normalize_integration_mock_responses.py` or its successor so
  it normalizes schema-emitted YAML, not a separate hand-authored contract.
- Keep any seed helpers that need benchmark or payload YAML aligned with the
  same typed models and serializer path used by the integration suite.
- Remove dict-shaped fixture assembly where the schema already exists.

### 5. Update docs and corpus guidance

- Update `specs/integration-test-rules.md` so the contract clearly says that
  fixture meaning lives in typed models and YAML is just an emitted artifact.
- Update `tests/integration/mock_responses/README.md` so it no longer presents
  the corpus as the canonical authoring surface for new fixture semantics.
- Update any adjacent integration guidance that still tells maintainers to edit
  raw YAML first and model second.

### 6. Add regression coverage

- Add a round-trip regression that builds a benchmark fixture from a schema
  instance, emits YAML, reloads it, and validates it against the same model.
- Add a regression that proves the shared serializer preserves the expected
  benchmark and payload file shape.
- Add a regression that proves new fixture helpers do not require raw dict
  authoring for the core schema contracts.

## Non-Goals

- Do not change the runtime validation semantics of
  `BenchmarkDefinition`, `AssemblyDefinition`, or `PayloadTrajectoryDefinition`.
- Do not redesign the DSPy mock transport protocol in this migration.
- Do not migrate integration tests to a database-backed store yet.
- Do not remove the mock-response corpus outright unless the later
  implementation phase explicitly proves that no compatibility path is needed.
- Do not change the test boundary from HTTP-driven integration to unit-style
  model tests.
- Do not broaden this migration into a generic YAML formatting cleanup.

## Sequencing

The safe order is:

1. Add the shared schema-first serializer seam.
2. Move the seed helpers and a narrow pilot set of integration tests onto typed
   models.
3. Demote the mock-response corpus to compatibility or replay-only status.
4. Update the corpus guidance and normalization tooling.
5. Add the round-trip regressions and then sweep the remaining fixture authors.

## Acceptance Criteria

1. New benchmark and payload fixture definitions are authored as typed schema
   instances, not as nested dict literals.
2. YAML emission happens through a shared code-native path.
3. `tests/integration/mock_responses/` is no longer the canonical source of
   fixture semantics.
4. Integration tests still round-trip emitted YAML back through the same
   Pydantic models before asserting behavior.
5. The migration leaves fixture meaning centralized enough that later
   database-backed test materialization can reuse the same schema contracts.

## Migration Checklist

Use this checklist to track the implementation from the first serializer seam
through corpus demotion and regression coverage. Do not close the migration
until every unchecked item is either completed or explicitly waived with a
written rationale.

### Schema and serialization

- [ ] Add a shared schema-first YAML serializer for integration fixtures.
- [ ] Move core benchmark, assembly, and payload fixture builders to typed
  model instances.
- [ ] Remove dict-shaped fixture assembly where a schema class already exists.

### Corpus demotion

- [ ] Update the mock-response loader and startup checks so the corpus is
  compatibility material, not canonical fixture ownership.
- [ ] Refresh `tests/integration/mock_responses/README.md` to match the new
  contract.
- [ ] Update normalization tooling so it operates on schema-emitted YAML.

### Tests and regressions

- [ ] Migrate representative P0 and P1 tests to the schema-first fixture path.
- [ ] Add round-trip regressions for emitted benchmark and payload YAML.
- [ ] Verify the same typed model validates the authored object and the emitted
  file content.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

- `shared/models/schemas.py`
- `tests/integration/agent/helpers.py`
- `controller/agent/mock_scenarios.py`
- `controller/agent/mock_llm.py`
- `tests/conftest.py`
- `scripts/normalize_integration_mock_responses.py`
- `scripts/validate_integration_mock_response_preflight.py`
- `tests/integration/mock_responses/README.md`
- `specs/devtools.md`
- `specs/integration-test-rules.md`
- representative integration tests under `tests/integration/architecture_p0/`
  and `tests/integration/architecture_p1/`
