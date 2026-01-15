from __future__ import annotations

from typing import Any, Tuple

from sbomify.apps.core.domain.exceptions import DomainError


def api_error_response(error: DomainError) -> Tuple[int, dict[str, Any]]:
    return error.status_code, error.to_dict()
