from __future__ import annotations

import importlib
from typing import Any

from shared.workers.workbench_models import ManufacturingConfig, ManufacturingMethod

__all__ = [
    "HoleType",
    "ManufacturingConfig",
    "ManufacturingMethod",
    "cad",
    "calculate_power_budget",
    "controllers",
    "create_circuit",
    "define_fluid",
    "electronics",
    "fastener_hole",
    "get_stress_report",
    "preview",
    "preview_stress",
    "render_cad",
    "renderer_client",
    "route_wire",
    "set_soft_mesh",
    "simulate",
    "simulate_circuit_transient",
    "submit_for_review",
    "validate",
    "validate_and_price",
    "validate_circuit",
]

_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
    "cad": ("worker_heavy.utils.cad", None),
    "controllers": ("worker_heavy.utils.controllers", None),
    "electronics": ("worker_heavy.utils.electronics", None),
    "renderer_client": ("worker_heavy.utils.renderer_client", None),
    "validate_and_price": ("worker_heavy.utils.dfm", "validate_and_price"),
    "submit_for_review": ("worker_heavy.utils.handover", "submit_for_review"),
    "HoleType": ("worker_heavy.utils.cad", "HoleType"),
    "fastener_hole": ("worker_heavy.utils.cad", "fastener_hole"),
    "calculate_power_budget": (
        "worker_heavy.utils.electronics",
        "calculate_power_budget",
    ),
    "create_circuit": ("worker_heavy.utils.electronics", "create_circuit"),
    "route_wire": ("worker_heavy.utils.electronics", "route_wire"),
    "simulate_circuit_transient": (
        "worker_heavy.utils.electronics",
        "simulate_circuit_transient",
    ),
    "validate_circuit": ("worker_heavy.utils.electronics", "validate_circuit"),
    "define_fluid": ("worker_heavy.utils.validation", "define_fluid"),
    "get_stress_report": ("worker_heavy.utils.validation", "get_stress_report"),
    "preview_stress": ("worker_heavy.utils.validation", "preview_stress"),
    "set_soft_mesh": ("worker_heavy.utils.validation", "set_soft_mesh"),
    "simulate": ("worker_heavy.utils.validation", "simulate"),
    "validate": ("worker_heavy.utils.validation", "validate"),
    "render_cad": ("worker_heavy.utils.preview", "render_cad"),
    "preview": ("worker_heavy.utils.preview", "preview"),
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
