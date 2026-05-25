"""Shared mapping from Django's ``ValidationError`` to a Ninja ``ErrorResponse`` body.

Lives in ``services`` (not ``apis.py``) because both ``core/apis.py`` and
``teams/apis.py`` need it, and the latter is already imported BY ``core/apis.py``
(``serialize_contact_profile``) — putting this helper in either ``apis.py``
would create a circular import.

Issue #953: handlers that call ``.full_clean()`` (or models whose
``.save()`` calls it) trip ``validate_unique()`` BEFORE the DB ever throws
``IntegrityError``. The ``DUPLICATE_NAME`` branch on the ``IntegrityError``
side is unreachable in that case, so we have to detect the unique-violation
at the ``ValidationError`` layer and surface the dedicated error code there.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError

from sbomify.apps.core.schemas import ErrorCode


def validation_error_response(ve: DjangoValidationError, resource_label: str) -> tuple[int, dict[str, Any]]:
    """Map a ``DjangoValidationError`` to an ``ErrorResponse`` 400 body.

    Surfaces ``DUPLICATE_NAME`` when ``validate_unique()`` flagged the failure
    (``message_dict`` has a ``__all__`` entry containing ``"already exists"``)
    so clients can distinguish a duplicate from a generic validation failure
    without grepping the prose detail string. Other validation errors stay
    on ``INVALID_DATA``.

    ``resource_label`` is interpolated into the friendly detail string for
    duplicate cases ("A {resource_label} with this name already exists in
    this team") so the same helper can serve component / contact-entity /
    any future caller without conflating error vocabulary.

    The ``"already exists"`` substring — not just the ``__all__`` key — is
    the disambiguator: some model-level ``clean()`` rules also bind their
    errors to ``__all__`` (e.g. "Mutually-exclusive fields A and B were
    both set") and must NOT be misclassified as a duplicate.
    """
    msg_dict = ve.message_dict
    unique_hits = msg_dict.get("__all__", [])
    is_unique_violation = any("already exists" in m.lower() for m in unique_hits)
    if is_unique_violation:
        return 400, {
            "detail": f"A {resource_label} with this name already exists in this team",
            "errors": msg_dict,
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    return 400, {
        "detail": "Validation error",
        "errors": msg_dict,
        "error_code": ErrorCode.INVALID_DATA,
    }
