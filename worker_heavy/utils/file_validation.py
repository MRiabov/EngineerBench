"""
File validation utilities for agent handover files.

Validates the structure and content of:
- benchmark_definition.yaml: Central data exchange object
- assembly_definition.yaml: Cost risk management
- benchmark_plan.md / engineering_plan.md: Structured planning documents
- Review files: YAML frontmatter with decision field
"""

# T015: Hashing for immutability checks
import copy
import hashlib
import io
import re
import subprocess
import tempfile
import tokenize
from collections import Counter
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import ValidationError

from shared.agents.config import load_agents_config
from shared.enums import AgentName, BenchmarkRefusalReason
from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    CoarsePayloadTrajectory,
    PartConfig,
    PayloadTrajectoryDefinition,
    PayloadTrajectoryPose,
    PlanRefusalFrontmatter,
    ReviewFrontmatter,
    SubassemblyEstimate,
)
from shared.script_contracts import (
    BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
    BENCHMARK_SCRIPT_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    SOLUTION_SCRIPT_PATH,
    plan_path_for_agent,
)
from shared.simulation.schemas import get_default_simulator_backend
from shared.workers.workbench_models import ManufacturingConfig
from worker_heavy.utils.dfm import (
    validate_declared_assembly_cost,
    validate_declared_assembly_weight,
    validate_exact_declared_assembly_cost,
    validate_exact_declared_assembly_weight,
)
from worker_heavy.utils.payload_trajectory_validation import (
    validate_payload_trajectory_swept_clearance,
)
from worker_heavy.utils.validation import (
    _validate_benchmark_definition_consistency,
)
from worker_heavy.workbenches.config import load_config, load_merged_config

logger = structlog.get_logger(__name__)

# Required sections for plan validation
BENCHMARK_PLAN_REQUIRED_SECTIONS = [
    "Learning Objective",
    "Geometry",
    "Objectives",
]

ENGINEERING_PLAN_REQUIRED_SECTIONS = [
    "Solution Overview",
    "Parts List",
    "Assembly Strategy",
    "Cost & Weight Budget",
    "Risk Assessment",
]

TEMPLATE_PLACEHOLDERS = [
    "x_min",
    "x_max",
    "[x, y, z]",
    "y_min",
    "z_min",  # benchmark_definition.yaml
    "[implement here]",
    "TODO:",
    "...",  # generic
    "[x_min",
    "[x_max",  # generic
]


def _normalize_benchmark_definition_contract(data: dict[str, Any]) -> dict[str, Any]:
    """Accept legacy benchmark-part metadata keys while validating canonically."""

    normalized = copy.deepcopy(data)
    benchmark_parts = normalized.get("benchmark_parts")
    if not isinstance(benchmark_parts, list):
        return normalized

    for part in benchmark_parts:
        if not isinstance(part, dict):
            continue
        metadata = part.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if "is_fixed" not in metadata and "fixed" in metadata:
            metadata["is_fixed"] = metadata["fixed"]
        metadata.pop("fixed", None)

    return normalized


_MISSING_FILE_ERROR_RE = re.compile(
    r"^Error:\s*File\s+'(?P<path>[^']+)'\s+not found\.?$", re.IGNORECASE
)


def _exact_identifier_pattern(identifier: str) -> re.Pattern[str]:
    escaped = re.escape(identifier.strip())
    return re.compile(
        rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])",
    )


def _count_exact_identifier_mentions(content: str, identifier: str) -> int:
    if not identifier.strip():
        return 0
    return len(_exact_identifier_pattern(identifier).findall(content))


def _token_counts_to_list(tokens: Counter[str]) -> list[tuple[str, int]]:
    return sorted(tokens.items(), key=lambda item: item[0])


def _format_identity_pair(
    label: str | None,
) -> str:
    pieces: list[str] = []
    if label is not None:
        pieces.append(f"label={label}")
    if not pieces:
        return "<unlabeled>"
    return ", ".join(pieces)


def _merge_token_count_maps(*maps: Counter[str]) -> Counter[str]:
    merged: Counter[str] = Counter()
    for mapping in maps:
        for token, count in mapping.items():
            if not token.strip() or count <= 0:
                continue
            merged[token] += count
    return merged


def _planner_plan_grounding_tokens_from_benchmark(
    benchmark_definition: BenchmarkDefinition,
) -> Counter[str]:
    tokens: Counter[str] = Counter()
    for benchmark_part in benchmark_definition.benchmark_parts:
        if benchmark_part.label.strip():
            tokens[benchmark_part.label.strip()] += 1
    return tokens


def _planner_plan_grounding_identity_pairs_from_benchmark(
    benchmark_definition: BenchmarkDefinition,
) -> Counter[tuple[str | None, str | None]]:
    pairs: Counter[tuple[str | None, str | None]] = Counter()
    for benchmark_part in benchmark_definition.benchmark_parts:
        label = benchmark_part.label.strip() or None
        if label is not None:
            pairs[(label, None)] += 1
    return pairs


def _planner_plan_grounding_identity_pairs_from_assembly(
    assembly_definition: AssemblyDefinition,
) -> Counter[tuple[str | None, str | None]]:
    pairs: Counter[tuple[str | None, str | None]] = Counter()

    def _visit(item: object) -> None:
        if isinstance(item, SubassemblyEstimate):
            subassembly_id = item.subassembly_id.strip() or None
            if subassembly_id is not None:
                pairs[(subassembly_id, None)] += 1
            for part in item.parts:
                _visit(part)
        elif isinstance(item, PartConfig):
            label = item.name.strip() or None
            if label is not None:
                pairs[(label, None)] += 1

    for item in assembly_definition.final_assembly:
        _visit(item)
    return pairs


def _validate_assembly_inventory_parity(
    assembly_definition: AssemblyDefinition,
) -> list[str]:
    """Require manufactured-part labels to match their final_assembly counts."""
    declared_tokens: Counter[str] = Counter()
    for part in assembly_definition.manufactured_parts:
        if part.part_name.strip():
            declared_tokens[part.part_name.strip()] += part.quantity

    final_assembly_tokens: Counter[str] = Counter()
    for item in assembly_definition.final_assembly:
        if isinstance(item, SubassemblyEstimate):
            if item.subassembly_id.strip():
                final_assembly_tokens[item.subassembly_id.strip()] += 1
            for part in item.parts:
                if part.name.strip():
                    final_assembly_tokens[part.name.strip()] += 1
        elif isinstance(item, PartConfig) and item.name.strip():
            final_assembly_tokens[item.name.strip()] += 1

    errors: list[str] = []
    for token in sorted(set(declared_tokens) & set(final_assembly_tokens)):
        declared_count = declared_tokens.get(token, 0)
        final_assembly_count = final_assembly_tokens.get(token, 0)
        if declared_count != final_assembly_count:
            errors.append(
                "assembly_definition.yaml: final_assembly parity mismatch for "
                f"'{token}' (declared {declared_count}, final_assembly "
                f"{final_assembly_count}; final_assembly must match the "
                "declared inventory exactly)"
            )
    return errors


def _planner_plan_grounding_tokens_from_assembly(
    assembly_definition: AssemblyDefinition,
) -> Counter[str]:
    # Grounding tokens come from the authored declaration and the final_assembly
    # labels. Overlapping manufactured-part labels are parity-checked separately
    # so the merge here does not become a silent fallback for mismatches.
    declared_tokens: Counter[str] = Counter()
    for part in assembly_definition.manufactured_parts:
        if part.part_name.strip():
            declared_tokens[part.part_name.strip()] += part.quantity

    final_assembly_tokens: Counter[str] = Counter()
    for item in assembly_definition.final_assembly:
        if isinstance(item, SubassemblyEstimate):
            if item.subassembly_id.strip():
                final_assembly_tokens[item.subassembly_id.strip()] += 1
            for part in item.parts:
                if part.name.strip():
                    final_assembly_tokens[part.name.strip()] += 1
        elif isinstance(item, PartConfig) and item.name.strip():
            final_assembly_tokens[item.name.strip()] += 1

    if not final_assembly_tokens:
        return declared_tokens

    tokens = Counter(declared_tokens)
    for token in set(declared_tokens) | set(final_assembly_tokens):
        tokens[token] = max(
            declared_tokens.get(token, 0), final_assembly_tokens.get(token, 0)
        )
    return tokens


def _benchmark_script_expected_identity_pairs(
    *,
    benchmark_definition: BenchmarkDefinition,
    assembly_definition: AssemblyDefinition | None = None,
) -> Counter[tuple[str | None, str | None]]:
    expected = _planner_plan_grounding_identity_pairs_from_benchmark(
        benchmark_definition
    )
    if assembly_definition is None:
        return expected
    return expected + _planner_plan_grounding_identity_pairs_from_assembly(
        assembly_definition
    )


def _assembly_script_expected_identity_pairs(
    assembly_definition: AssemblyDefinition,
) -> Counter[tuple[str | None, str | None]]:
    return _planner_plan_grounding_identity_pairs_from_assembly(assembly_definition)


def _benchmark_script_expected_tokens(
    *,
    benchmark_definition: BenchmarkDefinition,
    assembly_definition: AssemblyDefinition | None = None,
) -> Counter[str]:
    expected = _planner_plan_grounding_tokens_from_benchmark(benchmark_definition)
    if assembly_definition is None:
        return expected

    assembly_counts = _planner_plan_grounding_tokens_from_assembly(assembly_definition)
    return Counter(
        {
            token: max(expected.get(token, 0), assembly_counts.get(token, 0))
            for token in set(expected) | set(assembly_counts)
        }
    )


def _assembly_script_expected_tokens(
    assembly_definition: AssemblyDefinition,
) -> Counter[str]:
    # Mirror the planner-side contract: labels from the declared inventory and
    # final_assembly are both grounded, while overlapping manufactured-part
    # labels are parity-checked separately.
    declared_tokens: Counter[str] = Counter()
    for part in assembly_definition.manufactured_parts:
        if part.part_name.strip():
            declared_tokens[part.part_name.strip()] += part.quantity

    final_assembly_tokens: Counter[str] = Counter()
    for item in assembly_definition.final_assembly:
        if isinstance(item, SubassemblyEstimate):
            if item.subassembly_id.strip():
                final_assembly_tokens[item.subassembly_id.strip()] += 1
            for part in item.parts:
                if part.name.strip():
                    final_assembly_tokens[part.name.strip()] += 1
        elif isinstance(item, PartConfig) and item.name.strip():
            final_assembly_tokens[item.name.strip()] += 1

    if not final_assembly_tokens:
        return declared_tokens

    expected = Counter(declared_tokens)
    for token in set(declared_tokens) | set(final_assembly_tokens):
        expected[token] = max(
            declared_tokens.get(token, 0), final_assembly_tokens.get(token, 0)
        )
    return expected


def validate_planner_evidence_script_layout_contract(
    *,
    artifact_name: str,
    content: str,
) -> list[str]:
    """Reject presentation-layout wording in the planner evidence scripts."""
    if not artifact_name.endswith("_evidence_script.py"):
        return []
    if not re.search(r"\b(exploded|staggered)\b", content, flags=re.IGNORECASE):
        return []
    return [
        f"{artifact_name}: exploded/staggered presentation is forbidden in the "
        "planner evidence script; keep display-only layout in the technical "
        "drawing companion instead."
    ]


def _validate_exact_identifier_mentions(
    *,
    artifact_name: str,
    content: str,
    required_tokens: Counter[str],
) -> list[str]:
    errors: list[str] = []
    for token, expected_count in _token_counts_to_list(required_tokens):
        actual_count = _count_exact_identifier_mentions(content, token)
        if actual_count < expected_count:
            errors.append(
                f"{artifact_name}: missing exact identifier mention '{token}' "
                f"(expected at least {expected_count}, found {actual_count})"
            )
    return errors


def _collect_component_identity_counts(
    component: Any,
) -> tuple[Counter[str], list[tuple[str | None, str | None]]]:
    counts: Counter[str] = Counter()
    identity_entries: list[tuple[str | None, str | None]] = []

    def _visit(node: Any, *, is_root: bool) -> None:
        children = getattr(node, "children", ()) or ()
        label = getattr(node, "label", None)

        if not (is_root and children):
            normalized_label = (
                label.strip() if isinstance(label, str) and label.strip() else None
            )
            if normalized_label is not None:
                counts[normalized_label] += 1
            if normalized_label is not None:
                identity_entries.append((normalized_label, None))

        for child in children:
            _visit(child, is_root=False)

    _visit(component, is_root=True)
    return counts, identity_entries


def _collect_component_identity_pairs(
    component: Any,
) -> tuple[Counter[tuple[str | None, str | None]], list[tuple[str | None, str | None]]]:
    pairs: Counter[tuple[str | None, str | None]] = Counter()
    identity_entries: list[tuple[str | None, str | None]] = []

    def _visit(node: Any, *, is_root: bool) -> None:
        children = getattr(node, "children", ()) or ()
        label = getattr(node, "label", None)

        if not (is_root and children):
            normalized_label = (
                label.strip() if isinstance(label, str) and label.strip() else None
            )
            if normalized_label is not None:
                pair = (normalized_label, None)
                pairs[pair] += 1
                identity_entries.append(pair)

        for child in children:
            _visit(child, is_root=False)

    _visit(component, is_root=True)
    return pairs, identity_entries


def _format_component_identity_entries(
    identity_entries: list[tuple[str | None, str | None]],
    *,
    max_entries: int = 4,
) -> str:
    if not identity_entries:
        return "<none>"

    formatted_entries: list[str] = []
    for label, _ in identity_entries[:max_entries]:
        pieces: list[str] = []
        if label is not None:
            pieces.append(f"label={label}")
        if not pieces:
            pieces.append("<unlabeled>")
        formatted_entries.append(", ".join(pieces))

    if len(identity_entries) > max_entries:
        formatted_entries.append("...")
    return "; ".join(formatted_entries)


def validate_component_inventory_exactness(
    *,
    component: Any,
    expected_tokens: Counter[str],
    artifact_name: str,
    expected_identity_pairs: Counter[tuple[str | None, str | None]] | None = None,
) -> list[str]:
    observed_tokens, identity_entries = _collect_component_identity_counts(component)
    observed_pairs, pair_entries = _collect_component_identity_pairs(component)
    errors: list[str] = []
    identity_summary = _format_component_identity_entries(identity_entries)
    for token in sorted(set(observed_tokens) | set(expected_tokens)):
        expected_count = expected_tokens.get(token, 0)
        observed_count = observed_tokens.get(token, 0)
        if observed_count != expected_count:
            errors.append(
                f"{artifact_name}: exact inventory mismatch for '{token}' "
                f"(expected {expected_count}, found {observed_count}; "
                f"observed identities: {identity_summary})"
            )
    if expected_identity_pairs is not None:
        pair_summary = _format_component_identity_entries(pair_entries)
        for label, _ in sorted(
            set(observed_pairs) | set(expected_identity_pairs),
            key=lambda item: (
                "" if item[0] is None else item[0],
                "" if item[1] is None else item[1],
            ),
        ):
            expected_count = expected_identity_pairs.get((label, None), 0)
            observed_count = observed_pairs.get((label, None), 0)
            if observed_count != expected_count:
                errors.append(
                    f"{artifact_name}: exact inventory pair mismatch for "
                    f"({_format_identity_pair(label)}) "
                    f"(expected {expected_count}, found {observed_count}; "
                    f"observed identities: {pair_summary})"
                )
    return errors


def _find_template_placeholders(filename: str, content: str) -> list[str]:
    """Return template placeholder markers, with context-aware handling for ellipses."""
    found_placeholders = [
        p for p in TEMPLATE_PLACEHOLDERS if p != "..." and p in content
    ]

    if "..." not in content:
        return found_placeholders

    # Python code often contains valid ellipses in strings, type hints, or
    # function-call shorthand. Treat `...` as a placeholder only when it
    # appears in comments for Python files.
    if filename.endswith(".py"):
        try:
            for token in tokenize.generate_tokens(io.StringIO(content).readline):
                if token.type == tokenize.COMMENT and "..." in token.string:
                    found_placeholders.append("...")
                    break
        except tokenize.TokenError:
            # Fail closed for malformed Python content that still contains
            # template-style ellipses.
            found_placeholders.append("...")
        return found_placeholders

    # For non-Python files, check whether `...` appears inside code blocks
    # (fenced or inline backticks) or YAML block scalars containing code.
    # Ellipses in those contexts are not template placeholders.
    if _is_ellipsis_in_code_context(filename, content):
        return found_placeholders

    found_placeholders.append("...")
    return found_placeholders


# Regex patterns for detecting code contexts where `...` is legitimate
_FENCED_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_YAML_BLOCK_SCALAR_RE = re.compile(
    r"(?m)^[ \t]*(?:\w[\w_]*):[ \t]*(?:\||>)[+\-]?\n([ \t]+.*\n?)+",
)


def _is_ellipsis_in_code_context(filename: str, content: str) -> bool:
    """Return True if all `...` occurrences appear inside code contexts."""
    # Build a set of character spans that are code contexts
    code_spans: list[tuple[int, int]] = []

    # Fenced code blocks (``` ... ```)
    for match in _FENCED_CODE_BLOCK_RE.finditer(content):
        code_spans.append((match.start(), match.end()))

    # Inline code (` ... `)
    for match in _INLINE_CODE_RE.finditer(content):
        code_spans.append((match.start(), match.end()))

    # YAML block scalars (| or >) that contain code-like content
    # Heuristic: if the block contains parentheses, brackets, or dots,
    # treat it as code context
    for match in _YAML_BLOCK_SCALAR_RE.finditer(content):
        block_text = match.group(0)
        if any(ch in block_text for ch in ("(", ")", "[", "]", "{", "}", "...")):
            code_spans.append((match.start(), match.end()))

    # Check if every `...` falls within at least one code span
    for match in re.finditer(r"\.\.\.", content):
        ellipsis_start = match.start()
        ellipsis_end = match.end()
        in_code = any(
            span_start <= ellipsis_start and ellipsis_end <= span_end
            for span_start, span_end in code_spans
        )
        if not in_code:
            return False

    return True


def _is_missing_file_error(content: str, *, expected_path: str | None = None) -> bool:
    """Return True when a read_file 404 placeholder was mistaken for content."""
    match = _MISSING_FILE_ERROR_RE.match(content.strip())
    if not match:
        return False
    if expected_path is None:
        return True
    returned_path = match.group("path").strip().lstrip("/")
    normalized_expected = expected_path.strip().lstrip("/")
    return returned_path == normalized_expected


def _benchmark_refusal_error(reason: BenchmarkRefusalReason, message: str) -> str:
    return f"{reason.value}: {message}"


def _point_within_bounds(point: tuple[float, float, float], bounds: Any) -> bool:
    return all(
        float(bounds.min[index]) <= float(point[index]) <= float(bounds.max[index])
        for index in range(3)
    )


def _payload_trajectory_policy_role_for_stage(
    node_type: AgentName | str | None,
) -> AgentName:
    node_value = (
        node_type.value if isinstance(node_type, AgentName) else str(node_type or "")
    )
    if node_value in {
        AgentName.BENCHMARK_PLANNER.value,
        AgentName.BENCHMARK_PLAN_REVIEWER.value,
        AgentName.BENCHMARK_CODER.value,
        AgentName.BENCHMARK_REVIEWER.value,
    }:
        return AgentName.BENCHMARK_PLANNER
    return AgentName.ENGINEER_PLANNER


def _validate_payload_trajectory_budget(
    *,
    artifact_name: str,
    budget_role: AgentName,
    sample_stride_s: float,
    anchors: list[Any],
) -> list[str]:
    try:
        policy = load_agents_config().get_coarse_payload_trajectory_policy(budget_role)
    except Exception as exc:
        return [f"{artifact_name}: unable to load payload trajectory policy: {exc}"]

    errors: list[str] = []
    if sample_stride_s - policy.sample_stride_s > 1e-9:
        errors.append(
            f"{artifact_name}: sample_stride_s ({sample_stride_s:.3f}s) exceeds "
            f"the configured budget for {budget_role.value} "
            f"({policy.sample_stride_s:.3f}s)"
        )

    for anchor_index, anchor in enumerate(anchors):
        if any(
            float(observed) - float(limit) > 1e-9
            for observed, limit in zip(
                anchor.position_tolerance_mm,
                policy.position_tolerance_mm,
                strict=True,
            )
        ):
            errors.append(
                f"{artifact_name}: anchors[{anchor_index}].position_tolerance_mm "
                "exceeds the configured payload trajectory budget"
            )
        if anchor.rotation_tolerance_deg is not None and any(
            float(observed) - float(limit) > 1e-9
            for observed, limit in zip(
                anchor.rotation_tolerance_deg,
                policy.rotation_tolerance_deg,
                strict=True,
            )
        ):
            errors.append(
                f"{artifact_name}: anchors[{anchor_index}].rotation_tolerance_deg "
                "exceeds the configured payload trajectory budget"
            )

    return errors


def _validate_payload_endpoint_positions(
    *,
    artifact_name: str,
    benchmark_definition: BenchmarkDefinition,
    first_anchor: Any,
    last_anchor: Any,
    terminal_event: Any | None,
) -> list[str]:
    errors: list[str] = []
    build_zone = benchmark_definition.objectives.build_zone_mm
    goal_zone = benchmark_definition.objectives.goal_zone_mm

    if not _point_within_bounds(first_anchor.pos_mm, build_zone):
        errors.append(
            f"{artifact_name}: the first payload trajectory anchor must lie within "
            "benchmark_definition.objectives.build_zone_mm"
        )

    if last_anchor.goal_zone_contact or last_anchor.goal_zone_entry:
        if not _point_within_bounds(last_anchor.pos_mm, goal_zone):
            errors.append(
                f"{artifact_name}: the terminal payload trajectory anchor must lie within "
                "benchmark_definition.objectives.goal_zone_mm"
            )
    elif terminal_event is not None:
        if terminal_event.zone_name != "goal_zone":
            errors.append(
                f"{artifact_name}: terminal_event.zone_name must be 'goal_zone'"
            )
        if not _point_within_bounds(terminal_event.pos_mm, goal_zone):
            errors.append(
                f"{artifact_name}: terminal_event.pos_mm must lie within "
                "benchmark_definition.objectives.goal_zone_mm"
            )
    else:
        errors.append(
            f"{artifact_name}: payload trajectory must prove the terminal goal-zone "
            "entry/contact in the last anchor or terminal_event"
        )

    return errors


def _validate_payload_trajectory_contract(
    *,
    artifact_name: str,
    benchmark_definition: BenchmarkDefinition,
    payload_part_names: list[str],
    sample_stride_s: float,
    anchors: list[Any],
    terminal_event: Any | None,
    budget_role: AgentName,
    expected_payload_part_names: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []

    expected_names = sorted(
        name.strip() for name in (expected_payload_part_names or []) if name.strip()
    )
    observed_names = sorted(
        name.strip() for name in payload_part_names if str(name).strip()
    )
    if expected_payload_part_names is not None and observed_names != expected_names:
        errors.append(
            f"{artifact_name}: payload_part_names {observed_names} do not match "
            f"the expected payload parts {expected_names}"
        )
    elif expected_payload_part_names is None and not observed_names:
        errors.append(f"{artifact_name}: payload_part_names must not be empty")

    if len(anchors) < 2:
        errors.append(f"{artifact_name}: motion path must contain at least two anchors")
        return errors

    errors.extend(
        _validate_payload_trajectory_budget(
            artifact_name=artifact_name,
            budget_role=budget_role,
            sample_stride_s=sample_stride_s,
            anchors=anchors,
        )
    )
    errors.extend(
        _validate_payload_endpoint_positions(
            artifact_name=artifact_name,
            benchmark_definition=benchmark_definition,
            first_anchor=anchors[0],
            last_anchor=anchors[-1],
            terminal_event=terminal_event,
        )
    )
    return errors


def _payload_trajectory_definition_from_coarse_payload_trajectory(
    coarse_payload_trajectory: CoarsePayloadTrajectory,
) -> PayloadTrajectoryDefinition:
    first_anchor = coarse_payload_trajectory.anchors[0]
    return PayloadTrajectoryDefinition(
        backend=get_default_simulator_backend(),
        payload_part_names=coarse_payload_trajectory.payload_part_names,
        initial_pose=PayloadTrajectoryPose(
            reference_point=first_anchor.reference_point,
            pos_mm=first_anchor.pos_mm,
            rot_deg=first_anchor.rot_deg,
        ),
        sample_stride_s=coarse_payload_trajectory.sample_stride_s,
        anchors=coarse_payload_trajectory.anchors,
        terminal_event=coarse_payload_trajectory.terminal_event,
    )


def _relabel_payload_clearance_errors(
    errors: list[str],
    *,
    source_artifact: str,
    target_artifact: str,
) -> list[str]:
    source_prefix = f"{source_artifact}:"
    target_prefix = f"{target_artifact}:"
    relabeled: list[str] = []
    for error in errors:
        if error.startswith(source_prefix):
            relabeled.append(f"{target_prefix}{error[len(source_prefix) :]}")
        else:
            relabeled.append(error)
    return relabeled


def _validate_payload_trajectory_clearance_from_payload_definition(
    *,
    files_content_map: dict[str, str],
    benchmark_definition: BenchmarkDefinition,
    coarse_payload_trajectory: CoarsePayloadTrajectory,
    assembly_definition: AssemblyDefinition,
    benchmark_assembly_definition: AssemblyDefinition | None,
    session_id: str | None = None,
) -> list[str]:
    required_scripts = (
        BENCHMARK_SCRIPT_PATH,
        SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    )
    missing_scripts = [
        script_path
        for script_path in required_scripts
        if not (files_content_map.get(script_path) or "").strip()
    ]
    if missing_scripts:
        return [
            "assembly_definition.yaml.coarse_payload_trajectory: missing required planner "
            f"geometry artifact(s): {missing_scripts}"
        ]

    with tempfile.TemporaryDirectory(prefix="payload_trajectory_clearance_") as tmp:
        workspace_root = Path(tmp)
        for script_path in required_scripts:
            (workspace_root / script_path).write_text(
                files_content_map[script_path],
                encoding="utf-8",
            )

        payload_definition = (
            _payload_trajectory_definition_from_coarse_payload_trajectory(
                coarse_payload_trajectory
            )
        )
        clearance_errors = validate_payload_trajectory_swept_clearance(
            workspace_root=workspace_root,
            benchmark_definition=benchmark_definition,
            payload_definition=payload_definition,
            assembly_definition=assembly_definition,
            benchmark_assembly_definition=benchmark_assembly_definition,
            session_id=session_id,
            moving_script_path=SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
        )
        return _relabel_payload_clearance_errors(
            clearance_errors,
            source_artifact="payload_trajectory_definition.yaml",
            target_artifact="assembly_definition.yaml.coarse_payload_trajectory",
        )


def validate_payload_trajectory_definition_yaml(
    content: str,
    *,
    benchmark_definition: BenchmarkDefinition | None = None,
    coarse_payload_trajectory: CoarsePayloadTrajectory | None = None,
    expected_payload_part_names: list[str] | None = None,
    assembly_definition: AssemblyDefinition | None = None,
    benchmark_assembly_definition: AssemblyDefinition | None = None,
    workspace_root: Path | None = None,
    validate_clearance: bool = True,
    session_id: str | None = None,
) -> tuple[bool, PayloadTrajectoryDefinition | list[str]]:
    try:
        data = yaml.safe_load(content)
        if data is None:
            return False, ["Empty or invalid YAML content"]

        found_placeholders = _find_template_placeholders(
            "payload_trajectory_definition.yaml", content
        )
        if found_placeholders:
            return False, [
                "payload_trajectory_definition.yaml still contains template placeholders: "
                f"{found_placeholders}"
            ]

        precise_path = PayloadTrajectoryDefinition(**data)
    except yaml.YAMLError as e:
        logger.error(
            "payload_trajectory_definition_yaml_parse_error",
            error=str(e),
            session_id=session_id,
        )
        return False, [f"YAML parse error: {e}"]
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        logger.error(
            "payload_trajectory_definition_yaml_validation_error",
            errors=errors,
            session_id=session_id,
        )
        return False, errors

    if benchmark_definition is None:
        return True, precise_path

    coarse_names = (
        coarse_payload_trajectory.payload_part_names
        if coarse_payload_trajectory is not None
        else expected_payload_part_names
    )
    coarse_stride = (
        coarse_payload_trajectory.sample_stride_s
        if coarse_payload_trajectory is not None
        else None
    )
    try:
        coder_budget = load_agents_config().get_coarse_payload_trajectory_policy(
            AgentName.ENGINEER_CODER
        )
    except Exception as exc:
        return False, [
            "payload_trajectory_definition.yaml: unable to load payload "
            f"trajectory policy: {exc}"
        ]

    errors: list[str] = _validate_payload_trajectory_contract(
        artifact_name="payload_trajectory_definition.yaml",
        benchmark_definition=benchmark_definition,
        payload_part_names=precise_path.payload_part_names,
        sample_stride_s=precise_path.sample_stride_s,
        anchors=precise_path.anchors,
        terminal_event=precise_path.terminal_event,
        budget_role=AgentName.ENGINEER_CODER,
        expected_payload_part_names=coarse_names,
    )

    if (
        coarse_stride is not None
        and precise_path.sample_stride_s - coarse_stride > 1e-9
    ):
        errors.append(
            "payload_trajectory_definition.yaml: sample_stride_s "
            f"({precise_path.sample_stride_s:.3f}s) must be less than or equal to "
            "the coarse payload trajectory sample_stride_s "
            f"({coarse_stride:.3f}s)"
        )
    if precise_path.sample_stride_s - coder_budget.sample_stride_s > 1e-9:
        errors.append(
            "payload_trajectory_definition.yaml: sample_stride_s "
            f"({precise_path.sample_stride_s:.3f}s) exceeds the engineer_coder "
            f"budget ({coder_budget.sample_stride_s:.3f}s)"
        )

    if coarse_payload_trajectory is not None:
        coarse_set = {
            name.strip()
            for name in coarse_payload_trajectory.payload_part_names
            if name.strip()
        }
        precise_set = {
            name.strip() for name in precise_path.payload_part_names if name.strip()
        }
        if precise_set != coarse_set:
            errors.append(
                "payload_trajectory_definition.yaml: payload_part_names must match "
                "the approved coarse payload trajectory"
            )

    if errors:
        return False, errors

    if validate_clearance and benchmark_definition is not None:
        clearance_errors = validate_payload_trajectory_swept_clearance(
            workspace_root=workspace_root or Path.cwd(),
            benchmark_definition=benchmark_definition,
            payload_definition=precise_path,
            assembly_definition=assembly_definition,
            benchmark_assembly_definition=benchmark_assembly_definition,
            session_id=session_id,
        )
        if clearance_errors:
            return False, clearance_errors

    logger.info("payload_trajectory_definition_yaml_valid", session_id=session_id)
    return True, precise_path


validate_precise_path_definition_yaml = validate_payload_trajectory_definition_yaml


def validate_benchmark_definition_yaml(
    content: str, session_id: str | None = None
) -> tuple[bool, BenchmarkDefinition | list[str]]:
    """
    Parse and validate benchmark_definition.yaml content.

    Args:
        content: Raw YAML string content
        session_id: Optional session ID for logging

    Returns:
        (True, BenchmarkDefinition) if valid
        (False, list[str]) with error messages if invalid
    """
    try:
        data = yaml.safe_load(content)
        if data is None:
            return False, ["Empty or invalid YAML content"]

        benchmark_parts = data.get("benchmark_parts")
        if not isinstance(benchmark_parts, list) or not benchmark_parts:
            return False, [
                "benchmark_definition.yaml must declare at least one benchmark_parts entry"
            ]

        data = _normalize_benchmark_definition_contract(data)

        # 1. Enforce that file is not the template
        found_placeholders = _find_template_placeholders(
            "benchmark_definition.yaml", content
        )
        if found_placeholders:
            return False, [
                f"benchmark_definition.yaml still contains template placeholders: {found_placeholders}"
            ]

        objectives = BenchmarkDefinition(**data)

        material_id = objectives.payload.material_id
        manufacturing_config = load_config()
        known_material_ids = set(manufacturing_config.materials.keys())
        known_material_ids.update(manufacturing_config.cnc.materials.keys())
        known_material_ids.update(
            manufacturing_config.injection_molding.materials.keys()
        )
        known_material_ids.update(manufacturing_config.three_dp.materials.keys())
        if material_id not in known_material_ids:
            return False, [
                "payload.material_id must reference a known material from "
                f"manufacturing_config.yaml (got '{material_id}')"
            ]

        objective_error = _validate_benchmark_definition_consistency(objectives)
        if objective_error:
            logger.error(
                "benchmark_definition_yaml_invalid",
                errors=[objective_error],
                session_id=session_id,
            )
            return False, [objective_error]

        logger.info("benchmark_definition_yaml_valid", session_id=session_id)
        return True, objectives
    except yaml.YAMLError as e:
        logger.error(
            "benchmark_definition_yaml_parse_error", error=str(e), session_id=session_id
        )
        return False, [f"YAML parse error: {e}"]
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        logger.error(
            "benchmark_definition_yaml_validation_error",
            errors=errors,
            session_id=session_id,
        )
        return False, errors


def validate_assembly_definition_yaml(
    content: str,
    session_id: str | None = None,
    manufacturing_config: ManufacturingConfig | None = None,
    exact_weight: bool = False,
) -> tuple[bool, AssemblyDefinition | list[str]]:
    """
    Parse and validate assembly_definition.yaml content.

    Args:
        content: Raw YAML string content
        session_id: Optional session ID for logging

    Returns:
        (True, AssemblyDefinition) if valid
        (False, list[str]) with error messages if invalid
    """
    try:
        data = yaml.safe_load(content)
        if data is None:
            return False, ["Empty or invalid YAML content"]

        # 1. Check for template placeholders in cost estimation too
        found_placeholders = _find_template_placeholders(
            "assembly_definition.yaml", content
        )
        if found_placeholders:
            return False, [
                f"assembly_definition.yaml still contains template placeholders: {found_placeholders}"
            ]

        estimation = AssemblyDefinition(**data)
        effective_config = manufacturing_config or load_config()
        cost_errors = validate_declared_planner_cost_contract(
            assembly_definition=estimation,
            manufacturing_config=effective_config,
        )
        if cost_errors:
            logger.error(
                "cost_estimation_yaml_invalid",
                errors=cost_errors,
                session_id=session_id,
            )
            return False, cost_errors

        if exact_weight:
            weight_errors = validate_exact_planner_weight_contract(
                assembly_definition=estimation,
                manufacturing_config=effective_config,
            )
            if weight_errors:
                logger.error(
                    "weight_estimation_yaml_invalid",
                    errors=weight_errors,
                    session_id=session_id,
                )
                return False, weight_errors

        logger.info("cost_estimation_yaml_valid", session_id=session_id)
        return True, estimation
    except yaml.YAMLError as e:
        logger.error(
            "cost_estimation_yaml_parse_error", error=str(e), session_id=session_id
        )
        return False, [f"YAML parse error: {e}"]
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        logger.error(
            "cost_estimation_yaml_validation_error",
            errors=errors,
            session_id=session_id,
        )
        return False, errors


def validate_benchmark_assembly_payload_contract(
    *,
    benchmark_definition: BenchmarkDefinition | None,
    assembly_definition: AssemblyDefinition,
    plan_text: str | None = None,
    todo_text: str | None = None,
    plan_refusal_text: str | None = None,
) -> list[str]:
    """Validate benchmark-side payload fixtures from structured YAML only."""
    errors: list[str] = []
    if plan_refusal_text is not None:
        is_valid_refusal, _ = validate_plan_refusal(plan_refusal_text)
        if is_valid_refusal:
            return errors

    if assembly_definition.coarse_payload_trajectory is not None:
        errors.append(
            _benchmark_refusal_error(
                BenchmarkRefusalReason.CONTRADICTORY_CONSTRAINTS,
                "benchmark_assembly_definition.yaml must not declare "
                "coarse_payload_trajectory; benchmark payload motion is encoded "
                "through the benchmark fixtures instead",
            )
        )
    return errors


validate_benchmark_assembly_motion_contract = (
    validate_benchmark_assembly_payload_contract
)


def validate_declared_planner_cost_contract(
    *,
    assembly_definition: AssemblyDefinition,
    manufacturing_config: ManufacturingConfig,
) -> list[str]:
    """Validate that planner totals include deterministic declared costs."""
    return validate_declared_assembly_cost(assembly_definition, manufacturing_config)


def validate_declared_planner_weight_contract(
    *,
    assembly_definition: AssemblyDefinition,
    manufacturing_config: ManufacturingConfig,
) -> list[str]:
    """Validate that planner totals include deterministic declared weights."""
    return validate_declared_assembly_weight(assembly_definition, manufacturing_config)


def validate_exact_planner_cost_contract(
    *,
    assembly_definition: AssemblyDefinition,
    manufacturing_config: ManufacturingConfig,
) -> list[str]:
    """Validate that planner totals exactly match deterministic declared costs."""
    return validate_exact_declared_assembly_cost(
        assembly_definition, manufacturing_config
    )


def validate_exact_planner_weight_contract(
    *,
    assembly_definition: AssemblyDefinition,
    manufacturing_config: ManufacturingConfig,
) -> list[str]:
    """Validate that planner totals exactly match deterministic declared weights."""
    return validate_exact_declared_assembly_weight(
        assembly_definition, manufacturing_config
    )


def validate_planner_handoff_cross_contract(
    *,
    benchmark_definition: BenchmarkDefinition,
    assembly_definition: AssemblyDefinition,
    manufacturing_config: ManufacturingConfig,
    planner_node_type: AgentName | str | None = None,
    files_content_map: dict[str, str] | None = None,
    plan_text: str | None = None,
    session_id: str | None = None,
) -> list[str]:
    """Validate planner targets against benchmark caps and reject stale copies."""
    errors: list[str] = []
    try:
        plan_artifact_name = plan_path_for_agent(planner_node_type).as_posix()
    except ValueError as exc:
        return [str(exc)]
    planner_node_value = (
        planner_node_type.value
        if isinstance(planner_node_type, AgentName)
        else str(planner_node_type or "")
    )
    is_benchmark_planner = planner_node_value in {
        AgentName.BENCHMARK_PLANNER.value,
        AgentName.BENCHMARK_PLAN_REVIEWER.value,
        AgentName.BENCHMARK_CODER.value,
        AgentName.BENCHMARK_REVIEWER.value,
    }
    is_engineer_planner = planner_node_value in {
        AgentName.ENGINEER_PLANNER.value,
        AgentName.ENGINEER_PLAN_REVIEWER.value,
        AgentName.ENGINEER_CODER.value,
        AgentName.ENGINEER_EXECUTION_REVIEWER.value,
    }
    is_engineer_planner_boundary = planner_node_value in {
        AgentName.ENGINEER_PLANNER.value,
        AgentName.ENGINEER_PLAN_REVIEWER.value,
    }

    errors.extend(_validate_assembly_inventory_parity(assembly_definition))

    if plan_text is not None:
        if is_benchmark_planner:
            plan_tokens = Counter(
                dict.fromkeys(
                    set(
                        _planner_plan_grounding_tokens_from_benchmark(
                            benchmark_definition
                        ).keys()
                    )
                    | set(
                        _planner_plan_grounding_tokens_from_assembly(
                            assembly_definition
                        ).keys()
                    ),
                    1,
                )
            )
        elif is_engineer_planner:
            plan_tokens = Counter(
                dict.fromkeys(
                    _planner_plan_grounding_tokens_from_assembly(assembly_definition), 1
                )
            )
        else:
            plan_tokens = Counter()
        errors.extend(
            _validate_exact_identifier_mentions(
                artifact_name=plan_artifact_name,
                content=plan_text,
                required_tokens=plan_tokens,
            )
        )

    planner_cap_pairs = (
        (
            "benchmark_definition.constraints.max_unit_cost",
            benchmark_definition.constraints.max_unit_cost,
            "assembly_definition.constraints.planner_target_max_unit_cost_usd",
            assembly_definition.constraints.planner_target_max_unit_cost_usd,
        ),
        (
            "benchmark_definition.constraints.max_weight_g",
            benchmark_definition.constraints.max_weight_g,
            "assembly_definition.constraints.planner_target_max_weight_g",
            assembly_definition.constraints.planner_target_max_weight_g,
        ),
    )
    for (
        expected_label,
        expected_value,
        observed_label,
        observed_value,
    ) in planner_cap_pairs:
        if expected_value is None:
            errors.append(f"{expected_label} is missing; cannot validate planner caps")
            continue
        if observed_value is None:
            errors.append(f"{observed_label} is missing; planner caps are required")
            continue
        if observed_value - expected_value > 1e-6:
            if observed_label.endswith("planner_target_max_unit_cost_usd"):
                errors.append(
                    "Planner target cost "
                    f"({observed_value:.1f}) must be less than or equal to "
                    f"benchmark max cost ({expected_value:.1f})"
                )
            elif observed_label.endswith("planner_target_max_weight_g"):
                errors.append(
                    "Planner target weight "
                    f"({observed_value:.1f}) must be less than or equal to "
                    f"benchmark max weight ({expected_value:.1f})"
                )
            else:
                errors.append(
                    f"{observed_label} ({observed_value:.2f}) must be less than or equal "
                    f"to {expected_label} ({expected_value:.2f})"
                )

    copied_cap_pairs = (
        (
            "benchmark_definition.constraints.max_unit_cost",
            benchmark_definition.constraints.max_unit_cost,
            "assembly_definition.constraints.benchmark_max_unit_cost_usd",
            assembly_definition.constraints.benchmark_max_unit_cost_usd,
        ),
        (
            "benchmark_definition.constraints.max_weight_g",
            benchmark_definition.constraints.max_weight_g,
            "assembly_definition.constraints.benchmark_max_weight_g",
            assembly_definition.constraints.benchmark_max_weight_g,
        ),
    )
    for (
        expected_label,
        expected_value,
        observed_label,
        observed_value,
    ) in copied_cap_pairs:
        if observed_value is None:
            continue
        if expected_value is None:
            errors.append(
                f"{expected_label} is missing; cannot validate copied benchmark caps"
            )
            continue
        if abs(observed_value - expected_value) > 1e-6:
            errors.append(
                f"{observed_label} ({observed_value:.2f}) must equal "
                f"{expected_label} ({expected_value:.2f})"
            )

    payload_part_names = [part.part_name for part in assembly_definition.payload_parts]
    coarse_payload_trajectory = assembly_definition.coarse_payload_trajectory
    if is_engineer_planner and coarse_payload_trajectory is None:
        errors.append(
            "assembly_definition.coarse_payload_trajectory is required for "
            "engineer handoffs"
        )
    elif coarse_payload_trajectory is not None:
        expected_payload_part_names = payload_part_names if payload_part_names else None
        errors.extend(
            _validate_payload_trajectory_contract(
                artifact_name="assembly_definition.yaml.coarse_payload_trajectory",
                benchmark_definition=benchmark_definition,
                payload_part_names=coarse_payload_trajectory.payload_part_names,
                sample_stride_s=coarse_payload_trajectory.sample_stride_s,
                anchors=coarse_payload_trajectory.anchors,
                terminal_event=coarse_payload_trajectory.terminal_event,
                budget_role=_payload_trajectory_policy_role_for_stage(
                    planner_node_type
                ),
                expected_payload_part_names=expected_payload_part_names,
            )
        )
        if is_engineer_planner_boundary:
            if files_content_map is None:
                errors.append(
                    "assembly_definition.yaml.coarse_payload_trajectory: "
                    "benchmark_script.py "
                    "and solution_plan_evidence_script.py are required to validate "
                    "planner clearance"
                )
            else:
                errors.extend(
                    _validate_payload_trajectory_clearance_from_payload_definition(
                        files_content_map=files_content_map,
                        benchmark_definition=benchmark_definition,
                        coarse_payload_trajectory=coarse_payload_trajectory,
                        assembly_definition=assembly_definition,
                        benchmark_assembly_definition=None,
                        session_id=session_id,
                    )
                )

    errors.extend(
        validate_exact_planner_cost_contract(
            assembly_definition=assembly_definition,
            manufacturing_config=manufacturing_config,
        )
    )
    return errors


def validate_review_frontmatter(
    content: str, cad_agent_refused: bool = False, session_id: str | None = None
) -> tuple[bool, ReviewFrontmatter | list[str]]:
    """
    Parse and validate review markdown frontmatter.

    Args:
        content: Raw markdown content with YAML frontmatter
        cad_agent_refused: Whether the CAD agent refused the plan
            (determines if refusal decisions are valid)
        session_id: Optional session ID for logging

    Returns:
        (True, ReviewFrontmatter) if valid
        (False, list[str]) with error messages if invalid
    """
    # Extract YAML frontmatter
    frontmatter_match = re.search(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not frontmatter_match:
        return False, [
            "Missing YAML frontmatter (must start with --- and end with ---)"
        ]

    try:
        data = yaml.safe_load(frontmatter_match.group(1))
        if data is None:
            return False, ["Empty frontmatter"]

        frontmatter = ReviewFrontmatter(**data)

        # Context-specific validation: refusal decisions
        is_refusal_decision = frontmatter.decision in (
            "confirm_plan_refusal",
            "reject_plan_refusal",
        )
        if is_refusal_decision and not cad_agent_refused:
            return False, [
                f"Decision '{frontmatter.decision}' is only valid "
                "when CAD agent refused the plan"
            ]

        logger.info(
            "review_frontmatter_valid",
            decision=frontmatter.decision,
            session_id=session_id,
        )
        return True, frontmatter
    except yaml.YAMLError as e:
        logger.error(
            "review_frontmatter_parse_error", error=str(e), session_id=session_id
        )
        return False, [f"YAML parse error: {e}"]
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        logger.error(
            "review_frontmatter_validation_error", errors=errors, session_id=session_id
        )
        return False, errors


def validate_plan_refusal(
    content: str, session_id: str | None = None
) -> tuple[bool, PlanRefusalFrontmatter | list[str]]:
    """
    Parse and validate plan_refusal.md content.
    Requires structured frontmatter and evidence in the body.
    """
    # Extract YAML frontmatter
    frontmatter_match = re.search(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not frontmatter_match:
        return False, ["Missing YAML frontmatter in plan_refusal.md"]

    body = content[frontmatter_match.end() :].strip()
    if not body:
        return False, ["plan_refusal.md must include evidence in the body"]

    try:
        data = yaml.safe_load(frontmatter_match.group(1))
        if data is None:
            return False, ["Empty frontmatter in plan_refusal.md"]

        frontmatter = PlanRefusalFrontmatter(**data)
        logger.info(
            "plan_refusal_valid",
            role=frontmatter.role,
            reasons=frontmatter.reasons,
            session_id=session_id,
        )
        return True, frontmatter
    except yaml.YAMLError as e:
        logger.error("plan_refusal_parse_error", error=str(e), session_id=session_id)
        return False, [f"YAML parse error: {e}"]
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        logger.warning("plan_refusal_validation_error", errors=errors)
        return False, errors


def validate_node_output(
    node_type: str,
    files_content_map: dict[str, str],
    session_id: str | None = None,
    manufacturing_config: ManufacturingConfig | None = None,
) -> tuple[bool, list[str]]:
    """
    Universally validate node output for required files and template placeholders.

    Args:
        node_type: planner or coder role identifier.
        files_content_map: Mapping of filename to string content.
        session_id: Optional session ID for logging

    Returns:
        (True, []) if valid
        (False, list[str]) with error messages if invalid
    """
    errors = []
    benchmark_definition_model: BenchmarkDefinition | None = None
    assembly_definition_models: dict[str, AssemblyDefinition] = {}
    payload_trajectory_definition_content: str | None = None
    payload_trajectory_definition_model: PayloadTrajectoryDefinition | None = None
    effective_config = manufacturing_config
    try:
        node_enum = (
            node_type if isinstance(node_type, AgentName) else AgentName(node_type)
        )
    except Exception:
        node_enum = None
    node_key = node_enum if node_enum is not None else node_type
    try:
        plan_artifact_name = plan_path_for_agent(node_key).as_posix()
    except ValueError as exc:
        return False, [str(exc)]
    plan_content = files_content_map.get(plan_artifact_name)

    def _missing_file(path: str) -> bool:
        content = files_content_map.get(path)
        if content is None or not content.strip():
            return True
        return _is_missing_file_error(content, expected_path=path)

    # 1. Required files check
    # If plan_refusal.md is present and valid, skip regular required files check
    if "plan_refusal.md" in files_content_map:
        is_refusal_valid, _ = validate_plan_refusal(
            files_content_map["plan_refusal.md"], session_id=session_id
        )
        if is_refusal_valid:
            # Only validate plan_refusal.md and skip others
            required_files = ["plan_refusal.md"]
        else:
            # If refusal is invalid, we still want regular files or a better refusal
            required_files = {
                AgentName.ENGINEER_PLANNER: [
                    plan_artifact_name,
                    "todo.md",
                    "benchmark_definition.yaml",
                    "assembly_definition.yaml",
                    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
                ],
                AgentName.BENCHMARK_PLANNER: [
                    plan_artifact_name,
                    "todo.md",
                    "benchmark_definition.yaml",
                    "benchmark_assembly_definition.yaml",
                    BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
                ],
                AgentName.ENGINEER_CODER: [
                    plan_artifact_name,
                    "todo.md",
                    "benchmark_definition.yaml",
                    SOLUTION_SCRIPT_PATH,
                ],
                AgentName.BENCHMARK_CODER: [
                    plan_artifact_name,
                    "todo.md",
                    "benchmark_definition.yaml",
                    BENCHMARK_SCRIPT_PATH,
                ],
            }.get(node_key, [])
    else:
        required_files = {
            AgentName.ENGINEER_PLANNER: [
                plan_artifact_name,
                "todo.md",
                "benchmark_definition.yaml",
                "assembly_definition.yaml",
                SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
            ],
            AgentName.BENCHMARK_PLANNER: [
                plan_artifact_name,
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
                BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
            ],
            AgentName.ENGINEER_CODER: [
                plan_artifact_name,
                "todo.md",
                "benchmark_definition.yaml",
                "payload_trajectory_definition.yaml",
                SOLUTION_SCRIPT_PATH,
            ],
            AgentName.BENCHMARK_CODER: [
                plan_artifact_name,
                "todo.md",
                "benchmark_definition.yaml",
                BENCHMARK_SCRIPT_PATH,
            ],
        }.get(node_key, [])

    for req_file in required_files:
        if _missing_file(req_file):
            errors.append(f"Missing required file: {req_file}")

    # 2. Template placeholder check
    for filename, content in files_content_map.items():
        if _is_missing_file_error(content, expected_path=filename):
            continue
        found_placeholders = _find_template_placeholders(filename, content)
        if found_placeholders:
            placeholder_list = ", ".join(found_placeholders)
            errors.append(
                f"File '{filename}' contains template placeholders: {placeholder_list}"
            )

    # 3. Specific validation for known formats
    for filename, content in files_content_map.items():
        if _is_missing_file_error(content, expected_path=filename):
            continue
        if filename == plan_artifact_name:
            plan_type = "engineering"  # Default to engineering for most nodes
            if "benchmark" in str(node_key) or "# Learning Objective" in content:
                plan_type = "benchmark"

            is_valid, plan_errors = validate_plan_md_structure(
                content,
                plan_type,
                session_id=session_id,
                artifact_path=filename,
            )
            if not is_valid:
                errors.extend([f"{filename}: {e}" for e in plan_errors])
        elif filename == "todo.md":
            from shared.workers.markdown_validator import validate_todo_md

            res = validate_todo_md(content)
            if not res.is_valid:
                errors.extend([f"todo.md: {e}" for e in res.violations])
        elif filename == "benchmark_definition.yaml":
            is_valid, obj_res = validate_benchmark_definition_yaml(
                content, session_id=session_id
            )
            if not is_valid:
                # obj_res is list[str] on failure
                errors.extend([f"benchmark_definition.yaml: {e}" for e in obj_res])
            else:
                benchmark_definition_model = obj_res
        elif filename in {
            "assembly_definition.yaml",
            "benchmark_assembly_definition.yaml",
        }:
            if effective_config is None:
                if "manufacturing_config.yaml" in files_content_map:
                    custom_config = yaml.safe_load(
                        files_content_map["manufacturing_config.yaml"]
                    )
                    effective_config = load_merged_config(
                        override_data=custom_config or {}
                    )
                else:
                    effective_config = load_config()
            is_valid, asm_res = validate_assembly_definition_yaml(
                content,
                session_id=session_id,
                manufacturing_config=effective_config,
                exact_weight=filename == "assembly_definition.yaml",
            )
            if not is_valid:
                # asm_res is list[str] on failure
                errors.extend([f"{filename}: {e}" for e in asm_res])
            else:
                assembly_definition_models[filename] = asm_res
                if filename == "benchmark_assembly_definition.yaml":
                    motion_errors = validate_benchmark_assembly_payload_contract(
                        benchmark_definition=benchmark_definition_model,
                        assembly_definition=asm_res,
                        plan_text=plan_content,
                        todo_text=files_content_map.get("todo.md"),
                        plan_refusal_text=files_content_map.get("plan_refusal.md"),
                    )
                    if motion_errors:
                        errors.extend([f"{filename}: {e}" for e in motion_errors])
        elif filename == "payload_trajectory_definition.yaml":
            payload_trajectory_definition_content = content
        elif filename == "plan_refusal.md":
            is_valid, refusal_res = validate_plan_refusal(
                content, session_id=session_id
            )
            if not is_valid:
                if isinstance(refusal_res, list):
                    errors.extend([f"plan_refusal.md: {e}" for e in refusal_res])
                else:
                    # Should not happen based on validate_plan_refusal return type
                    errors.append("plan_refusal.md: Invalid structure")
        elif filename in {
            BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
            SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
        }:
            errors.extend(
                [
                    f"{filename}: {message}"
                    for message in validate_planner_evidence_script_layout_contract(
                        artifact_name=filename,
                        content=content,
                    )
                ]
            )

    if benchmark_definition_model is not None and assembly_definition_models:
        if effective_config is None:
            effective_config = load_config()
        for filename, assembly_definition_model in assembly_definition_models.items():
            cross_contract_errors = validate_planner_handoff_cross_contract(
                benchmark_definition=benchmark_definition_model,
                assembly_definition=assembly_definition_model,
                manufacturing_config=effective_config,
                planner_node_type=node_type,
                files_content_map=files_content_map,
                plan_text=plan_content,
                session_id=session_id,
            )
            if cross_contract_errors:
                errors.extend(
                    [f"{filename}: {message}" for message in cross_contract_errors]
                )

    engineering_assembly_definition_model = assembly_definition_models.get(
        "assembly_definition.yaml"
    )
    benchmark_assembly_definition_model = assembly_definition_models.get(
        "benchmark_assembly_definition.yaml"
    )
    if payload_trajectory_definition_content is not None and node_enum in {
        AgentName.ENGINEER_PLANNER,
        AgentName.ENGINEER_CODER,
    }:
        is_valid, precise_result = validate_payload_trajectory_definition_yaml(
            payload_trajectory_definition_content,
            benchmark_definition=benchmark_definition_model,
            coarse_payload_trajectory=(
                engineering_assembly_definition_model.coarse_payload_trajectory
                if engineering_assembly_definition_model is not None
                else None
            ),
            assembly_definition=engineering_assembly_definition_model,
            benchmark_assembly_definition=benchmark_assembly_definition_model,
            workspace_root=Path.cwd(),
            expected_payload_part_names=(
                [
                    part.part_name
                    for part in engineering_assembly_definition_model.payload_parts
                ]
                if engineering_assembly_definition_model is not None
                else None
            ),
            session_id=session_id,
        )
        if not is_valid and isinstance(precise_result, list):
            errors.extend(precise_result)
        elif is_valid:
            payload_trajectory_definition_model = precise_result

    if (
        payload_trajectory_definition_model is not None
        and benchmark_definition_model is not None
    ):
        errors.extend(
            _validate_payload_trajectory_clearance_from_payload_definition(
                files_content_map=files_content_map,
                benchmark_definition=benchmark_definition_model,
                payload_definition=payload_trajectory_definition_model,
                assembly_definition=engineering_assembly_definition_model,
                benchmark_assembly_definition=benchmark_assembly_definition_model,
                session_id=session_id,
            )
        )

    return len(errors) == 0, errors


def validate_plan_md_structure(
    content: str,
    plan_type: str = "benchmark",
    session_id: str | None = None,
    artifact_path: str | None = None,
) -> tuple[bool, list[str]]:
    """
    Validate a split plan file has required sections.

    Args:
        content: Raw markdown content
        plan_type: "benchmark" or "engineering"
        session_id: Optional session ID for logging

    Returns:
        (True, []) if valid
        (False, list[str]) with missing section names if invalid
    """
    if artifact_path is None:
        artifact_path = (
            "engineering_plan.md" if plan_type == "engineering" else "benchmark_plan.md"
        )
    if plan_type == "engineering":
        from shared.workers.markdown_validator import validate_plan_md

        result = validate_plan_md(content, plan_type=plan_type)
        if not result.is_valid:
            logger.error(
                "plan_md_missing_sections",
                missing=result.violations,
                session_id=session_id,
            )
            return False, result.violations

        logger.info("plan_md_valid", plan_type=plan_type, session_id=session_id)
        return True, []

    from shared.workers.markdown_validator import validate_plan_md

    result = validate_plan_md(content, plan_type=plan_type)
    if not result.is_valid:
        logger.error(
            "plan_md_missing_sections",
            missing=result.violations,
            session_id=session_id,
        )
        return False, result.violations

    logger.info("plan_md_valid", plan_type=plan_type, session_id=session_id)
    return True, []


def calculate_file_hash(path: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    if not path.exists():
        return ""
    sha256_hash = hashlib.sha256()
    with path.open("rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def validate_immutability(
    path: Path, session_id: str | None = None
) -> tuple[bool, str | None]:
    """
    Verify that a file has not changed since the initial commit (or baseline).

    Strategy:
    1. Check if git is available and repo is initialized.
    2. Get the hash of the file from the *first* commit (benchmark baseline).
    3. Compare with current hash.

    Returns:
        (True, None) if immutable or cannot verify.
        (False, error_message) if changed.
    """
    if not path.exists():
        return True, None

    try:
        # Check if inside a git repo
        subprocess.check_output(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path.parent,
            stderr=subprocess.DEVNULL,
        )

        # Get the first commit hash (root commit where benchmark was generated)
        # We assume the benchmark generator commits the initial state.
        root_commit = subprocess.check_output(
            ["git", "rev-list", "--max-parents=0", "HEAD"], cwd=path.parent, text=True
        ).strip()

        if not root_commit:
            # No commits yet, can't verify against baseline
            return True, None

        # Get the hash of the file at the root commit
        # git show <commit>:<path>
        try:
            original_content = subprocess.check_output(
                ["git", "show", f"{root_commit}:{path.name}"],
                cwd=path.parent,
                stderr=subprocess.DEVNULL,
            )
            original_hash = hashlib.sha256(original_content).hexdigest()
            current_hash = calculate_file_hash(path)

            if original_hash != current_hash:
                msg = (
                    f"Immutability violation: {path.name} has been modified "
                    "from the benchmark baseline."
                )
                logger.error(
                    "immutability_violation", path=str(path), session_id=session_id
                )
                return False, msg

        except subprocess.CalledProcessError:
            # File might not have existed in root commit (e.g. created later)
            # In that case, immutability check might not apply or is ambiguous.
            # Ideally benchmark_definition.yaml SHOULD exist in root commit.
            pass

    except (subprocess.CalledProcessError, FileNotFoundError):
        # Git not installed or not a repo, skip check
        pass
    except Exception as e:
        logger.error(
            "immutability_check_failed_internal",
            error=str(e),
            session_id=session_id,
        )

    return True, None
