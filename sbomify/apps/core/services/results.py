from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import ValidationError as PydanticValidationError

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceResult(Generic[T]):
    """Lightweight service-layer result wrapper.

    Keeps services free of HTTP concerns while preserving error messages.
    """

    value: T | None = None
    error: str | None = None
    status_code: int | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, value: T | None = None) -> "ServiceResult[T]":
        return cls(value=value, error=None, status_code=None)

    @classmethod
    def failure(cls, error: str, status_code: int | None = None) -> "ServiceResult[T]":
        return cls(value=None, error=error, status_code=status_code)


def extract_pydantic_error_message(e: PydanticValidationError) -> str:
    """Extract a user-friendly message from a Pydantic ValidationError."""
    if not e.errors():
        return "Invalid input"
    raw_msg = e.errors()[0].get("msg", "Invalid input")
    # Strip Pydantic's "Value error, " prefix for cleaner user-facing messages
    if raw_msg.startswith("Value error, "):
        return raw_msg[len("Value error, ") :]
    return raw_msg
