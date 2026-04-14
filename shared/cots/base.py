from abc import ABC
from typing import Any

from build123d import Compound

from shared.models.schemas import PartMetadata
from shared.observability.events import emit_event
from shared.observability.schemas import ComponentUsageEvent


class COTSPart(Compound, ABC):
    """
    Abstract base class for all COTS parts.
    Automatically handles observability event emitting on initialization.
    """

    def __init__(
        self,
        category: str,
        part_number: str,
        data: dict[str, Any],
        children=None,
        label: str | None = None,
        **kwargs,
    ):
        """
        Initialize the COTS part.

        Args:
            category: The category of the part (e.g., 'actuator', 'fastener').
            part_number: The specific model or Part ID.
            data: Metadata dictionary containing at least 'price' and 'weight_g'.
            children: build123d geometry children.
            kwargs: extra build123d.Compound arguments.
        """
        super().__init__(children=children or [], **kwargs)

        self.category = category
        self.part_number = part_number

        # Refactor to use PartMetadata instead of dict
        self.metadata = PartMetadata(
            cots_id=part_number,
            material_id=data.get("material_id", "cots-generic"),
        )

        # Ensure label exists for identification.
        if label is not None:
            self.label = label
        elif not hasattr(self, "label") or not self.label:
            self.label = f"{category}_{part_number}"

        # Price and weight are mandatory for observability metrics
        # but we use defaults if missing to avoid crashes.
        self.price = data.get("price", data.get("unit_cost", 0.0))
        self.weight_g = data.get("weight_g", 0.0)

        # Automatic observability event emitting
        emit_event(
            ComponentUsageEvent(
                category=self.category,
                part_number=self.part_number,
                label=self.label,
                price=self.price,
                weight_g=self.weight_g,
            )
        )

    @property
    def info(self):
        """Standard property to access metadata, identical to Indexer expectations."""
        return self.metadata
