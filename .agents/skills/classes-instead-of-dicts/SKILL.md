---
name: classes-instead-of-dicts
description: Enforce typed schema contracts by preferring classes (especially `pydantic.BaseModel`) over freeform dicts. Use this whenever adding or modifying classes, and whenever planning or implementing storage logic or API communication (function interfaces and HTTP endpoints).
---

# Classes Instead Of Dicts

Use this skill any time structured data is exchanged across boundaries.
This skill is self-contained: apply only the rules in this file for this policy.

## Activation scope

Apply this skill whenever work includes any of the following:

1. Adding a new class.
2. Modifying an existing class.
3. Planning or coding storage logic.
4. Planning or coding API communication logic, including function interfaces and HTTP endpoints.

## Core rules

1. For structured payloads, prefer explicit typed classes over freeform `dict`.
2. Use `pydantic.BaseModel` for API/function/event contracts and data exchange.
3. Use SQLAlchemy models and migrations for persistent database schema.
4. When touching legacy dict-based contracts, refactor toward typed models.
5. Parse JSON/YAML/XML into typed models before business logic or test assertions.

## Typing guardrails

1. Prefer `Enum` values over ad-hoc strings.
2. Prefer `pathlib.Path` over raw path strings.
3. Prefer typed strategies/classes over substring matching.
4. Keep function signatures and return types explicit; avoid dict-shaped contracts unless data is truly dynamic.
5. If a field's dimension or unit is only implied by context, encode it in the field name so the contract is explicit.

## Planning checklist for storage and API work

1. Define request/response and internal transfer models before implementing logic.
2. Keep persistence models (SQLAlchemy) separate from transfer models (Pydantic).
3. Validate and normalize at boundaries, then pass typed objects internally.

## Narrow exception

Use `dict[str, Any]` only for genuinely open-ended metadata where keys cannot be modeled. Convert to typed structures as soon as shape becomes stable.
