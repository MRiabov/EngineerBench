#!/usr/bin/env python3
"""Normalize derived fields in integration mock-response compatibility fixtures.

This utility is meant for `tests/integration/mock_responses/` compatibility
snapshots. It rewrites deterministic assembly totals/geometry fields and
validates the benchmark-definition schema without touching scenario-specific
narrative or planner intent text.

Use `--fix` to write normalized files back to disk. Without `--fix`, the script
only reports drift.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.models.schemas import AssemblyDefinition, BenchmarkDefinition

yaml_rt = YAML(typ="rt")
yaml_rt.preserve_quotes = True
yaml_rt.width = 120
yaml_rt.indent(mapping=2, sequence=4, offset=2)


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml_rt.load(handle)


def _dump_yaml(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml_rt.dump(data, handle)


def _parse_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _benchmark_caps_from_sibling_definition(path: Path) -> tuple[float, float] | None:
    benchmark_definition_path = next(
        (
            candidate
            for candidate in sorted(path.parent.glob("*benchmark_definition.yaml"))
        ),
        None,
    )
    if benchmark_definition_path is None:
        return None

    data = _load_yaml(benchmark_definition_path)
    if not isinstance(data, dict):
        return None

    constraints = data.get("constraints")
    if not isinstance(constraints, dict):
        return None

    max_unit_cost = constraints.get("max_unit_cost")
    max_weight_g = constraints.get("max_weight_g")
    if max_unit_cost is None or max_weight_g is None:
        return None

    return _parse_float(max_unit_cost), _parse_float(max_weight_g)


def _declared_assembly_cost(data: dict[str, Any]) -> float:
    manufactured_cost = 0.0
    for part in data.get("manufactured_parts") or []:
        manufactured_cost += _parse_float(
            part.get("estimated_unit_cost_usd")
        ) * _parse_float(part.get("quantity"), 1.0)
    return round(manufactured_cost, 2)


def _normalize_manufactured_parts(data: dict[str, Any]) -> bool:
    changed = False
    for part in data.get("manufactured_parts") or []:
        bbox = part.get("stock_bbox_mm")
        if not isinstance(bbox, dict):
            continue

        x = _parse_float(bbox.get("x"))
        y = _parse_float(bbox.get("y"))
        z = _parse_float(bbox.get("z"))
        stock_volume = round(x * y * z, 2)
        if part.get("stock_volume_mm3") != stock_volume:
            part["stock_volume_mm3"] = stock_volume
            changed = True

        method = str(part.get("manufacturing_method", "")).strip().upper()
        if method == "CNC":
            removed_volume = round(
                max(0.0, stock_volume - _parse_float(part.get("part_volume_mm3"))), 2
            )
        else:
            removed_volume = 0.0

        if part.get("removed_volume_mm3") != removed_volume:
            part["removed_volume_mm3"] = removed_volume
            changed = True

    return changed


def _normalize_assembly_file(path: Path, *, fix: bool) -> tuple[bool, list[str]]:
    errors: list[str] = []
    data = _load_yaml(path)
    if not isinstance(data, dict):
        return False, [f"{path}: YAML root must be a mapping"]

    changed = _normalize_manufactured_parts(data)
    benchmark_caps = _benchmark_caps_from_sibling_definition(path)
    totals = data.get("totals")
    if not isinstance(totals, dict):
        return False, [f"{path}: totals must be a mapping"]

    constraints = data.get("constraints")
    if not isinstance(constraints, dict):
        return False, [f"{path}: constraints must be a mapping"]

    if benchmark_caps is not None:
        benchmark_max_unit_cost, benchmark_max_weight_g = benchmark_caps
        if constraints.get("benchmark_max_unit_cost_usd") != benchmark_max_unit_cost:
            constraints["benchmark_max_unit_cost_usd"] = benchmark_max_unit_cost
            changed = True
        if constraints.get("benchmark_max_weight_g") != benchmark_max_weight_g:
            constraints["benchmark_max_weight_g"] = benchmark_max_weight_g
            changed = True
        if (
            _parse_float(constraints.get("planner_target_max_unit_cost_usd"))
            > benchmark_max_unit_cost
        ):
            constraints["planner_target_max_unit_cost_usd"] = benchmark_max_unit_cost
            changed = True
        if (
            _parse_float(constraints.get("planner_target_max_weight_g"))
            > benchmark_max_weight_g
        ):
            constraints["planner_target_max_weight_g"] = benchmark_max_weight_g
            changed = True

    expected_cost = _declared_assembly_cost(data)
    if totals.get("estimated_unit_cost_usd") != expected_cost:
        totals["estimated_unit_cost_usd"] = expected_cost
        changed = True

    empty_assembly = not (data.get("manufactured_parts") or data.get("final_assembly"))
    if empty_assembly:
        if totals.get("estimated_weight_g") != 0:
            totals["estimated_weight_g"] = 0
            changed = True
    else:
        if _parse_float(totals.get("estimated_weight_g")) <= 0:
            errors.append(
                f"{path}: estimated_weight_g is non-positive for a non-empty assembly; this fixture cannot be auto-populated"
            )

    try:
        AssemblyDefinition.model_validate(data)
    except ValidationError as exc:
        errors.append(f"{path}: {exc}")

    if errors:
        return changed, errors

    if fix and changed:
        _dump_yaml(path, data)

    return changed, []


def _validate_benchmark_definition_file(path: Path) -> list[str]:
    data = _load_yaml(path)
    if not isinstance(data, dict):
        return [f"{path}: YAML root must be a mapping"]

    errors: list[str] = []
    try:
        BenchmarkDefinition.model_validate(data)
    except ValidationError as exc:
        errors.append(f"{path}: {exc}")
        return errors

    constraints = data.get("constraints")
    if not isinstance(constraints, dict):
        return [f"{path}: constraints must be a mapping"]

    est_cost = constraints.get("estimated_solution_cost_usd")
    est_weight = constraints.get("estimated_solution_weight_g")
    max_cost = constraints.get("max_unit_cost")
    max_weight = constraints.get("max_weight_g")

    if isinstance(est_cost, (int, float)) and isinstance(est_weight, (int, float)):
        expected_max_cost = round(float(est_cost) * 1.5, 10)
        expected_max_weight = round(float(est_weight) * 1.5, 10)

        if (
            max_cost is not None
            and abs(_parse_float(max_cost) - expected_max_cost) > 1e-6
        ):
            errors.append(
                f"{path}: max_unit_cost {max_cost!r} does not match 1.5x estimated_solution_cost_usd ({expected_max_cost})"
            )
        if (
            max_weight is not None
            and abs(_parse_float(max_weight) - expected_max_weight) > 1e-6
        ):
            errors.append(
                f"{path}: max_weight_g {max_weight!r} does not match 1.5x estimated_solution_weight_g ({expected_max_weight})"
            )

    return errors


def _iter_target_files(targets: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for target in targets:
        if target.is_file():
            if target.name.endswith(
                ("assembly_definition.yaml", "benchmark_definition.yaml")
            ):
                files.add(target)
            continue

        if not target.exists():
            raise FileNotFoundError(f"Target does not exist: {target}")

        for pattern in ("*assembly_definition.yaml", "*benchmark_definition.yaml"):
            files.update(path for path in target.rglob(pattern) if path.is_file())

    return sorted(files)


def _resolve_targets(args: argparse.Namespace) -> list[Path]:
    mock_root = ROOT / "tests" / "integration" / "mock_responses"

    targets: list[Path] = []
    for scenario in args.scenario:
        scenario_path = mock_root / scenario
        if not scenario_path.exists():
            raise FileNotFoundError(f"Unknown integration scenario: {scenario}")
        targets.append(scenario_path)

    for raw_path in args.path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        targets.append(path)

    if args.all:
        targets.append(mock_root)

    if not targets:
        raise SystemExit("Provide at least one --scenario, --path, or --all target.")

    return targets


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize deterministic fixture fields in tests/integration/mock_responses."
        )
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Normalize one INT-### scenario directory (repeatable).",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Normalize a specific file or directory (repeatable).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Normalize every content file under tests/integration/mock_responses.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Write normalized YAML back to disk.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        targets = _resolve_targets(args)
        files = _iter_target_files(targets)
    except Exception as exc:
        print(f"error: {exc}")
        return 2

    changed_files: list[Path] = []
    validation_errors: list[str] = []
    validated = 0

    for path in files:
        validated += 1
        if path.name.endswith(
            ("assembly_definition.yaml", "benchmark_assembly_definition.yaml")
        ):
            changed, errors = _normalize_assembly_file(path, fix=args.fix)
            if changed:
                changed_files.append(path)
            validation_errors.extend(errors)
            continue

        if path.name.endswith("benchmark_definition.yaml"):
            validation_errors.extend(_validate_benchmark_definition_file(path))

    if changed_files and args.fix:
        print(f"normalized {len(changed_files)} file(s):")
        for path in changed_files:
            print(f"- {path.relative_to(ROOT)}")

    if changed_files and not args.fix:
        print("drift detected:")
        for path in changed_files:
            print(f"- {path.relative_to(ROOT)}")
        return 1

    if validation_errors:
        print("validation errors:")
        for error in validation_errors:
            print(f"- {error}")
        return 1

    print(f"validated {validated} file(s).")
    if not changed_files or not args.fix:
        print("no files rewritten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
