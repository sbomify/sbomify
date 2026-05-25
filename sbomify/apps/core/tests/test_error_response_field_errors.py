"""Tests for the `ErrorResponse.errors` field (issue #952).

Before #952, `ErrorResponse` only declared `{detail, error_code}` so
django-ninja silently stripped the `errors` key out of the response body.
Per-field validation errors from Django's `ValidationError.message_dict`
never reached the client.

These tests pin the new contract: when an endpoint returns 400 with an
`errors` dict, the wire response MUST include that dict with the same
shape (`{"<field-name>": ["<msg1>", "<msg2>"]}`).
"""

from __future__ import annotations

import json
import os

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.tests.fixtures import sample_access_token, sample_billing_plan  # noqa: F401
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401


@pytest.mark.django_db
def test_duplicate_component_name_returns_field_errors(
    sample_team_with_owner_member,  # noqa: F811
    sample_access_token,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """The reproduction from issue #952: POSTing a component with a name
    that already exists in the team must return a 400 with the per-field
    error reaching the client (not silently stripped).
    """
    team = sample_team_with_owner_member.team
    user = sample_team_with_owner_member.user
    # Billing plan is needed so the create endpoint passes the
    # `_check_billing_limits` guard and reaches the validation path.
    team.billing_plan = sample_billing_plan.key
    team.save()
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"],
        password=os.environ["DJANGO_TEST_PASSWORD"],
    )
    setup_test_session(client, team, user)

    # Seed an existing component with the name we'll try to duplicate
    Component.objects.create(team=team, name="duplicate-me")

    # POST the duplicate
    url = reverse("api-1:create_component")
    payload = {"name": "duplicate-me", "component_type": "bom"}
    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    data = response.json()

    # Standard fields: still there
    assert "detail" in data
    # Issue #953: the same path that this test exercises (POST a duplicate
    # name) now surfaces ``DUPLICATE_NAME`` directly instead of the catch-all
    # ``INVALID_DATA``. The original #952 invariant — "errors dict survives
    # serialization" — is unchanged; only the error_code label is more
    # specific now.
    assert data.get("error_code") == "DUPLICATE_NAME"

    # The new fix: `errors` field is preserved on the wire (not stripped
    # by the django-ninja serializer). Before the schema fix, this assertion
    # would fail because the response was `{"detail": "...", "error_code": "..."}`
    # with no `errors` key at all.
    assert "errors" in data, f"ErrorResponse.errors was stripped (issue #952 regression). Got: {data}"
    assert isinstance(data["errors"], dict)
    # Django's ``unique_together = ("team", "name")`` constraint surfaces
    # the validation error under ``__all__`` (NON_FIELD_ERRORS). The
    # important assertion for the #952 regression is that the dict
    # survived serialization at all; the helper's any-key scan covers
    # the alternative single-field ``unique=True`` shape in
    # ``TestValidationErrorResponseHelper``.
    assert any(data["errors"].values()), f"`errors` dict was preserved but is empty: {data['errors']}"


@pytest.mark.django_db
def test_error_response_schema_round_trip():
    """Schema-level unit pin: `ErrorResponse` accepts an `errors` dict and
    serializes it back. This guards against a future schema rewrite that
    drops the field again."""
    from sbomify.apps.core.schemas import ErrorCode, ErrorResponse

    resp = ErrorResponse(
        detail="Validation error",
        error_code=ErrorCode.INVALID_DATA,
        errors={"name": ["Component with this Team and Name already exists."]},
    )
    dumped = resp.model_dump()
    assert dumped["errors"] == {"name": ["Component with this Team and Name already exists."]}, (
        "ErrorResponse.errors must round-trip through pydantic serialization."
    )

    # Without `errors` set, the field defaults to None at the pydantic
    # level. Note: django-ninja does NOT apply `exclude_none` by default,
    # so the wire response includes `"errors": null` rather than omitting
    # the key entirely (verified by `teams/tests/test_contact_profiles.py
    # ::test_get_contact_profile_not_found`, which asserts
    # `errors: None` in the JSON body for a 404 response). Clients that
    # need to distinguish "field not set" from "field has no errors"
    # should treat both `null` and missing as "no per-field info".
    resp_no_errors = ErrorResponse(detail="not found", error_code=ErrorCode.NOT_FOUND)
    assert resp_no_errors.errors is None
