# Finite Element Analysis (FEA) Principles

## Core Concepts

### 1. Stress & Strain

- **Stress ($\\sigma$):** Internal resistance of a material to an external force (measured in Pascals, Pa).
- **Strain ($\\epsilon$):** Deformation or displacement of material particles under stress.
- **Von Mises Stress:** A scalar value derived from the stress tensor used to predict yielding of ductile materials.

### 2. Failure Criteria

- **Ultimate Stress ($\\sigma\_{u}$):** The maximum stress a material can withstand before rupture.
- **Yield Stress ($\\sigma\_{y}$):** The stress at which a material begins to deform plastically.
- **Safety Factor (SF):** Ratio of ultimate/yield stress to actual stress ($SF = \\frac{\\sigma\_{limit}}{\\sigma\_{actual}}$).
- **Utilization (%):** Percentage of the material's capacity being used ($Utilization = \\frac{\\sigma\_{actual}}{\\sigma\_{limit}} imes 100$).

## Simulation Workflow

1. **Meshing:**

   - Conversion of CAD (BREP) to a tetrahedral mesh (via TetGen).
   - Mesh density: Higher density improves accuracy but increases computation time.
   - Mesh Repair: If geometry is self-intersecting, use `trimesh` to repair before simulation.

2. **Simulation (Genesis):**

   - Applies boundary conditions (fixed supports, loads).
   - Solves for displacement and stress.
   - **Linear FEM:** Used for "rigid" materials (metals, hard plastics) where deformations are small.
   - **Hyperelastic (Neo-Hookean):** Used for "soft" materials or "elastomers" where large deformations occur.

3. **Post-Processing:**

   - Inspect the simulation output metrics that matter for the current mechanism.

## Interpreting Results

- **PART_BREAKAGE:** Occurs immediately when any part exceeds `ultimate_stress_pa`.
- **Target Safety Factor:** 1.5 - 5.0 for standard engineering applications.
- **Overdesign:** Safety factor > 5.0 indicates unnecessary material (increases weight and cost).
- **Underdesign:** Safety factor < 1.5 indicates high risk of failure or insufficient durability.
