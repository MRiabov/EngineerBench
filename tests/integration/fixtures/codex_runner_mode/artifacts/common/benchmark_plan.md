## 1. Learning Objective

Demonstrate a valid benchmark row that keeps the integration fixture in a passable state.

## 2. Environment Geometry

- The fixture uses a compact, static workspace geometry.
- The benchmark payload stays inside the declared bounds.

## 3. Input Objective

- The input object is a simple cube fixture.

## 4. Objectives

- Keep the fixture deterministic.
- Preserve a minimal but valid benchmark contract.

## 5. Simulation Bounds

- The simulation bounds remain broad enough for the fixture geometry.

## 6. Constraints Handed To Engineering

- The downstream engineer-owned files should remain schema-valid.

## 7. Success Criteria

- The fixture row validates without workspace-contract errors.

## 8. Planner Artifacts

- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_script.py`

## 9. Part Metadata

- `fixture_box` is the only benchmark-owned part in this fixture.
