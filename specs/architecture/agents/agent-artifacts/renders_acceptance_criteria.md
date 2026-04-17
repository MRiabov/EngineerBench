# renders Acceptance Criteria

## Role of the File Family

The render family includes bundle-local render manifests, the append-only render index, preview scene snapshots, optional simulation sidecars, and the actual rendered media files.
It is worth being a dedicated artifact family because visual evidence is what lets reviewers validate geometry, motion, and revision attribution without guessing from filenames or text summaries.

## Hard Requirements

- Reviewers inspect the actual media, not just filenames.
- The latest revision's render bundle is the only accepted bundle for that review.
- Bundle-local `render_manifest.json` data matches the current seed and review gate.
- Every PNG/JPG evidence path declared by the manifest exists in the bundle, and `preview_evidence_paths` agrees with the image artifact set.
- `renders/render_index.jsonl` matches the latest published bundle metadata when historical lookup is involved.
- `preview_scene.json`, `frames.jsonl`, and `objects.parquet` match the current bundle when those sidecars are present.
- `frames.jsonl` and `objects.parquet` are required when the manifest advertises MP4 evidence.
- `renders/render_manifest.json` remains a compatibility alias, not the historical source of truth.
- Missing or stale render evidence is treated as a hard failure, not a prompt to guess.

## Quality Criteria

- The media makes the relevant geometry or motion easy to inspect.
- The bundle is clearly attributable to the current revision.
- When render images exist and the stage requires visual inspection, the bundle contains enough media to satisfy the configured minimum inspection count.
- The render evidence complements validation and simulation output instead of duplicating or contradicting it.

## Reviewer Look-Fors: File Antipatterns to Look For

- A reviewer only listed files instead of actually inspecting media.
- The bundle is stale, from a different revision, or attached to the wrong stage.
- The bundle manifest declares image evidence that is not present on disk.
- The bundle-local manifest and sidecars do not agree with the current workspace state.
- Historical lookup points at a bundle that does not match the latest revision evidence.

## Cross-References

- `specs/architecture/rendering.md`
- `specs/architecture/CAD-and-other-infra.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/definitions-of-success-and-failure.md`
