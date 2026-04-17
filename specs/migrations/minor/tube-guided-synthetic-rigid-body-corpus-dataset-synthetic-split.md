---
title: Tube-Guided Synthetic Rigid-Body Corpus Dataset-Synthetic Split
status: migration
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-17T00:00:00Z'
---

# Tube-Guided Synthetic Rigid-Body Corpus Dataset-Synthetic Split

<!-- Migration tracker. The corpus semantics stay in the major migration; this doc owns the implementation home and file-splitting contract. -->

## Purpose

This migration relocates the tube-guided synthetic rigid-body corpus
generator out of the notebook tree and into `dataset/synthetic/`.

The semantic corpus contract remains owned by
[Tube-Guided Synthetic Rigid-Body Corpus Generation](../major/tube-guided-synthetic-rigid-body-corpus-generation.md).
That major migration defines the acceptance policy, publication shape, and
seed layout. This migration defines where the generator code lives and how
large each source file is allowed to become.

`dataset/synthetic/` is the right code home because `scripts/experiments/**`
is documented as measurement and investigation scaffolding, not stable
contract code, and the current notebook-based implementation has outgrown a
single-file or notebook-first layout.

The target is a normal Python module tree with bounded responsibilities, not
a notebook artifact with supporting scraps around it.

## Problem Statement

The current implementation sprawls across a 2,783-line notebook script, a
small helper module, and a scratch buglog.

That shape creates four problems:

1. The generator is too large to reason about as a single unit.
2. The notebook boundary hides reusable logic inside an interactive artifact.
3. The implementation home is easy to confuse with the repo's disposable
   experiment tree.
4. There is no explicit file-size cap, so future edits can quietly recreate
   the same monolith.

The published corpus still belongs under `dataset/data/seed/**`, but the
generator that produces it should live beside the rest of the dataset
implementation, not inside `notebooks/` or `scripts/experiments/`.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `notebooks/tube_guided_synthetic_rigid_body_corpus.py` | Monolithic generator driver with route synthesis, acceptance logic, export paths, and debugging utilities in one file. | The file is 2,783 lines and is no longer maintainable as a single implementation unit. |
| `notebooks/tube_guided_synthetic_rigid_body_corpus_utils.py` | Partial helper module that still hangs off the notebook tree. | It is a temporary pressure valve, not a stable source-tree boundary. |
| `notebooks/tube_guided_synthetic_rigid_body_corpus.ipynb` | Interactive exploratory surface. | The generator is no longer notebook-shaped work; it needs importable module ownership. |
| `tube_guided_synthetic_rigid_body_corpus_buglog.md` | Scratch notes for geometry and render issues. | Debug notes are not a contract surface and should not anchor the implementation tree. |
| `scripts/experiments/**` | Canonical home for throwaway probes and benchmarks. | That tree is explicitly non-contractual and should not own reusable generation logic. |
| `dataset/data/seed/**` | Final corpus publication path. | The published seed layout is the output, not the source tree. |
| `dataset/evals/materialize_seed_workspace.py` | Materializes seeded workspaces from published artifacts. | It must remain compatible with the new generator output, but it should not own generator logic. |

## Proposed Target State

1. The canonical generator implementation lives under
   `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/`.
2. The generator is split into small modules with explicit ownership
   boundaries instead of one monolithic notebook script.
3. No generator implementation file exceeds 800 lines.
4. The notebook tree is scratch-only or removed from the canonical path; it
   does not own production generator logic.
5. The generator code remains dataset-owned and imports cleanly from the repo
   root without relying on notebook execution.
6. The corpus-policy migration remains the semantic source of truth for
   acceptance, publication, and seed shape.
7. `scripts/experiments/**` stays reserved for probes, measurements, and
   disposable debugging evidence.

## Required Work

### Source tree

- Move the reusable generator logic out of `notebooks/` and into
  `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/`.
- Split the implementation by responsibility so each module stays bounded
  and reviewable.
- Keep the published seed output paths unchanged.

### Module boundaries

- Separate source-bundle ingestion from geometry construction.
- Separate route and waypoint handling from scratch-tube generation.
- Separate acceptance filtering from decomposition and export.
- Keep utility-only code in module files, not in the notebook wrapper.
- Use typed data models for the source bundle and batch outputs instead of
  ad hoc dicts where the implementation needs structured records.

### Notebook and scratch surfaces

- Demote `notebooks/tube_guided_synthetic_rigid_body_corpus.py` to a thin
  scratch driver if it is retained at all.
- Treat `notebooks/tube_guided_synthetic_rigid_body_corpus.ipynb` and
  `tube_guided_synthetic_rigid_body_corpus_buglog.md` as investigation aids,
  not canonical implementation surfaces.
- Do not keep duplicate business logic in the notebook after the module
  split lands.

### Size guard

- Add a repo check that fails when any file in the generator tree exceeds
  800 lines.
- Prefer splitting modules over introducing a second oversized helper file.
- Treat the size cap as part of the implementation contract, not as a style
  preference.

### Documentation and references

- Update any generator-facing docs that still point at the notebook tree as
  the implementation home.
- Keep the major corpus migration as the source of truth for corpus
  semantics.
- Make the `dataset/synthetic/` home explicit wherever the generator is
  documented or invoked.

## Non-Goals

- Do not change the tube-guided corpus acceptance threshold, decomposition
  rules, or publication bundle shape.
- Do not move published seed data out of `dataset/data/seed/`.
- Do not turn `scripts/experiments/**` into a stable runtime or generator
  contract.
- Do not introduce a second public dataset format.
- Do not keep the monolithic notebook as the authoritative implementation
  surface.
- Do not broaden this into a general dataset-package redesign beyond the
  generator tree.

## Sequencing

1. Create the `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/`
   module tree and move the core generator logic into it.
2. Split the source-bundle, geometry, acceptance, decomposition, and export
   responsibilities into separate files.
3. Reduce the notebook to a scratch driver or retire it from the canonical
   path.
4. Add the 800-line size guard for the generator tree.
5. Refresh references, docs, and any seed-materialization touchpoints that
   describe the generator home.

## Acceptance Criteria

1. The generator can be imported and run from `dataset/synthetic/` without
   notebook execution.
2. The canonical generator logic is split across multiple small files
   instead of one monolithic notebook module.
3. No file in the generator tree exceeds 800 lines.
4. The notebook tree is no longer the authoritative implementation surface.
5. The published corpus output paths remain compatible with the existing
   seed layout.
6. The major corpus migration still defines the publication contract and is
   not replaced by this implementation split.
7. A structural check or integration assertion proves the generator tree
   stays within the file-size cap.

## Migration Checklist

### Source split

- [ ] Create the `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/`
  implementation tree.
- [ ] Move the reusable generator logic out of `notebooks/` and into module
  files.
- [ ] Separate source-bundle, geometry, acceptance, decomposition, and
  export responsibilities.

### Scratch demotion

- [ ] Reduce `notebooks/tube_guided_synthetic_rigid_body_corpus.py` to a
  thin wrapper or retire it.
- [ ] Keep `notebooks/tube_guided_synthetic_rigid_body_corpus.ipynb` and the
  buglog out of the canonical implementation path.

### Size and validation

- [ ] Add a check that fails when any generator file exceeds 800 lines.
- [ ] Verify the generator still materializes the same published seed
  layout.

### Documentation

- [ ] Update generator-facing docs and references to point at
  `dataset/synthetic/`.
- [ ] Keep the major corpus migration linked as the semantic source of
  truth.

## File-Level Change Set

- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/__init__.py`
- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/models.py`
- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/paths.py`
- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/geometry.py`
- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/contract.py`
- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/text_templates.py`
- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/pipeline.py`
- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/size_guard.py`
- `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus/cli.py`
- `notebooks/tube_guided_synthetic_rigid_body_corpus.py` as a thin wrapper
- `notebooks/tube_guided_synthetic_rigid_body_corpus_utils.py` as a
  compatibility alias
- `specs/migrations/major/tube-guided-synthetic-rigid-body-corpus-generation.md`
- generator-facing docs that still point at `notebooks/` as the canonical
  home
