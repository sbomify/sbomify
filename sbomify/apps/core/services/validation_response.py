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

_UNIQUE_ERROR_CODES = frozenset({"unique", "unique_together"})


def _is_unique_violation(ve: DjangoValidationError) -> bool:
    """Detect a uniqueness-constraint failure on a ``DjangoValidationError``.

    Prefers the structured ``ValidationError.error_dict`` path so we read the
    ``code`` attribute Django sets on errors raised by ``validate_unique()``
    (``"unique"`` for single-field, ``"unique_together"`` for multi-field).
    This is robust against:

    - **i18n**: if ``USE_I18N=True`` is ever flipped on, Django translates
      the default unique message and a substring match for ``"already
      exists"`` would silently stop matching.
    - **False positives**: custom ``clean()`` rules that happen to use the
      phrase "already exists" (e.g. ``ContactProfileContact.clean()`` raises
      ``"A security contact already exists in this profile..."`` — that's a
      role-exclusivity rule, NOT a name uniqueness violation, and surfacing
      it as ``DUPLICATE_NAME`` would tell the API client "rename and retry"
      when the actual fix is "demote the other security contact").

    Fallback: if ``error_dict`` isn't available (a caller built the
    ``ValidationError`` from a plain string with no code), drop down to the
    legacy substring grep so behaviour doesn't regress for those paths.

    See ``teams/views/contact_profiles.py::_format_formset_errors`` for the
    matching error-code pattern on the HTML form side.
    """
    error_dict = getattr(ve, "error_dict", None)
    if error_dict:
        for errors in error_dict.values():
            for err in errors:
                if getattr(err, "code", None) in _UNIQUE_ERROR_CODES:
                    return True
        # error_dict was present but no unique code — definitively NOT a
        # unique violation (custom clean() raised it; substring grep would
        # be a false positive here).
        return False
    # Plain ``ValidationError("...")`` / ``ValidationError([...])`` —
    # accessing ``message_dict`` here would raise ``AttributeError``, so
    # use ``messages`` which is always available. Substring check is the
    # least-bad option for unstructured input (no ``code`` to read).
    return any("already exists" in m.lower() for m in ve.messages)


def validation_error_response(
    ve: DjangoValidationError,
    resource_label: str,
    scope_label: str = "team",
) -> tuple[int, dict[str, Any]]:
    """Map a ``DjangoValidationError`` to an ``ErrorResponse`` 400 body.

    Surfaces ``DUPLICATE_NAME`` when ``validate_unique()`` flagged the failure
    so clients can distinguish a duplicate from a generic validation failure
    without grepping the prose detail string. Other validation errors stay
    on ``INVALID_DATA``.

    Parameters:
        ve: The Django ``ValidationError`` raised by ``full_clean()``.
        resource_label: Singular name of the resource being created/updated
            (``"component"``, ``"contact entity"``, …). Interpolated into the
            duplicate detail string.
        scope_label: The scope inside which uniqueness is enforced. Defaults
            to ``"team"`` because the bulk of CRUD resources have
            ``unique_together = ("team", "name")``; pass e.g.
            ``"contact profile"`` for ``ContactEntity`` whose uniqueness is
            ``unique_together = ("profile", "name")``. The resulting detail
            is "A {resource_label} with this name already exists in this
            {scope_label}".

    Disambiguation between a true uniqueness violation and a custom
    ``clean()`` rule that happens to say "already exists" is done by
    inspecting the ``ValidationError.error_dict``'s ``code`` attribute
    (Django sets ``code="unique"`` / ``"unique_together"`` on
    ``validate_unique()``'s errors). See ``_is_unique_violation``.
    """
    # ``message_dict`` raises ``AttributeError`` if the ValidationError
    # was built from a plain string / list rather than a dict; fall back
    # to a synthetic ``{"__all__": [...]}`` shape so the response always
    # carries an ``errors`` dict in the same wire format.
    try:
        msg_dict = ve.message_dict
    except AttributeError:
        msg_dict = {"__all__": list(ve.messages)}
    if _is_unique_violation(ve):
        return 400, {
            "detail": f"A {resource_label} with this name already exists in this {scope_label}",
            "errors": msg_dict,
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    return 400, {
        "detail": "Validation error",
        "errors": msg_dict,
        "error_code": ErrorCode.INVALID_DATA,
    }
