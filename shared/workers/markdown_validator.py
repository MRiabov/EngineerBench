"""
Markdown validation utilities for benchmark_plan.md / engineering_plan.md and
todo.md files.

Validates structural requirements as per desired_architecture.md.
"""

import re

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    """Result of markdown validation."""

    is_valid: bool
    violations: list[str] = Field(default_factory=list)


ENGINEERING_PLAN_REQUIRED_SECTIONS = [
    "## 1. Solution Overview",
    "## 2. Parts List",
    "## 3. Assembly Strategy",
    "## 4. Assumption Register",
    "## 5. Detailed Calculations",
    "## 6. Critical Constraints / Operating Envelope",
    "## 7. Cost & Weight Budget",
    "## 8. Risk Assessment",
]

# Strict heading patterns (numbered headings required)
ENGINEERING_PLAN_SECTION_PATTERNS = [
    r"^##\s*1\.\s*Solution\s+Overview\s*$",
    r"^##\s*2\.\s*Parts\s+List\s*$",
    r"^##\s*3\.\s*Assembly\s+Strategy\s*$",
    r"^##\s*4\.\s*Assumption\s+Register\s*$",
    r"^##\s*5\.\s*Detailed\s+Calculations\s*$",
    r"^##\s*6\.\s*Critical\s+Constraints\s*/\s*Operating\s+Envelope\s*$",
    r"^##\s*7\.\s*Cost\s*(?:&|and)\s*Weight\s+Budget\s*$",
    r"^##\s*8\.\s*Risk\s+Assessment\s*$",
]

BENCHMARK_PLAN_VARIANTS = [
    {
        "required_sections": [
            "## 1. Learning Objective",
            "## 2. Static Geometry",
            "## 3. Input Object",
            "## 4. Objectives",
            "## 5. Design",
            "## 6. Randomization",
            "## 7. Build123d Strategy",
            "## 8. Cost & Weight Envelope",
            "## 9. Part Metadata",
        ],
        "section_patterns": [
            r"^##\s*1\.\s*Learning\s+Objective\s*$",
            r"^##\s*2\.\s*Static\s+Geometry\s*$",
            r"^##\s*3\.\s*Input\s+Object\s*$",
            r"^##\s*4\.\s*Objectives\s*$",
            r"^##\s*5\.\s*Design\s*$",
            r"^##\s*6\.\s*Randomization\s*$",
            r"^##\s*7\.\s*Build123d\s+Strategy\s*$",
            r"^##\s*8\.\s*Cost\s*&\s*Weight\s+Envelope\s*$",
            r"^##\s*9\.\s*Part\s+Metadata\s*$",
        ],
    },
    {
        "required_sections": [
            "## 1. Solution Overview",
            "## 2. Parts List",
            "## 3. Assembly Strategy",
            "## 4. Assumption Register",
            "## 5. Detailed Calculations",
            "## 6. Critical Constraints / Operating Envelope",
            "## 7. Cost & Weight Budget",
            "## 8. Risk Assessment",
        ],
        "section_patterns": [
            r"^##\s*1\.\s*Solution\s+Overview\s*$",
            r"^##\s*2\.\s*Parts\s+List\s*$",
            r"^##\s*3\.\s*Assembly\s+Strategy\s*$",
            r"^##\s*4\.\s*Assumption\s+Register\s*$",
            r"^##\s*5\.\s*Detailed\s+Calculations\s*$",
            r"^##\s*6\.\s*Critical\s+Constraints\s*/\s*Operating\s+Envelope\s*$",
            r"^##\s*7\.\s*Cost\s*&\s*Weight\s+Budget\s*$",
            r"^##\s*8\.\s*Risk\s+Assessment\s*$",
        ],
    },
    {
        "required_sections": [
            "## 1. Learning Objective",
            "## 2. Environment Geometry",
            "## 3. Input Objective",
            "## 4. Objectives",
            "## 5. Simulation Bounds",
            "## 6. Constraints Handed To Engineering",
            "## 7. Success Criteria",
            "## 8. Planner Artifacts",
        ],
        "section_patterns": [
            r"^##\s*1\.\s*Learning\s+Objective\s*$",
            r"^##\s*2\.\s*Environment\s+Geometry\s*$",
            r"^##\s*3\.\s*Input\s+Objective\s*$",
            r"^##\s*4\.\s*Objectives\s*$",
            r"^##\s*5\.\s*Simulation\s+Bounds\s*$",
            r"^##\s*6\.\s*Constraints\s+Handed\s+To\s+Engineering\s*$",
            r"^##\s*7\.\s*Success\s+Criteria\s*$",
            r"^##\s*8\.\s*Planner\s+Artifacts\s*$",
        ],
    },
    {
        "required_sections": [
            "## 1. Learning Objective",
            "## 2. Geometry",
            "## 3. Objectives",
            "## 4. Randomization",
            "## 5. Implementation Notes",
        ],
        "section_patterns": [
            r"^##\s*1\.\s*Learning\s+Objective\s*$",
            r"^##\s*2\.\s*Geometry\s*$",
            r"^##\s*3\.\s*Objectives\s*$",
            r"^##\s*4\.\s*Randomization\s*$",
            r"^##\s*5\.\s*Implementation\s+Notes\s*$",
        ],
    },
]

# Valid checkbox patterns for todo.md
TODO_CHECKBOX_PATTERN = re.compile(r"^\s*-\s*\[([ xX/\-])\]", re.MULTILINE)
INVALID_CHECKBOX_PATTERN = re.compile(r"^\s*-\s*\[[^\]]*\]", re.MULTILINE)

# List/table detection helpers
BULLET_LIST_PATTERN = re.compile(r"^\s*[-*+]\s+\S+", re.MULTILINE)
NUMBERED_LIST_PATTERN = re.compile(r"^\s*\d+\.\s+\S+", re.MULTILINE)

CALC_INDEX_TABLE_HEADERS = [
    "ID",
    "Problem / Decision",
    "Result",
    "Impact",
]
CALC_SUBSECTION_HEADING_PATTERN = re.compile(
    r"^\s*###\s*(CALC-\d{3})\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
CALC_ANY_HEADING_PATTERN = re.compile(r"^\s*###\s*CALC-", re.IGNORECASE)
CALC_REQUIRED_SUBHEADINGS = [
    "#### Problem Statement",
    "#### Assumptions",
    "#### Derivation",
    "#### Worst-Case Check",
    "#### Result",
    "#### Design Impact",
    "#### Cross-References",
]
CALC_REQUIRED_SUBHEADINGS_SET = {
    heading.lower() for heading in CALC_REQUIRED_SUBHEADINGS
}


def _extract_sections(
    content: str,
    *,
    required_sections: list[str],
    section_patterns: list[str],
) -> dict[str, list[str]]:
    """Return a map of section title to body lines (excluding the heading)."""
    lines = content.splitlines()
    heading_matches: list[tuple[int, str]] = []

    for idx, line in enumerate(lines):
        for section, pattern in zip(required_sections, section_patterns, strict=True):
            if re.match(pattern, line, re.IGNORECASE):
                heading_matches.append((idx, section))
                break

    if not heading_matches:
        return {}

    heading_matches.sort(key=lambda x: x[0])
    sections: dict[str, list[str]] = {}
    for i, (start_idx, section) in enumerate(heading_matches):
        end_idx = (
            heading_matches[i + 1][0] if i + 1 < len(heading_matches) else len(lines)
        )
        body_lines = lines[start_idx + 1 : end_idx]
        sections[section] = body_lines
    return sections


def _plan_spec(plan_type: str) -> tuple[list[str], list[str]]:
    if plan_type == "engineering":
        return ENGINEERING_PLAN_REQUIRED_SECTIONS, ENGINEERING_PLAN_SECTION_PATTERNS
    if plan_type == "benchmark":
        raise ValueError("Benchmark plan validation uses schema variants")
    raise ValueError(f"Unsupported plan_type '{plan_type}'")


def _validate_plan_md_with_spec(
    content: str,
    *,
    required_sections: list[str],
    section_patterns: list[str],
    plan_type: str,
) -> ValidationResult:
    violations: list[str] = []

    for section, pattern in zip(required_sections, section_patterns, strict=True):
        if not re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            violations.append(f"Missing required section: {section}")

    sections = _extract_sections(
        content,
        required_sections=required_sections,
        section_patterns=section_patterns,
    )

    if plan_type == "engineering":
        parts_lines = sections.get("## 2. Parts List", [])
        if "## 2. Parts List" in sections and not (
            _has_table(parts_lines)
            or BULLET_LIST_PATTERN.search("\n".join(parts_lines))
        ):
            violations.append(
                "Parts List must contain a bullet list or table of parts."
            )

        assembly_lines = sections.get("## 3. Assembly Strategy", [])
        if "## 3. Assembly Strategy" in sections and not NUMBERED_LIST_PATTERN.search(
            "\n".join(assembly_lines)
        ):
            violations.append(
                "Assembly Strategy must contain a numbered list of steps."
            )

        assumption_lines = sections.get("## 4. Assumption Register", [])
        if "## 4. Assumption Register" in sections and not (
            _has_table(assumption_lines)
            or BULLET_LIST_PATTERN.search("\n".join(assumption_lines))
        ):
            violations.append(
                "Assumption Register must contain a bullet list or table of source-backed inputs."
            )

        calculation_lines = sections.get("## 5. Detailed Calculations", [])
        if "## 5. Detailed Calculations" in sections:
            calc_table = _find_calc_index_table(calculation_lines)
            if calc_table is None:
                violations.append(
                    "Detailed Calculations must use the exact summary table with columns `ID`, `Problem / Decision`, `Result`, and `Impact`."
                )
            else:
                _, _, calc_rows = calc_table
                if not calc_rows:
                    violations.append(
                        "Detailed Calculations summary table must include at least one `CALC-*` row."
                    )

                table_ids: list[str] = []
                for row_idx, cells in calc_rows:
                    row_id = cells[0].strip().upper()
                    if not re.fullmatch(r"CALC-\d{3}", row_id):
                        violations.append(
                            f"Detailed Calculations row {row_idx + 1} must use a `CALC-###` identifier in the first column."
                        )
                        continue
                    if not all(cell.strip() for cell in cells[1:]):
                        violations.append(
                            f"Detailed Calculations row {row_idx + 1} must populate the `Problem / Decision`, `Result`, and `Impact` columns."
                        )
                    table_ids.append(row_id)

                calc_heading_entries: list[tuple[int, str]] = []
                for line_idx, line in enumerate(calculation_lines):
                    heading_match = CALC_SUBSECTION_HEADING_PATTERN.match(line)
                    if heading_match:
                        calc_heading_entries.append(
                            (line_idx, heading_match.group(1).upper())
                        )
                        continue
                    if CALC_ANY_HEADING_PATTERN.match(line):
                        violations.append(
                            "Detailed Calculations subsection headings must use the exact `### CALC-001: <short title>` form."
                        )

                heading_ids = [entry[1] for entry in calc_heading_entries]
                if not calc_heading_entries:
                    violations.append(
                        "Detailed Calculations must include matching `### CALC-001: <short title>` subsections for every summary-table row."
                    )
                elif table_ids and heading_ids != table_ids:
                    violations.append(
                        "Detailed Calculations summary-table rows and `CALC-*` subsections must match one-to-one in the same order."
                    )

                for idx, (line_idx, calc_id) in enumerate(calc_heading_entries):
                    end_idx = (
                        calc_heading_entries[idx + 1][0]
                        if idx + 1 < len(calc_heading_entries)
                        else len(calculation_lines)
                    )
                    block_lines = calculation_lines[line_idx + 1 : end_idx]
                    violations.extend(_validate_calc_block(block_lines, calc_id))

        envelope_lines = sections.get(
            "## 6. Critical Constraints / Operating Envelope", []
        )
        if "## 6. Critical Constraints / Operating Envelope" in sections and not (
            _has_table(envelope_lines)
            or BULLET_LIST_PATTERN.search("\n".join(envelope_lines))
        ):
            violations.append(
                "Critical Constraints / Operating Envelope must contain a bullet list or table of derived limits."
            )

        budget_lines = sections.get("## 7. Cost & Weight Budget", [])
        if "## 7. Cost & Weight Budget" in sections and not (
            _has_table(budget_lines)
            or BULLET_LIST_PATTERN.search("\n".join(budget_lines))
        ):
            violations.append(
                "Cost & Weight Budget must contain a bullet list or table of items."
            )

        risk_lines = sections.get("## 8. Risk Assessment", [])
        if "## 8. Risk Assessment" in sections and not (
            _has_table(risk_lines) or BULLET_LIST_PATTERN.search("\n".join(risk_lines))
        ):
            violations.append(
                "Risk Assessment must contain a bullet list or table of risks."
            )

    if plan_type == "benchmark":
        for section in required_sections[1:]:
            lines = sections.get(section, [])
            if section in sections and not "\n".join(lines).strip():
                violations.append(
                    f"{section.removeprefix('## ').strip()} must contain content."
                )

    return ValidationResult(is_valid=len(violations) == 0, violations=violations)


def _has_table(lines: list[str]) -> bool:
    for i in range(len(lines) - 1):
        if "|" in lines[i] and re.match(r"^\s*\|?[\s:-]+\|?[\s|:-]*$", lines[i + 1]):
            return True
    return False


def _split_table_row(line: str) -> list[str] | None:
    if "|" not in line:
        return None
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_separator_line(line: str) -> bool:
    cells = _split_table_row(line)
    if cells is None or not cells:
        return False
    return all(re.fullmatch(r"[:\-\s]+", cell) is not None for cell in cells)


def _find_calc_index_table(
    lines: list[str],
) -> tuple[int, int, list[tuple[int, list[str]]]] | None:
    """Return the exact calculation table location and rows if present."""
    for idx in range(len(lines) - 1):
        header_cells = _split_table_row(lines[idx])
        if header_cells != CALC_INDEX_TABLE_HEADERS:
            continue
        if not _is_table_separator_line(lines[idx + 1]):
            continue

        rows: list[tuple[int, list[str]]] = []
        row_idx = idx + 2
        while row_idx < len(lines):
            line = lines[row_idx]
            if not line.strip() or "|" not in line:
                break
            row_cells = _split_table_row(line)
            if row_cells is None or len(row_cells) != len(CALC_INDEX_TABLE_HEADERS):
                break
            rows.append((row_idx, row_cells))
            row_idx += 1

        return idx, row_idx, rows

    return None


def _ordered_heading_positions(
    lines: list[str], headings: list[str]
) -> tuple[list[int], list[str]]:
    positions: list[int] = []
    missing: list[str] = []
    cursor = 0

    for heading in headings:
        pattern = re.compile(rf"^\s*{re.escape(heading)}\s*$", re.IGNORECASE)
        found_idx: int | None = None
        for idx in range(cursor, len(lines)):
            if pattern.match(lines[idx]):
                found_idx = idx
                break
        if found_idx is None:
            missing.append(heading)
            continue
        positions.append(found_idx)
        cursor = found_idx + 1

    return positions, missing


def _validate_calc_block(lines: list[str], calc_id: str) -> list[str]:
    violations: list[str] = []

    for line in lines:
        if line.lstrip().startswith("#### "):
            normalized = re.sub(r"\s+", " ", line.strip()).lower()
            if normalized not in CALC_REQUIRED_SUBHEADINGS_SET:
                violations.append(
                    f"{calc_id}: Detailed Calculations subsection contains unsupported heading: {line.strip()}"
                )

    positions, missing = _ordered_heading_positions(lines, CALC_REQUIRED_SUBHEADINGS)
    if missing:
        violations.append(
            f"{calc_id}: Detailed Calculations subsection is missing required headings: {', '.join(missing)}"
        )
    if positions != sorted(positions):
        violations.append(
            f"{calc_id}: Detailed Calculations subsection headings must appear in the required order."
        )

    return violations


def validate_plan_md(content: str, plan_type: str = "engineering") -> ValidationResult:
    """
    Validate plan markdown structure against required sections and
    list/table requirements.

    Args:
        content: The markdown content to validate

    Returns:
        ValidationResult with is_valid flag and list of violations
    """
    if plan_type == "benchmark":
        candidate_results = [
            _validate_plan_md_with_spec(
                content,
                required_sections=variant["required_sections"],
                section_patterns=variant["section_patterns"],
                plan_type=plan_type,
            )
            for variant in BENCHMARK_PLAN_VARIANTS
        ]
        for result in candidate_results:
            if result.is_valid:
                return result
        return min(candidate_results, key=lambda result: len(result.violations))

    required_sections, section_patterns = _plan_spec(plan_type)
    return _validate_plan_md_with_spec(
        content,
        required_sections=required_sections,
        section_patterns=section_patterns,
        plan_type=plan_type,
    )


def validate_todo_md(
    content: str, require_completion: bool = False
) -> ValidationResult:
    """
    Validate todo.md structure for proper checkbox format.

    Valid checkboxes: [ ], [x], [X], [/], [-]
    Invalid: anything else inside brackets

    Args:
        content: The markdown content to validate
        require_completion: If True, no unchecked items are allowed.

    Returns:
        ValidationResult with is_valid flag and list of violations
    """
    violations = []

    # Find all checkbox-like patterns
    all_checkboxes = INVALID_CHECKBOX_PATTERN.findall(content)
    valid_checkboxes = TODO_CHECKBOX_PATTERN.findall(content)

    # Count invalid checkboxes
    invalid_count = len(all_checkboxes) - len(valid_checkboxes)
    if invalid_count > 0:
        violations.append(
            f"Found {invalid_count} invalid checkbox(es). "
            "Valid formats: [ ], [x], [X], [/], [-]"
        )

    # Check that there's at least one checkbox (it's a TODO list)
    if len(all_checkboxes) == 0:
        violations.append("No checkboxes found. TODO list should have checkbox items.")

    if require_completion:
        # Only [x]/[X] (completed) or [-] (skipped) are acceptable at submission
        invalid_states = [s for s in valid_checkboxes if s.lower() not in ("x", "-")]
        if invalid_states:
            violations.append(
                "All TODO items must be completed or skipped before submission "
                "(only [x] or [-] allowed)."
            )

    return ValidationResult(is_valid=len(violations) == 0, violations=violations)


def validate_markdown_file(path: str, content: str) -> ValidationResult:
    """
    Dispatch validation based on filename.

    Args:
        path: File path (used to determine which validator to use)
        content: The markdown content to validate

    Returns:
        ValidationResult
    """
    if path.endswith("benchmark_plan.md"):
        return validate_plan_md(content, plan_type="benchmark")
    if path.endswith("engineering_plan.md"):
        return validate_plan_md(content, plan_type="engineering")
    if path.endswith("plan.md"):
        raise ValueError(
            "plan.md is no longer supported; use benchmark_plan.md or "
            "engineering_plan.md"
        )
    if path.endswith("todo.md"):
        return validate_todo_md(content)
    # No validation for other markdown files
    return ValidationResult(is_valid=True, violations=[])
