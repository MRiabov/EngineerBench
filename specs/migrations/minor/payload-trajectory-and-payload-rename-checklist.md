---
status: migration
---

# Payload and trajectory rename checklist

This migration converts the codebase from the old `moved object` and `motion forecast` naming to the new `payload` and `payload trajectory` vocabulary.

Use this checklist to track the implementation end to end. Keep compatibility aliases only while the migration is in flight.

## Checklist

### Core models

- [x] Rename `MovedObject` to `Payload` in `shared/models/schemas.py`.
- [x] Rename `MotionForecastContact` to `PayloadTrajectoryContact`.
- [x] Rename `MotionForecastAnchor` to `PayloadTrajectoryAnchor`.
- [x] Rename `MotionForecastTerminalEvent` to `PayloadTrajectoryTerminalEvent`.
- [x] Rename `MotionForecast` to `CoarsePayloadTrajectory`.
- [x] Rename `MovingPart` to `PayloadPart`.
- [x] Update `shared/models/__init__.py` to export the new names.
- [x] Keep compatibility aliases for the old class names only if the downstream surface still needs them.

### Core fields

- [x] Rename `AssemblyDefinition.motion_forecast` to `AssemblyDefinition.coarse_payload_trajectory`.
- [x] Rename `moving_part_names` to `payload_part_names` on the coarse and precise trajectory models.
- [x] Rename any property or derived accessor named `moving_parts` to `payload_parts` or `coarse_payload_parts`.
- [x] Rename config fields that store the coarse-path policy from `motion_forecast` to the final payload-trajectory policy name.

### Helper functions and methods

- [x] Rename `get_motion_forecast_policy()` to the final payload-trajectory policy getter.
- [x] Rename `_motion_forecast_policy_role_for_stage()` to the final payload-trajectory role helper name.
- [x] Rename `_validate_motion_forecast_budget()` to the final payload-trajectory budget helper name.
- [x] Rename `_payload_trajectory_definition_from_motion_forecast()` to a name that reflects the coarse payload trajectory source.
- [x] Rename `_validate_motion_forecast_clearance_from_artifacts()` to the final payload-trajectory clearance helper name.
- [x] Update validator method names and docstrings so they no longer describe the old vocabulary.

### Validation and runtime consumers

- [x] Update `worker_heavy/utils/file_validation.py` to use the new model and field names.
- [x] Update `worker_heavy/utils/payload_trajectory_validation.py` to use the renamed trajectory classes and fields.
- [x] Update `worker_heavy/simulation/payload_trajectory_monitor.py` to use the renamed anchor and trajectory types.
- [x] Update `worker_renderer/utils/payload_path_overlay.py` to resolve the renamed coarse trajectory field.
- [x] Update `controller/agent/node_entry_validation.py` to validate the renamed fields and helper functions.
- [x] Update `worker_heavy/simulation/builder.py` and `worker_heavy/utils/validation.py` if they still refer to the old class names.

### Config and templates

- [x] Rename `motion_forecast:` in `config/agents_config.yaml` to the final payload-trajectory policy key.
- [x] Update `shared/assets/template_repos/engineer/assembly_definition.yaml`.
- [x] Update any other starter templates that still expose the old field names.

### Seeds and fixtures

- [x] Update seeded `assembly_definition.yaml` files that still use `motion_forecast:`.
- [x] Update seeded `benchmark_definition.yaml` or fixture files that still use `moved_object`-style vocabulary where the new schema is expected.
- [x] Update `dataset/data/seed/role_based/*.json` prompts and criteria that still mention the old names in executable instructions.
- [x] Update mock responses and fixture files under `tests/integration/mock_responses/` that still assert the old names.

### Tests

- [x] Update integration tests that import the renamed classes.
- [x] Update tests that assert old error strings such as `assembly_definition.yaml.motion_forecast`.
- [x] Update tests that still use `motion_forecast:` YAML blocks in fixture setup.
- [x] Update tests that check the old helper or property names.

### Cleanup and verification

- [x] Run an `rg -n` sweep for `MovedObject`, `MotionForecast`, `motion_forecast`, `moving_part_names`, and `moved_object`.
- [x] Remove any compatibility alias that is no longer needed by the codebase.
- [x] Verify the narrowest relevant integration slice first, then widen only if the rename touches additional surfaces.
- [x] Leave a final note in the migration if any old names remain intentionally as historical seed data or temporary compatibility shims.

Remaining old-name matches are now expected only in historical seed/render artifacts and archival/spec documents that still describe the old contract surface.
