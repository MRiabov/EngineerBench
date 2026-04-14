"""Typed integration-test contracts for HTTP payload assertions."""

from pydantic import BaseModel, field_validator

from shared.enums import ResponseStatus


class HealthResponse(BaseModel):
    """Health payload returned by controller/worker `/health` endpoints."""

    status: ResponseStatus

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value
