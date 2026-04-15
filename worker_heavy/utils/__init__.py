from __future__ import annotations

import importlib
from typing import Any

from shared.workers.workbench_models import ManufacturingConfig, ManufacturingMethod

__all__ = [
    "ManufacturingConfig",
    "ManufacturingMethod",
    "render_cad",
    "renderer_client",
    "simulate",
    "submit_for_review",
    "validate",
    "validate_and_price",
]

_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
    "renderer_client": ("worker_heavy.utils.renderer_client", None),
    "validate_and_price": ("worker_heavy.utils.dfm", "validate_and_price"),
    "submit_for_review": ("worker_heavy.utils.handover", "submit_for_review"),
    "simulate": ("worker_heavy.utils.validation", "simulate"),
    "validate": ("worker_heavy.utils.validation", "validate"),
    "render_cad": ("worker_heavy.utils.render_cad", "render_cad"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_LAZY_ATTRS))
