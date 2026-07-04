"""Shared response models: the consistent error envelope and pagination wrapper."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str = Field(..., description="Machine-readable error code, e.g. 'not_found'.")
    message: str = Field(..., description="Human-readable explanation.")
    request_id: str | None = Field(None, description="Correlates with the X-Request-ID header.")
    details: dict[str, Any] | None = Field(None, description="Optional structured context.")


class ErrorResponse(BaseModel):
    """Every non-2xx response uses this envelope."""

    error: ErrorBody


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int

    @property
    def pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size if self.page_size else 0


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]
    details: dict[str, Any] = {}
