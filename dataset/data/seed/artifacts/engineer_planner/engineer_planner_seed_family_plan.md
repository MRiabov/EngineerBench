# Engineer Planner Seed Family Plan

## Purpose

This document defines a practical way to build about 100 `engineer_planner`
eval seeds without hand-authoring 100 unrelated benchmarks.

The goal is to maximize variation in planning difficulty while keeping the
benchmark review burden manageable and the seed structure contract-valid.

## Corpus Shape

The corpus should be organized as a set of benchmark families, not as a flat
list of unrelated tasks.

Each seed should follow this structural pattern:

1. A benchmark family is authored and reviewed on the benchmark side.
2. The approved benchmark bundle is frozen as read-only context.
3. A matching `engineer_planner` seed is created from that approved bundle.
4. The engineer row uses the standard hard-entry bundle for this role:
   - `engineering_plan.md`
   - `todo.md`
   - `benchmark_definition.yaml`
   - `assembly_definition.yaml`
   - `benchmark_assembly_definition.yaml`
   - `benchmark_script.py`
5. The row is validated before the family sweep continues.

The benchmark side and the engineer-planner side should stay coupled by
family, but not by file identity. Each row should have its own approved
benchmark instance and its own engineer-planner seed bundle.

## Design Rules

- One family means one core physical principle.
- Variants within a family should change one dominant difficulty axis at a
  time.
- Do not mix two unrelated benchmark families in one row.
- Prefer passive or near-passive mechanics first.
- Reserve interaction-heavy cases for a smaller subset of the corpus.
- Keep benchmark-owned fixtures read-only in every engineer seed.
- Keep the engineer-planner seed files exact and starter-like, not solved.
- Make the row id reveal the family and variant so the corpus is easy to
  audit later.

## Recommended Distribution

Use the active families to build about 100 seeds in total.

The recommended split is:

- 80 passive or mostly passive rows.
- 20 advanced rows with tighter geometry or interaction constraints.

This keeps most of the corpus cheap to review while still teaching the model
to handle harder benchmark shapes. Treat the per-family target rows as a
baseline and add extra variants to the strongest families until the corpus
reaches roughly 100 total rows.

## Family Matrix

| Family | Core benchmark shape | Main variation knobs | Suggested difficulty | Target rows |
| -- | -- | -- | -- | -- |
| `gap_bridge` | Separate start and goal platforms with a gap between them. | Gap width, bridge span, platform height mismatch, support lip depth, payload radius, spawn offset. | Easy to medium. | 10 |
| `central_bypass` | A central blocker sits between spawn and goal. | Blocker width, blocker height, route side, corridor width, goal shift, forbid-zone inflation. | Easy to medium. | 10 |
| `narrow_funnel` | A wide capture area narrows into a tight goal throat. | Throat width, funnel angle, capture mouth size, sleeve length, payload size, jitter envelope. | Medium. | 10 |
| `lower_bin` | The payload starts elevated and must land in a lower bin or catch zone. | Drop height, bin offset, deflector angle, rebound damping, lip geometry, release alignment. | Medium. | 10 |
| `gravity_chute` | A payload drops into an upper inlet and slides through a guided chute to a lower outlet or catch tray. | Chute slope, inlet height, chute length, bend count, wall height, throat width, exit offset. | Easy to medium. | 10 |
| `spiky_descent` | The route descends through spike-like obstacles and forbid zones into a lower goal basin. | Start height, descent slope, spike count, obstacle spacing, forbid-zone inflation, landing basin depth. | Medium. | 10 |
| `clearance_gate` | A long object must pass through a window or gate in a wall. | Window width, window height, wall thickness, rod length, approach angle, tilt tolerance. | Medium. | 10 |
| `s_corridor` | Two or more offset obstacles force a bent route. | Obstacle count, offsets, bend angle, pinch width, dead-end length, goal placement. | Medium. | 10 |
| `terrain_ridge` | The route crosses a bump, ridge, shallow step, or slope break. | Ridge height, slope length, crest radius, friction, start elevation, catch zone shape. | Medium to hard. | 10 |
| `post_capture` | The goal is centered around a post or ring-like target. | Post diameter, ring inner and outer diameter, concentricity offset, capture depth, landing pad size. | Harder precision case. | 10 |

### `gap_bridge`

This family teaches a planner to span empty space cleanly.

Good variants include:

- Short gap, wide bridge, generous tolerance.
- Wider gap with the same payload and a tighter support envelope.
- Small bridge span with a slightly larger payload radius.
- Bridge placement shifted left or right relative to the payload line.

Avoid turning this into a different family by adding a blocker or funnel.
The core question should remain: can the design bridge a void without
falling through?

### `central_bypass`

This family teaches route choice around a fixed obstruction.

Good variants include:

- Blocker centered exactly between spawn and goal.
- Blocker shifted so the path must favor the left side.
- Blocker shifted so the path must favor the right side.
- Blocker widened just enough to squeeze the free-space corridor.

Avoid adding a shelf or a lower-bin drop. The important signal is lateral
avoidance around the blocker.

### `narrow_funnel`

This family teaches precision capture and throat alignment.

Good variants include:

- A wide mouth that reduces to a narrow throat.
- A long throat with a slightly wider entry.
- A short funnel with a tighter final sleeve.
- A payload that barely fits the throat under worst-case radius.

The main variation should be throat width or throat length, not a totally new
obstacle layout.

### `lower_bin`

This family teaches controlled release or redirection into a lower target.

Good variants include:

- Higher drop with a wide catch bin.
- Lower drop with a tighter bin mouth.
- Deflector angled to send the payload into the bin.
- Escape lip added to prevent overshoot.

The important signal is gravity-aware redirection, not flat transfer.

### `gravity_chute`

This family teaches a planner to keep a payload inside a strictly downward
guided channel.

Good variants include:

- A straight, shallow chute with a generous inlet.
- A slightly steeper chute that keeps the same outlet.
- A single-bend chute that still drains cleanly into the lower target.
- A narrower throat that increases jam risk without changing the underlying
  descent.

Avoid turning this into a lower-bin family or a generic corridor problem. The
key question is whether the payload can remain guided through a continuous
downward chute without bouncing out or hanging up.

### `spiky_descent`

This family teaches downhill transport through a dense field of obstacles and
forbid zones.

Good variants include:

- Start height changed while keeping the same descending footprint.
- Descent slope made slightly steeper while keeping the same horizontal span.
- Spike count or spacing tightened to create a more cluttered downhill route.
- Forbid-zone placement shifted or inflated to force lateral avoidance while
  descending.
- Landing basin made shallower or deeper.
- Run-out region shortened to force a more compact downhill design.

The family should remain a descent problem with obstacle avoidance, not an
ascent problem, a gap bridge problem, or a terrain ridge problem.

### `clearance_gate`

This family teaches a planner to respect long-object clearance.

Good variants include:

- Longer rod with the same gate opening.
- Slightly narrower window with the same rod length.
- Wall thickness changed while keeping the same opening center.
- Approach angle shifted so the planner must account for tilt.

The key question is whether the object can pass through the opening without
world-space cheating.

### `s_corridor`

This family teaches routing through constrained free space.

Good variants include:

- Two blockers that create one clear corridor.
- Three blockers that create a bent or S-shaped corridor.
- A pinch point that is still contract-valid but tight.
- A goal zone that is laterally offset from the corridor exit.

The path should remain a path-planning problem, not a pure clearance problem.

### `terrain_ridge`

This family teaches the planner to cope with a terrain discontinuity.

Good variants include:

- A shallow bump in the middle of an otherwise flat route.
- A ridge with a rounded crest.
- A mild slope break that changes the effective launch or roll behavior.
- A start height that gives the solver a non-flat descent into the ridge.

The important signal is terrain handling, not obstacle avoidance.

### `post_capture`

This family teaches alignment around a goal-side obstacle or capture post.

Good variants include:

- A ring that must settle around a post.
- A post that sits inside a shallow goal cradle.
- A small concentricity offset that the design must absorb.
- A tighter post diameter with the same outer goal region.

This family should remain a capture-and-settle case, not a generic funnel.

## Variant Ladder

Within every family, keep the variants in a clear difficulty progression:

1. Easy: generous geometry, wide tolerances, obvious route.
2. Medium: one main dimension tightens or shifts.
3. Hard: one geometry constraint and one secondary constraint tighten
   together.

A good family should have a visible ramp from easy to hard without changing
its core physical principle.

## Seed Naming Convention

Use names that expose both the family and the variant.

Examples:

- `ep-gap-bridge-01`
- `ep-gap-bridge-07`
- `ep-central-bypass-03`
- `ep-gravity-chute-01`

The exact prefix can follow local corpus conventions, but the family and
variant should be obvious from the id.

## Seed Production Workflow

1. Pick one family.
2. Author the benchmark variant and review it to completion.
3. Freeze the approved benchmark bundle.
4. Create the matching `engineer_planner` seed bundle.
5. Keep the engineer-planner starter files exact and unsolved.
6. Record the row in the dataset with the family name and variant id.
7. Validate the single row with `scripts/validate_eval_seed.py`.
8. Validate the whole family slice.
9. Only then move to the next family.

Do not batch all 100 rows before the first family passes. Fix each family while
the context is still local.

## Coverage Rules

- Keep at least one family for each of these ideas:
  - bridging a gap,
  - bypassing an obstacle,
  - narrowing a goal,
  - dropping into a lower target,
  - feeding through a gravity-fed chute,
  - clearing a gate or window,
  - routing through a bent corridor,
  - surviving a terrain discontinuity,
  - capturing around a post.
- Keep the majority of rows in the passive families.
- Keep the benchmark geometry family-pure; do not blend two ideas just to fill
  quota.

## Validation Rules

- Every seed must be schema-valid before it is counted.
- Every seed must have a reviewed benchmark bundle behind it.
- Every engineer-planner seed must expose the role-appropriate hard-entry
  bundle at entry.
- Every family should be validated as a slice before the corpus widens.
- If a family keeps failing, fix the family design instead of forcing more
  variants into it.

## Stop Conditions

- Stop widening a family when the review burden becomes larger than the new
  information the family provides.
- Stop adding families when the new family would only duplicate an existing
  physical principle.
- Stop at 100 only after the last family slice validates cleanly.
