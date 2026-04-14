from __future__ import annotations

from shared.cots.models import COTSCategory


def supported_cots_geometry_hints() -> list[str]:
    """Return COTS template hint lines.

    The template renderer only needs a stable list of comment lines to splice
    into starter scripts. Keep this dependency-free so importing agent template
    helpers does not require catalog access.
    """

    return [
        "# COTS parts are catalog-backed and should be referenced by exact part_id.",
        f"# Supported COTS categories: {', '.join(category.value for category in COTSCategory)}.",
    ]
