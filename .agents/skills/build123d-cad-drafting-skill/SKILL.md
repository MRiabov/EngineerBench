---
name: build123d-cad-drafting-skill
description: Use this skill when you need do CAD modeling using build123d. Includes builder modes, semantic selectors, and MJCF-compatible boolean strategies, and everything you need to know about build123d syntax.
---

# build123d CAD Drafting Expert

Read this skill and the relevant reference files below before planning any `build123d` implementation.

## Core Directives

01. **Solid Modeling**: Prefer `with BuildPart()` plus primitives, booleans, fillets, chamfers, and shells for solid modeling. Use joint or placement helpers when they reduce manual coordinate tweaking.
02. **Parametric Dimensioning**: Never guess a size. Drive each dimension from named inputs, source geometry, or formulas. Compute secondary offsets, wall thicknesses, clearances, and manufacturing constants from those inputs. If a value is missing, stop and surface the missing source instead of inventing a number.
03. **Semantic Selectors**: Avoid indices. Use `faces()`, `edges()`, `vertices()` with `sort_by(Axis.Z)` or `last()`/`first()`.
04. **2D Joint Sketching**: When a sketch is defined by tangency, fixed radius, or datum relationships, use the constrained line/arc helpers instead of hand-tuning vertices. Compute radii and spans from named parameters rather than by eye. These helpers are for CAD sketch layout, not MJCF joints or simulation joints. See [2d_joints.md](references/2d_joints.md).
05. **3D Placement Joints**: When assembly layout depends on repeated, mirrored, or rotated placement, use `Location`, `Locations`, `.move(...)`, `.moved(...)`, `Align`, and `Compound(children=[...])` placement patterns to derive poses from joint frames and datums instead of hand-deriving world coordinates. Prefer constraint-based placement against an existing part over standalone `Location(...)`; use absolute pose data only when there is no better mating or joint relationship. This is joint-driven placement, not random position-driven layout. When choosing a mating face, start from visual inspection and then confirm with axis-sorted selectors; in practice the obvious face is often the first or last face along a principal axis, which is faster and less error-prone than reasoning from coordinates alone. See [3d_joints.md](references/3d_joints.md) for a face-constrained example.
06. **MJCF Compliance**: Ensure parts are non-intersecting if they belong to different simulation links.
07. **Assembly Labels**: Use `.label = "stator"` and `.label = "rotor"` for automatic motor/joint injection in MJCF.
08. **Label Namespace Hygiene**: Top-level authored labels must be unique and must not be `environment` or start with `zone_`. The simulator reserves those names for the scene root and generated objective bodies, and duplicate labels collide with MJCF mesh/body names.
09. **Intersection Checks**: For pairwise geometry, use `shape_a.intersect(shape_b)`. The returned shape has a `.volume` property; if that volume is greater than zero, the shapes intersect, and you can inspect or render the returned intersection shape for debugging. For grouped children, wrap the parts in `Compound(children=[...])` and call `do_children_intersect()` on the compound; in this runtime it returns `(intersects, (shape_a, shape_b), volume)`, so unpack it for logging.
10. **COTS Parts**: If the geometry includes catalog-backed components, load `skills/cots-parts/SKILL.md` and keep the concrete COTS instance intact. Do not strip provenance or replace it with anonymous solids when the task still depends on part identity.

## Positioning Hierarchy

- If environment fixtures are available for attachment, prefer faces, edges, and other fixture features over raw coordinates.
- Use constraint chains and derived formulas from source geometry or environment properties such as `Wire.length` before reaching for absolute world positions. Use calculator-backed or scripted derivations for computed values; derived formulas are better than hand math, and hardcoded values are the last resort.
- Use `with Locations(...)` when you need a placement context for repeated instances. `Location(...)` is a pose object, not a context manager.
- Treat absolute locations outside of COTS constants as a drafting smell. Keep them minimal, traceable, and only use them when no attachment or datum relationship is available.

## Repo-Specific Contracts

1. **Part Authoring Pattern**: Build solids inside `BuildPart`, then extract `builder.part`, transform it, and only then assign labels/metadata.
2. **Constructor Guardrails**:
   - `Box` dimensions in this runtime are positional: `Box(length, width, height)`.
   - Do not use `Box(width=..., height=..., length=...)`.
   - For bottom/top alignment, use `Align.MIN` / `Align.MAX`, not `Align.BOTTOM` / `Align.TOP`.
   - Place top-level benchmark parts with `.move(Location(...))` or `.moved(Location(...))`, not `.translate(...)`. The simulation exporter recenters meshes and uses `child.location` for placement.
   - Do not pass `label=` into `Box`, `Sphere`, `Cylinder`, `Compound`, or other build123d constructors.
   - Assign `.label` after the part/compound already exists.
3. **Metadata Is Mandatory**:
   - Every part must have `PartMetadata(...)`.
   - Every final assembly must have `CompoundMetadata(...)`.
   - `CompoundMetadata(fixed=True)` on the parent assembly does not make child parts static. Mark each static benchmark fixture with `PartMetadata(..., fixed=True)` individually.
   - The repo-specific metadata import path is fixed: `from shared.models.schemas import PartMetadata, CompoundMetadata`. Do not grep the codebase to rediscover it.
4. **MJCF Compliance**:
   - Ensure parts are non-intersecting when they belong to different simulation links.
   - For direct pairwise checks, use `shape_a.intersect(shape_b)`. The returned shape has a `.volume` property; if that volume is greater than zero, the shapes intersect, and you can inspect or render the returned intersection shape for debugging.
   - For grouped children, wrap the parts in `Compound(children=[...])` and call `do_children_intersect()` on the compound. In this runtime it returns `(intersects, (shape_a, shape_b), volume)`, so unpack it for logging. When no overlap exists, the tuple is `(False, (None, None), 0.0)`.
5. **Assembly Labels**: Use `.label = "stator"` and `.label = "rotor"` for automatic motor/joint injection in MJCF when relevant.
6. **Final Assembly Contract**: Return a `Compound(children=[...])` from `build()`, then assign `.label` and `.metadata` to that compound.
   - Do not create an empty `Compound()` and then mutate `compound.children`; treat the children collection as construction-time input.
   - Preview yaw is measured clockwise from front. If a rear camera angle makes the model look mirrored on X, confirm the camera direction and world-space placement before changing geometry; the image may only be a back-side view.

## Placement And Rotation Contract

- Create top-level authored solids at the origin, then place them with `Location(...)`.
- Treat `Location(...)` as the last-mile pose carrier, not the default modeling strategy. If another part, mate, fastener, or datum can define the relationship, derive the pose from that constraint chain first and keep the absolute coordinate anchor as small and traceable as possible.
- For exported benchmark/engineering assemblies, the simulation stack reads pose from `child.location`.
- The orientation tuple inside `Location((x, y, z), (rx, ry, rz))` is in degrees, not radians.
- If a mechanism uses multiple top-level parts that must share the same slope or travel direction, encode compatible rotated locations for each of them. Do not rotate only one part and leave companion rails/walls flat.
- For chute/channel mechanisms, the floor and containment rails or walls must form one continuous corridor in the exported scene. Either place them with the same rotated frame or author them as one combined chute. A sloped floor with world-aligned rails/walls beside it is not a valid transport path.
- Verify downhill direction from the authored geometry, not from angle comments. If the object must travel from lower X to higher X, the support surface must be higher at the negative-X handoff and lower at the positive-X handoff in the final placed geometry. Reverse that relation when travel goes the other way.
- For X-aligned ramps or chutes rotated about Y, do not trust your intuition about the sign. Inspect the final placed part extents/vertices or exported scene and confirm that the spawn side is the high side before you accept the slope.
- Every child you place into `Compound(children=[...])` must be a distinct top-level object instance. Reusing one source shape is fine only if you derive separate placed copies from it with `.moved(...)`. When you need two rails, two walls, or mirrored supports from one builder result, always create each placement with `.moved(...)`; reserve `.move(...)` for a one-off final placement of a single object. Do not place the same mutable `Part` instance into the compound twice via repeated `.move(...)` calls.
- If a top-level part must be rotated in the exported scene, encode the rotation directly in the location, for example:

```python
ramp = ramp_builder.part.move(Location((0, 0, 0.06), (0, 2, 0)))
rail_upper = rail_builder.part.moved(Location((0, 0.06, 0.09), (0, 2, 0)))
rail_lower = rail_builder.part.moved(Location((0, -0.06, 0.09), (0, 2, 0)))
```

- If you first wrote `rail = rail_builder.part.move(...)` and later realize you need a mirrored or rotated companion rail, stop and rebuild that section with `.moved(...)` copies. Do not mutate the same builder result twice.

- Do not rely on `part.rotate(...)` as the final pose step for top-level exported parts. That can leave `child.location.orientation` unchanged, which makes the exported MJCF/scene appear unrotated even if the local build123d object looked rotated.

- Preview yaw is measured clockwise from front. If a rear camera angle makes the model look mirrored on X, confirm the camera direction and world-space placement before changing geometry; the image may only be a back-side view.

## Build-Zone Checks For Sloped Parts

- Validate sloped or rotated parts against the final rotated envelope, not just the nominal support heights or centerline endpoints.
- Include thickness, wall height, and top corners when checking whether an inclined floor or chute fits inside the allowed Z budget.
- When Z headroom is tight, prefer a thin transport floor with separate supports or rails instead of a tall wedge that rises from the ground.

## Support Continuity Contract

- For passive-transfer mechanisms, adjacent support parts must actually meet or overlap in the authored geometry where the object hands off between them.
- Do not rely on center-position arithmetic or visual near-contact. Check the real extents of the ramp/chute against the neighboring platform or support and remove any unsupported gap.

## Workspace Execution Contract

- In benchmark and engineer workspaces, shell verification commands already start in the seeded workspace root.
- Do not prepend hard-coded `cd /workspace`, `cd /home/user/workspace`, or host-specific repo paths before validation or simulation checks.

## References & Contents

### [assembly.md](references/assembly.md) (Assembly & Physics)

- Motor Pattern (stator/rotor) (L11)
- Explicit Joint Control (L33)
- Bearings & Fasteners (L59)
- Environment Zones (Goal/Forbid) (L75)
- Collision Best Practices (L82)

### [2d_joints.md](references/2d_joints.md) (2D Joints)

- Tangent bridge between repeated features
- Fixed-radius tangent arcs
- Dimension and extension lines

### [3d_joints.md](references/3d_joints.md) (3D Joints)

- Repeated datum placement with `Locations(...)`
- Rotated top-level parts with `Location(...)`
- Compound assembly placement and overlap checks

### [formula-driven-modelling.md](references/formula-driven-modelling.md) (Formula-Driven Modeling Example)

- Source-value tables, derived dimensions, and joint-driven placement
- Spreadsheet-style modeling with formulas instead of guessed sizes

### [technical_drawing.md](references/technical_drawing.md) (Technical Drawing)

- `TechnicalDrawing(...)` border/title block setup
- `project_to_viewport(...)`, `ExtensionLine(...)`, `Text(...)`, and `Draft(...)`
- `ExportSVG(...)` / `ExportDXF(...)` sheet export and preview workflow

### [cots-parts](../cots-parts/SKILL.md) (Catalog-Backed Components)

- Class-first COTS construction and provenance
- Motor local frames and placement contract
- Fixtures vs solution parts
- Declared-vs-used validation and anti-patterns

### [cheat_sheet.md](references/cheat_sheet.md) (Syntax Reference)

- Core Builders (L5)
- Sketching & Surfaces (L15)
- Modeling Operations 3D (L22)
- Feature Selection & Modification (L30)
- Direct Geometry / Algebra Mode (L40)
- IO & Export (L49)
- Common Pitfalls for LLMs (L55)

### [handpicked.md](references/handpicked.md) (Expert Patterns)

- Simple Parts & Boolean Operations (L5)
- Sketches & Extrusion (L21)
- Advanced Features: Holes & Locations (L33)
- Selection & Modification: Fillets/Chamfers (L48)
- Loft & Sweep (L61)
- Complex Geometry: The OCC Bottle (L77)
- Mirroring & Symmetries (L99)
- **Expert Pitfalls & Patterns (L113)**: `with Locations` Plural Trap, Implicit Contexts.

### [reference.md](references/reference.md) (Exhaustive Examples)

- 1-2: Simple Plates & Holes (L81)
- 3-5: Prismatic Solids & Locations (L127)
- 6-8: Point Lists, Polygons, Polylines (L225)
- 9-10: Selectors, Fillets, Chamfers, Holes (L300)
- 11-13: Grid/Polar Locations, Workplanes, Counterbore (L360)
- 14-17: Sweep, Mirroring, Profiles (L453)
- 18-22: Workplanes on Faces/Vertices, Rotated Planes (L561)
- 23-28: Revolve, Loft, Shelling, Slitting (L691)
- *Full Table of Contents (36 examples) available inside the file.*

Use the reference guides above as the lookup path for build123d details.
