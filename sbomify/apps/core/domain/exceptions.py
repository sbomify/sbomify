from __future__ import annotations

from typing import Any, Dict, Optional


class DomainError(Exception):
    status_code = 400
    error_code = "error"

    def __init__(self, detail: str | None = None, *, error_code: str | None = None) -> None:
        self.detail = detail or "An error occurred."
        if error_code:
            self.error_code = error_code
        super().__init__(self.detail)

    def to_dict(self) -> Dict[str, Any]:
        return {"detail": self.detail, "error_code": self.error_code}


class ValidationError(DomainError):
    status_code = 400
    error_code = "validation_error"


class PermissionDeniedError(DomainError):
    status_code = 403
    error_code = "permission_denied"


class NotFoundError(DomainError):
    status_code = 404
    error_code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    error_code = "conflict"


class ExternalServiceError(DomainError):
    status_code = 502
    error_code = "external_service_error"

    def __init__(self, detail: str | None = None, *, service: Optional[str] = None) -> None:
        super().__init__(detail or "External service error.")
        self.service = service

    def to_dict(self) -> Dict[str, Any]:
        payload = super().to_dict()
        if self.service:
            payload["service"] = self.service
        return payload
