from __future__ import annotations

from typing import Any, Tuple

from sbomify.apps.core.domain.exceptions import DomainError


def api_error_response(error: DomainError) -> Tuple[int, dict[str, Any]]:
    return error.status_code, error.to_dict()


#: openapi_extra for endpoints whose 200 is a CSV HttpResponse passed through
#: unvalidated. ninja deep-merges this into the operation, so the declared
#: error responses survive and the docs stop describing the download as an
#: empty body.
CSV_RESPONSE_DOCS: dict[str, Any] = {
    "responses": {
        200: {
            "description": "The CSV file",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    }
}
