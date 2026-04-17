# CAD and other infrastructure; dependencies.

## Scope summary

- Primary focus: CAD metadata requirements and supporting infrastructure assumptions outside the main agent workflow docs.
- Defines part metadata, schema strictness, and logging/tooling expectations that support CAD execution.
- Rendering policy, preview file naming, and render bundle contracts live in [Rendering](./rendering.md).
- Use this file when changing CAD model contracts or shared infra assumptions that are not specific to distributed execution.

## CAD

### Part metadata

Parts and assemblies have metadata, e.g. `material_id` for material parts and `fixed: bool` for benchmark-owned fixtures, plus other supported fields.

Define classes `PartMetadata` and `CompoundMetadata` that can store all properties related to them. Without these mandatory fields, validation will fail.

Metadata validation is ownership-sensitive:

1. Engineer-created manufactured parts and planner-declared manufactured parts must carry the manufacturing/workbench metadata required for manufacturability validation and pricing.
2. Benchmark-owned environment geometry, benchmark input objects, and benchmark objective markers are not treated as manufactured outputs.
3. Benchmark-owned read-only fixtures may carry physics/render metadata, but they are excluded from manufacturability validation and pricing.
4. Missing `manufacturing_method` / `material_id` is therefore a hard validation failure only for engineer-owned manufactured parts (and planner-owned manufactured-part definitions), not for benchmark fixtures.

Benchmark definitions also carry a declarative benchmark-side fixture metadata layer in `benchmark_definition.yaml`.

The rule is:

1. `benchmark_definition.yaml` may declare benchmark-owned fixture metadata such as `fixed` and `material_id` under `benchmark_parts`.
2. That YAML metadata is the benchmark contract for planning/handover, not the runtime CAD instance metadata used by simulation/export.
3. The actual built geometry still needs runtime `.metadata` on CAD parts/assemblies for exporter, validation, and rendering behavior.
4. Engineer-owned solution metadata remains outside `benchmark_definition.yaml`; it belongs in `assembly_definition.yaml` and the authored CAD result.

### Assigning a part to workbenches

The agent must assign a part manufacturing method to every part it expects to price or send for manufacturing. If not, the parts can not be priced or sent for manufacturing.

This rule does not apply to the benchmark-owned environment or other benchmark input fixtures handed to the engineer. Those objects are validated as geometry/physics context only, not as manufacturable outputs.

Verification is handled by deterministic validation methods.

So suppose the agent's code is as follows:

```py
from build123d import *
from utils.models.schemas import PartMetadata
from utils.enums import ManufacturingMethod
from utils import validate_and_price 
# `utils` is the public package that gathers the agent-facing helpers, so callers do not need to hunt through the codebase.

with BuildPart() as part_builder:
    Box(10,10,10)

part_builder.part.label="custom_label"
part_builder.part.metadata = PartMetadata(
    manufacturing_method=ManufacturingMethod.CNC,
    material_id="aluminum-6061"
)

validate_and_price(part_builder.part) # prints ("Part {label} is valid, the unit price at XYZ pcs is ...)
```

## Rendering

Rendering policy, preview file naming, persistent bundle layout, and `inspect_media(...)` behavior live in [Rendering](./rendering.md). This section remains only as a compatibility pointer for older readers.

### Workbench technical details

Technical details of manufacturability constraints are discussed in spec 004 (not to be discussed here; however manufacturability is determined by deterministic algorithms.)

Workbench validation, along with the other utility infrastructure, is read-only in the container.

### Supported workbenches

3D printing, CNC, and injection molding are supported.

## Other infra

### Strict schema

`schemathesis` checks run against the OpenAPI. All schema must be strictly typed to avoid ANY issues.
We use Pydantic excensively in this application.

### Logging

Use Structlog because it produces clearer traces and should work with OpenTelemetry out of the box.
For utils used internally in an agent, plain `logging` is acceptable.

<!--
## CAD and and design validation

As said, "agents will live inside of a filesystem". The agents will generate and execute design validations of files in the filesystem.-->
