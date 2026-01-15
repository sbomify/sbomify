from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

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
