from enum import StrEnum
from typing import Any

from pydantic import BaseModel, StrictFloat, StrictInt, StrictStr, field_validator


class COTSCategory(StrEnum):
    FASTENER = "fastener"
    GEAR = "gear"
    BEARING = "bearing"


class COTSItem(BaseModel):
    part_id: StrictStr
    name: StrictStr
    category: COTSCategory
    unit_cost: StrictFloat
    weight_g: StrictFloat
    import_recipe: StrictStr  # build123d code snippet
    metadata: dict[StrictStr, Any]

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class SearchConstraints(BaseModel):
    max_weight_g: float | None = None
    max_cost: float | None = None
    category: str | None = None
    min_size: float | None = None

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value


class SearchQuery(BaseModel):
    query: StrictStr
    constraints: SearchConstraints | None = None
    limit: StrictInt = 5
