from .models import SearchConstraints, SearchQuery
from .runtime import DEFAULT_DB_PATH, search_parts


def search_cots_catalog(
    query: str,
    max_weight_g: float | None = None,
    max_cost: float | None = None,
    category: str | None = None,
    limit: int = 5,
) -> str:
    """
    Search for off-the-shelf mechanical components (fasteners, bearings, etc.).
    Returns a list of parts with their IDs, costs, weights, and Python import recipes.

    Args:
        query: Text description of the part (e.g. 'M6 hex nut').
        max_weight_g: Maximum allowed weight in grams.
        max_cost: Maximum allowed unit cost.
        category: Filter by category ('fastener', 'gear', 'bearing').
        limit: Max number of results.
    """
    constraints = SearchConstraints(
        max_weight_g=max_weight_g,
        max_cost=max_cost,
        category=category,
    )

    sq = SearchQuery(query=query, constraints=constraints, limit=limit)
    parts, meta = search_parts(sq, DEFAULT_DB_PATH)

    if not parts:
        return "No parts found matching the criteria."

    output = []
    for p in parts:
        item_str = (
            f"- {p.name} (ID: {p.part_id})\n"
            f"  Category: {p.category}, Weight: {p.weight_g:.2f}g, Cost: ${p.unit_cost}\n"
            f"  Recipe: {p.import_recipe}\n"
            f"  Reproducibility Metadata: {meta}"
        )
        output.append(item_str)

    return "\n\n".join(output)
