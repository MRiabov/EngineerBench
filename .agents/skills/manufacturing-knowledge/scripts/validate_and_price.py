#!/usr/bin/env python3
"""
Populate and validate the workspace assembly-definition YAML.
Calculates stock volumes and removed volumes based on planner-provided dimensions.
"""

import sys
from pathlib import Path

import structlog
import yaml
from pydantic import ValidationError

# Add project root to path to import shared models
sys.path.append(str(Path(__file__).parents[3]))
from shared.enums import ManufacturingMethod
from shared.models.schemas import AssemblyDefinition
from worker_heavy.utils.dfm import (
    calculate_declared_assembly_cost,
    calculate_declared_assembly_weight,
    load_planner_manufacturing_config,
)

logger = structlog.get_logger(__name__)


def main():
    file_path = Path("assembly_definition.yaml")
    if not file_path.exists():
        benchmark_path = Path("benchmark_assembly_definition.yaml")
        file_path = benchmark_path if benchmark_path.exists() else file_path
    if not file_path.exists():
        print(
            "Error: assembly_definition.yaml or benchmark_assembly_definition.yaml not found."
        )
        sys.exit(1)

    try:
        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data:
            print("Error: Empty YAML file.")
            sys.exit(1)

        # 1. Geometry Calculations
        for part in data.get("manufactured_parts", []):
            bbox = part.get("stock_bbox_mm")
            if bbox and isinstance(bbox, dict):
                x = float(bbox.get("x", 0))
                y = float(bbox.get("y", 0))
                z = float(bbox.get("z", 0))

                # Calculate stock volume
                stock_vol = x * y * z
                part["stock_volume_mm3"] = round(stock_vol, 2)

                # Calculate removed volume for CNC
                m_method = part.get("manufacturing_method")
                if m_method == ManufacturingMethod.CNC or m_method == "CNC":
                    part_vol = float(part.get("part_volume_mm3", 0))
                    part["removed_volume_mm3"] = round(
                        max(0.0, stock_vol - part_vol), 2
                    )
                else:
                    part["removed_volume_mm3"] = 0.0

        # 2. Pydantic Validation
        estimation = AssemblyDefinition(**data)

        config_path = Path("manufacturing_config.yaml")
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        config = load_planner_manufacturing_config(config_path=config_path)
        data["totals"]["estimated_unit_cost_usd"] = calculate_declared_assembly_cost(
            estimation, config
        )
        data["totals"]["estimated_weight_g"] = calculate_declared_assembly_weight(
            estimation, config
        )
        estimation = AssemblyDefinition(**data)

        # 3. Write back normalized YAML
        updated_content = yaml.dump(data, sort_keys=False, default_flow_style=False)
        file_path.write_text(updated_content, encoding="utf-8")

        # 4. Success Output
        print(f"Success: {file_path.name} validated and updated.")
        print(f"Total Estimated Cost: ${estimation.totals.estimated_unit_cost_usd:.2f}")
        print(f"Total Estimated Weight: {estimation.totals.estimated_weight_g:.2f}g")

    except ValidationError as e:
        print(f"Validation Error: {e}")
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: manufacturing_config.yaml invalid: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
