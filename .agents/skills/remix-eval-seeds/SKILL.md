---
name: remix-eval-seeds
description: Remix benchmark eval seeds for benchmark_coder, including geometry diversification and complexity improvements.
---

This skill is neighboring with "eval-creation-workflow"

Without any addition, your eval seed geometry is often too simple and unspecific. While it is not easy to create a seed itself due to geometry constraints, after you have a successful pass, start improving on the complexity of the seed. Add noise, complex operations, unusual geometry to make the evaluation more diverse - diverse datasets help with better data generation.

This is suitable in particularly for generating and remixing *benchmark* eval seeds.

Pick any three of these:
1. Add a number of varying chamfers on the geometry
2. Replace boxes with ovals or circles,
3. Add walls to the scene
4. Introduce some random, unexpected objects in the path
5. Add lofts
6. Rotate objects
7. Move the objectives
8. Severely contract or expand the zone in one or more axes
9. Add or remove copies of objects
10. Introduce patterns into benchmark

Secondary remix:
1. Break symmetry more aggressively with off-axis placements, uneven spacing, and partial mirroring.
2. Add cutouts, pockets, slots, through-holes, or internal voids so the shape is less boxy.
3. Introduce stepped surfaces, terraces, ledges, or layered heights instead of flat planes.
4. Use tapered or lofted transitions between sections so the geometry changes continuously.
5. Add ribs, gussets, fins, bosses, or support struts to create secondary structure.
6. Vary clearance intentionally around the objective area, not just the outer bounds.
7. Create nonuniform copies of repeated features, like a row of objects with alternating sizes or offsets.
8. Add funnel-like regions, narrow passages, or widened chambers to change flow or path behavior.
9. Mix convex and concave features in the same object so the silhouette is less predictable.
10. Use rotated or skewed components, especially when combined with elevation changes.
11. Add terrain-like variation: ramps, slopes, berms, shelves, or shallow basins.
12. Introduce decoy geometry that is visually similar but functionally irrelevant.
13. Make the scene more layered in depth, not just denser in plan view.
14. Perturb only one axis at a time in some seeds.
15. Use a multi-axis remix in other seeds.

Practical rule:
- Keep one anchor feature recognizable.
- Remix one dimension at a time:
  - shape family
  - scale
  - orientation
  - spacing
  - topology
  - clearance
  - verticality
