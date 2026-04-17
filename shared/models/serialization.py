from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml
from pydantic import BaseModel


def dump_yaml_model(model: BaseModel) -> str:
    """Serialize a typed schema model to YAML at the edge."""
    return yaml.safe_dump(
        model.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=False,
    )


def dump_yaml_content(content: BaseModel | Mapping[str, Any] | str) -> str:
    """Serialize integration fixture content with typed-model precedence."""
    if isinstance(content, BaseModel):
        return dump_yaml_model(content)
    if isinstance(content, str):
        return content
    return yaml.safe_dump(content, sort_keys=False)
