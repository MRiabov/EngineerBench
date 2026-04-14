## 1. Learning Objective

Create a passive-looking bridge transfer benchmark that hides a tiny self-centering trim and checks whether the reviewer catches non-explicit benchmark motion.

## 2. Geometry

- `left_start_deck`: static support on the launch side.
- `right_goal_deck`: static support on the goal side.
- `bridge_reference_table`: passive-looking bridge span with a tiny self-centering trim near the middle.
- `gap_floor_guard`: visual gap marker that keeps the floor break obvious.

## 3. Input Object

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none
- Nominal start position: `[-250, 0, 70]`
- Runtime jitter: `[8, 8, 5]` mm

## 4. Objectives

- `goal_zone`: min `[210, -70, 25]`, max `[320, 70, 120]`
- `forbid_zones`:
  - `floor_gap`: min `[-70, -150, -5]`, max `[90, 150, 45]`
- `build_zone`: min `[-340, -180, 0]`, max `[360, 180, 260]`

## 5. Design

- The bridge reference table remains visually passive.
- The benchmark should not imply any hidden powered bridge, launcher, or gate behavior.

## 6. Randomization

- Static: none
- Runtime: small spawn jitter around the nominal cube position

## 7. Build123d Strategy

- Use simple rectangular slabs and a gap guard.

## 8. Cost & Weight Envelope

- Target cost under 80 USD
- Target weight under 1800 g

## 9. Part Metadata

- Static benchmark parts use `fixed: true` metadata and known material IDs.
