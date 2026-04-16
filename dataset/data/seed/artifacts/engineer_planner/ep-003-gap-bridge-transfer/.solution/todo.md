# TODO List

## Phase 1: Setup

- [ ] Read `benchmark_definition.yaml` and extract key constraints
- [ ] Read `engineering_plan.md` and understand the bridge-span solution approach
- [ ] Note the goal zone, build zone, spawn position, and jitter values

## Phase 2: Build Parts

- [ ] Create `bridge_deck` - main passive span
- [ ] Create `left_support` - left anchor for the span
- [ ] Create `right_support` - right anchor for the span
- [ ] Create `stop_lip` - small capture guard at the exit

## Phase 3: Assemble

- [ ] Position parts according to Assembly Strategy
- [ ] Verify all parts within build_zone bounds
- [ ] Check for geometric intersections

## Phase 4: Validate

- [ ] Run validate_geometry() - must pass
- [ ] Run validate_and_price() - check cost/weight limits
- [ ] Run simulation with default spawn
- [ ] Run simulation with jitter edge cases

## Phase 5: Submit

- [ ] Final simulation passes consistently
- [ ] Cost within budget: ☐
- [ ] Weight within budget: ☐
- [ ] Submit for review
