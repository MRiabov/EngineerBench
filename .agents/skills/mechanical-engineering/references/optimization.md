# Optimization Patterns for Mechanical Engineering

## Iterative Design Refinement

1. **Initial Design:** Create the geometry based on the benchmark requirements.
2. **Simulation:** Run the benchmark and inspect the resulting stress metrics.
3. **Analyze:** Call `get_stress_report(part_label)`.
4. **Refine:**
   - **If Safety Factor < 1.5 (Stress High):** Add material (increase wall thickness, add fillets, add ribs).
   - **If Safety Factor > 5.0 (Overdesign):** Remove material (hollow out parts, use thinner walls, add cutouts).
5. **Re-Verify:** Run the simulation again to confirm the safety factor is within the 1.5 - 5.0 range.

## Material Selection Optimization

- **Rigid (Metals, Hard Plastics):** Best for load-bearing structures.
- **Soft (Rubber, Silicone):** Best for seals, gaskets, or flexible hinges.
- **Elastomer (High Stretch):** Best for components that undergo large, reversible deformations.

## Balancing Performance and Cost

- Refer to the `manufacturing-knowledge` skill for material and manufacturing costs.
- Mechanical performance (Safety Factor) must be balanced with manufacturing constraints:
  - **CNC Milling:** Avoid undercuts and tight internal corners.
  - **Injection Molding:** Maintain uniform wall thickness (1.0 - 4.0mm) and add draft angles (2.0°).

## Common Patterns

### Ribbing for Stiffness

Add internal ribs to increase the Moment of Inertia ($I$) without significantly increasing volume/cost.

```python
# Expert Pattern: Adding internal ribs to a shell
rib_base = part.faces().filter_by(Axis.Z).last()
ribs = box(length=2, width=40, height=10).move(x=10) + 
       box(length=2, width=40, height=10).move(x=-10)
part = part + ribs
```

### Fillets to Reduce Stress Concentration

Sharp internal corners act as "stress risers." Always add fillets to internal edges that experience high load.

```python
# Expert Pattern: Stress reduction fillet
high_stress_edges = part.edges().filter_by(Axis.Z).internal()
part = fillet(high_stress_edges, radius=3.1)
```
