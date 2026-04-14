---
title: Solution Motor Actuation and Backend Parity
status: migration
agents_affected:
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-04T08:39:29Z'
---

# Solution Motor Actuation and Backend Parity

<!-- Migration tracker. Check items conservatively as implementation lands. -->

## Purpose

This migration is the runtime follow-on to
[COTS Geometry Import Runtime and Motor MVP](./cots-geometry-import-runtime-and-motor-mvp.md).
The geometry class, catalog resolution, and proxy geometry already exist. What
remains is making solution-authored motors behave as first-class actuated parts
on both supported physics backends.

The target contract is:

1. engineer-authored solution files can declare a motorized moving part once in
   `assembly_definition.yaml`,
2. the same moving-part contract drives real backend motion in both MuJoCo and
   Genesis,
3. solution scripts do not need backend-specific motor branches,
4. controller functions, power gating, and overload monitoring all consume the
   same shared motor contract,
5. unsupported motor mappings fail closed before a simulation can pretend to
   have succeeded,
6. the shared backend seam stays small unless a concrete motor capability gap
   proves that it must grow,
7. the first release is verified through real integration tests, not unit
   stubs or template-only checks.

This is a backend-parity change, not a new motor schema. The repo already knows
how to describe moving parts in `AssemblyDefinition.final_assembly` and how to
derive `moving_parts` from that contract. The gap is that MuJoCo already
materializes the motion contract more completely than Genesis does.

## Problem Statement

The current system has a solution motor contract, but the runtime behavior is
not fully symmetric across backends.

1. `shared/models/schemas.py` already turns `final_assembly` into typed
   `MovingPart` rows with `MotorControl` data.
2. `worker_heavy/utils/validation.py` already converts moving parts into
   controller inputs and passes them into simulation.
3. `worker_heavy/simulation/builder.py` already emits MuJoCo actuators from
   moving parts and already derives motor limits from COTS motor data.
4. `worker_heavy/simulation/genesis_backend.py` already understands some MJCF
   actuators, but its JSON scene path still treats motor entries more like
   metadata than a fully materialized solution actuator graph.
5. `worker_heavy/simulation/loop.py` already power-gates controls and checks
   overload through the shared backend API, so the gating logic is not the
   blocker.

That split creates four practical problems:

1. agents can author a motorized solution that works on one backend but not the
   other,
2. solution authors may accidentally rely on backend-specific behavior,
3. runtime validation can accept a motor contract that the backend cannot
   actually execute,
4. the simulation result can look motor-aware even when the backend never had a
   real controllable motion axis.

The architecture answer is to keep the solution contract shared and backend
specific only at the materialization layer. MuJoCo and Genesis should both
consume the same motion intent, not different solution languages.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `shared/models/schemas.py` | `AssemblyDefinition.moving_parts` already derives moving parts from the explicit motion forecast, and the motion contract is typed. | This is the canonical solution motion contract and should remain the source of truth. |
| `shared/simulation/backends.py` | Shared `apply_control`, `get_actuator_state`, and `get_all_actuator_names` seams already exist. | The backend seam is probably sufficient; do not expand it unless a specific motor capability is missing. |
| `worker_heavy/utils/validation.py` | Converts moving parts into time-based controller inputs and sends them to simulation. | This is the correct solution-level control path, but it depends on backend materialization working everywhere. |
| `worker_heavy/simulation/builder.py` | MuJoCo emits actuators from moving parts; Genesis serializes motor metadata and wire data into JSON. | MuJoCo is the baseline, but Genesis still needs the same solution contract to become a real actuator graph. |
| `worker_heavy/simulation/genesis_backend.py` | Parses MJCF actuators and applies control when an entity exists, but JSON motor entries are still not a full solution actuation path. | Genesis needs to materialize the same solution motor contract, not just remember that motors were declared. |
| `worker_heavy/simulation/loop.py` | Power gating, overload monitoring, and failure propagation are backend-agnostic. | The loop can already host the contract; it needs both backends to report consistent actuator behavior. |
| `tests/worker_heavy/simulation/test_genesis_builder_electronics.py` | Exercises backend-local Genesis motor/control state behavior. | It proves the Genesis backend surface exists, but not that solution-authored moving parts materialize with the same contract as MuJoCo. |
| `worker_heavy/simulation/test_dynamic_control.py` and `tests/worker_heavy/simulation/test_motor_overload.py` | Component-level coverage exists for actuator control and overload behavior. | We need end-to-end parity coverage through the real worker entrypoints, not just backend-local tests. |
| `tests/integration/architecture_p1/test_electronics_full.py` | Covers electromechanical validation and power budget behavior. | This is the right integration layer to extend with backend parity cases. |

## Proposed Target State

1. A solution authored in `solution_script.py` and `assembly_definition.yaml`
   can declare motorized moving parts once and run under either backend without
   solution-code branches.
2. `MuJoCoSimulationBuilder` remains the rigid-body baseline implementation for
   the shared motor contract.
3. `GenesisSimulationBuilder` materializes the same moving-part contract into a
   real controllable motion graph, not just metadata.
4. `apply_control()`, `get_actuator_state()`, and `get_all_actuator_names()`
   report motor state consistently enough for power gating and overload checks
   to behave the same way on both backends.
5. The existing motor control modes remain the supported set:
   `CONSTANT`, `SINUSOIDAL`, and `ON_OFF`.
6. Motor force limits, velocity estimates, and overload thresholds continue to
   come from the same COTS motor data that the geometry import layer already
   uses.
7. Unsupported or unresolved motor mappings fail closed before simulation or
   validation can claim success.
8. The shared `PhysicsBackend` protocol stays stable unless an explicit motor
   parity test proves that it is missing a required capability.

## Required Work

### 1. Lock the solution motor contract

- Treat `AssemblyDefinition.final_assembly`, `AssemblyDefinition.moving_parts`,
  and `AssemblyPartConfig.control` as the single solution motor contract.
- Keep the contract explicit about solution-owned labels and the backend-facing
  actuator names those labels produce.
- Do not add a second solution motor schema just for Genesis.
- If the syntax needs an example, add it to the new
  `electromechanics-syntax` skill instead of the starter workspace so the
  solution template stays neutral.

### 2. Keep MuJoCo as the reference implementation

- Preserve the current MuJoCo builder path as the reference for actuator naming,
  force-range derivation, and control-mode mapping.
- Keep MuJoCo behavior aligned with the existing motor data source in
  `shared/cots/parts/motors.py`.
- Do not regress the current MuJoCo motion path while adding backend parity.

### 3. Materialize the same contract in Genesis

- Extend `GenesisSimulationBuilder` and `GenesisBackend.load_scene()` so a
  solution motor becomes a real controllable mechanism, not only a serialized
  metadata entry.
- Choose the minimal representation that lets Genesis expose the same solution
  motor behavior contract as MuJoCo.
- If the cleanest route is to emit an MJCF-compatible motorized subscene for the
  rigid-body case, use that instead of inventing a third motor format.
- If the JSON path remains the primary Genesis path, teach it to instantiate the
  same joint/actuator semantics from the shared motor contract.

### 4. Normalize control and reporting

- Make `apply_control()` and `get_actuator_state()` return comparable results on
  both backends for solution motors.
- Make `get_all_actuator_names()` expose the same solution motor identity that
  `SimulationLoop` uses when power gating controls.
- Keep controller semantics in `worker_heavy/utils/validation.py` backend
  agnostic.
- Keep overload monitoring in `worker_heavy/simulation/loop.py` backend
  agnostic.

### 5. Fail closed on unsupported motor configs

- Reject moving parts whose motion-axis, joint, or actuator mapping cannot be resolved.
- Reject control modes that the backend cannot represent faithfully.
- Reject a scene that silently downgrades a motorized solution part to static
  geometry.
- Do not let a missing mapping degrade into a fake success with zero motion.
- Make the validation and file-validation path report the same fail-closed
  result before simulation starts when a motor mapping is missing, unsupported,
  or inconsistent with the declared COTS motor data.

### 6. Add integration coverage for solution motors

- Add or refresh integration tests that exercise the same motorized solution
  contract through the real worker entrypoints.
- Prove the MuJoCo path works for a motorized solution with at least one
  controller mode and a meaningful actuator response.
- Prove the Genesis path accepts the same solution contract and exposes the
  same motor identity and control behavior at the backend boundary.
- Prove that power gating suppresses the motor when the electrical contract is
  absent or disabled.
- Prove that sustained overload still produces the expected failure reason.
- Prove that unresolved motor mappings fail closed.

### 7. Update starter material and guidance

- Add a visible solution motor example to the new `electromechanics-syntax`
  skill if the implementation needs authors to see the supported contract.
- Keep the example concise and backend-neutral.
- Update prompt-facing guidance only if the electromechanics skill content
  actually changes.
- Refresh the integration-test catalog so the new parity coverage is recorded
  explicitly, either by extending the existing electromechanical rows or by
  adding a dedicated solution-motor backend-parity row.

## Non-Goals

- Do not reopen the COTS geometry import contract or the motor proxy geometry.
- Do not add a separate motor-only agent workflow.
- Do not add firmware, embedded code, or a full EDA stack.
- Do not add new motor families.
- Do not require benchmark-owned fixtures to obey the engineer solution motor
  rules.
- Do not grow the shared backend protocol unless a parity test proves that it is
  missing a real motor capability.

## Sequencing

This migration should land in a tight order so the new path stays testable.

The safe order is:

1. Confirm the exact solution motor contract in `AssemblyDefinition` and the
   builder/validation mapping from part names to actuator names.
2. Keep the MuJoCo path unchanged except where naming or shared data alignment
   must be tightened.
3. Materialize the Genesis solution motor path from the same contract.
4. Normalize backend actuator state reporting so power gating and overload
   checks observe the same semantics.
5. Add fail-closed validation for missing or unsupported motor mappings.
6. Add integration tests for both backends plus negative cases.
7. Update starter material and docs only after the runtime path is stable.

## Acceptance Criteria

1. An engineer-authored solution can declare a motorized moving part once and
   run without backend-specific code.
2. The same motorized solution contract works under MuJoCo and Genesis.
3. The backend reports enough actuator state for power gating and overload
   detection to behave consistently.
4. Unpowered motors remain gated off instead of moving anyway.
5. Sustained overload still surfaces the expected `MOTOR_OVERLOAD` failure.
6. Missing or unsupported motor mappings fail closed before they can look like a
   valid solution.
7. The integration suite proves the solution motor path through the repo's real
   test entrypoints.

## Migration Checklist

### Contract

- [x] Lock the solution motor contract in `AssemblyDefinition` and the moving
  part mapping.
- [ ] Keep the MuJoCo reference behavior stable while the parity work lands.
- [x] Define the Genesis motor materialization strategy from the same shared
  contract.
- [x] Add the visible motor example to the new `electromechanics-syntax` skill
  if authors need a concrete reference.

### Runtime

- [x] Materialize solution motors as real controllable motion axes in Genesis.
- [x] Normalize `apply_control()`, `get_actuator_state()`, and
  `get_all_actuator_names()` across backends.
- [ ] Keep power gating and overload monitoring backend-agnostic.
- [x] Fail closed on unresolved or unsupported motor mappings.
- [x] Keep the validation and file-validation path fail-closed on missing or
  incompatible motor mappings before simulation starts.

### Validation

- [ ] Preserve the shared validation path that turns moving parts into
  controller inputs.
- [x] Add a validation failure for missing or invalid motor mappings before
  simulation starts.
- [ ] Make the validation failure surface the same motor identity and control
  mode context that the simulation path uses.

### Tests

- [x] Add or refresh integration tests for a motorized solution on MuJoCo.
- [x] Add or refresh integration tests for the same solution contract on
  Genesis.
- [x] Add negative integration coverage for unresolved motor mappings.
- [x] Add regression coverage for unpowered and overloaded motors.
- [x] Refresh `specs/integration-test-list.md` so the solution-motor parity row
  is explicit and tied to the actual integration coverage.

### Docs

- [ ] Update the electromechanics-syntax skill if authors need an explicit
  motor example.
- [ ] Update the motor and simulation architecture docs if the final contract
  needs wording changes.
- [ ] Refresh the integration-test catalog if a dedicated backend-parity row is
  clearer than extending the existing electromechanical rows.

## File-Level Change Set

The implementation should touch the smallest realistic set of files that
enforce the new contract:

- `shared/models/schemas.py`
- `worker_heavy/utils/validation.py`
- `worker_heavy/simulation/builder.py`
- `worker_heavy/simulation/genesis_backend.py`
- `worker_heavy/simulation/loop.py`
- `tests/worker_heavy/simulation/test_dynamic_control.py`
- `tests/worker_heavy/simulation/test_motor_overload.py`
- `tests/worker_heavy/simulation/test_genesis_builder_electronics.py`
- `tests/integration/architecture_p1/test_electronics_full.py`
- `.agents/skills/electromechanics-syntax/SKILL.md`
- `.agents/skills/electromechanics-syntax/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
- `specs/architecture/simulation-and-rendering.md`
- `specs/architecture/electronics-and-electromechanics.md`
- `specs/integration-test-list.md`
- `worker_heavy/utils/file_validation.py` if the final validation contract needs
  an explicit fail-closed motor-mapping rule
- `shared/simulation/backends.py` only if a concrete parity test proves the
  shared backend seam is missing a required motor capability
