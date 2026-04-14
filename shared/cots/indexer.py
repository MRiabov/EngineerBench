from pathlib import Path
from typing import Any

import structlog
from bd_warehouse.bearing import SingleRowDeepGrooveBallBearing
from bd_warehouse.fastener import HexNut, PlainWasher, SocketHeadCapScrew
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.models.schemas import BoundingBox, COTSMetadata
from shared.type_checking import type_check

from .database.init import init_db
from .database.models import CatalogMetadataORM, COTSItemORM

logger = structlog.get_logger(__name__)

# Density for steel in g/mm^3 (approx 7.85 g/cm^3)
STEEL_DENSITY_G_MM3 = 0.00785

# Default costs for MVP
DEFAULT_COSTS = {
    "HexNut": 0.05,
    "SocketHeadCapScrew": 0.15,
    "PlainWasher": 0.02,
    "SingleRowDeepGrooveBallBearing": 2.50,
}


# ... (rest of imports)


@type_check
class Indexer:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.engine = create_engine(f"sqlite:///{self.db_path}")

    def get_part_classes(self) -> list[type]:
        """MVP: Hardcoded list of useful classes to index."""
        return [
            HexNut,
            SocketHeadCapScrew,
            PlainWasher,
            SingleRowDeepGrooveBallBearing,
        ]

    def extract_metadata(self, part_class: type, size: str) -> COTSMetadata | None:
        """Instantiate part and extract metadata."""
        try:
            # Class-specific instantiation arguments
            kwargs = {"size": size}
            class_name = part_class.__name__

            if class_name == "SocketHeadCapScrew":
                kwargs["length"] = 20  # Default length for indexing
            elif class_name == "PlainWasher":
                kwargs["fastener_type"] = "iso7089"  # Default type for indexing

            part = part_class(**kwargs)

            bb = part.bounding_box()
            volume = part.volume

            weight = volume * STEEL_DENSITY_G_MM3
            unit_cost = DEFAULT_COSTS.get(class_name, 0.10)

            # Category mapping
            category = "fastener"
            if "Bearing" in class_name:
                category = "bearing"
            elif "Gear" in class_name:
                category = "gear"

            # part_id should include extra parameters if they exist
            param_suffix = ""
            if "length" in kwargs:
                param_suffix += f"_{kwargs['length']}mm"
            if "fastener_type" in kwargs:
                param_suffix += f"_{kwargs['fastener_type']}"

            return COTSMetadata(
                part_id=f"{class_name}_{size}{param_suffix}",
                name=f"{class_name} {size}{param_suffix.replace('_', ' ')}",
                category=category,
                unit_cost=unit_cost,
                weight_g=weight,
                bbox=BoundingBox(
                    min=(bb.min.X, bb.min.Y, bb.min.Z),
                    max=(bb.max.X, bb.max.Y, bb.max.Z),
                ),
                volume=volume,
                params=kwargs,
            )
        except Exception as e:
            logger.error(
                "failed_to_extract_metadata",
                class_name=part_class.__name__,
                size=size,
                error=str(e),
                session_id="system",
            )
            return None

    def generate_recipe(self, part_class: type, params: dict[str, Any]) -> str:
        """Generate Python code to recreate the part."""
        module = part_class.__module__
        class_name = part_class.__name__
        args_str = ", ".join(
            [
                f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}"
                for k, v in params.items()
            ]
        )
        return f"from {module} import {class_name}\npart = {class_name}({args_str})"

    def index_all(self, limit_per_class: int = 20):
        """Main loop to populate the database."""
        init_db(self.db_path)

        with Session(self.engine) as session:
            for part_class in self.get_part_classes():
                class_name = part_class.__name__
                logger.info(f"Indexing {class_name}...")

                # Get available sizes from fastener_data or bearing_data
                if hasattr(part_class, "fastener_data"):
                    sizes = list(part_class.fastener_data.keys())
                elif hasattr(part_class, "bearing_data"):
                    sizes = list(part_class.bearing_data.keys())
                else:
                    logger.warning(f"No size data found for {class_name}, skipping.")
                    continue

                count = 0
                for size in sizes:
                    if count >= limit_per_class:
                        break

                    metadata = self.extract_metadata(part_class, size)
                    if not metadata:
                        continue

                    recipe = self.generate_recipe(part_class, metadata.params)

                    item = COTSItemORM(
                        part_id=metadata.part_id,
                        name=metadata.name,
                        category=metadata.category,
                        unit_cost=metadata.unit_cost,
                        weight_g=metadata.weight_g,
                        import_recipe=recipe,
                        metadata_dict=metadata.model_dump(),
                    )

                    session.merge(item)
                    count += 1

                session.commit()
                logger.info(f"Indexed {count} items for {class_name}")

            # Add catalog metadata for reproducibility
            import uuid

            metadata_record = CatalogMetadataORM(
                catalog_version="1.0.0",
                bd_warehouse_commit="a048a73",  # Placeholder from current repo
                catalog_snapshot_id=uuid.uuid4().hex,
            )
            session.merge(metadata_record)
            session.commit()
            logger.info("Catalog metadata stored.")


if __name__ == "__main__":
    indexer = Indexer("parts.db")
    indexer.index_all(limit_per_class=5)
