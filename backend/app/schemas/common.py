"""Shared Pydantic schemas and UTC normalization helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, BeforeValidator, Field

T = TypeVar("T")


def _ensure_utc(value: object) -> object:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


UTCDateTime = Annotated[datetime, BeforeValidator(_ensure_utc)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict = Field(default_factory=dict)
    correlation_id: str | None = None


class QuantityOut(BaseModel):
    value: float
    unit: str
    uncertainty: float | None = None
    confidence: float | None = None
    method: str | None = None
    source: str | None = None


class LineageOut(BaseModel):
    code_version: str | None = None
    algorithm: str | None = None
    algorithm_version: str | None = None
    model: str | None = None
    model_version: str | None = None
    run_timestamp: datetime | None = None
    provenance: dict = Field(default_factory=dict)
