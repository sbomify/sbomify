"""Conformance tests for the global NinjaAPI CSRF enforcement (#922).

The webhook view enables ``NinjaAPI(csrf=True)`` so session/cookie-authenticated API
mutations require an ``X-CSRFToken``. PAT/bearer clients carry no CSRF cookie and are
exempted by ``BearerAuthCsrfExemptMiddleware`` so programmatic API access still works.

These use ``Client(enforce_csrf_checks=True)`` because the default test client disables
CSRF entirely (which is exactly why a naive ``csrf=True`` would ship green yet break PAT
clients in production).
"""

import pytest
from django.test import Client

from sbomify.apps.core.tests.shared_fixtures import get_api_headers

pytestmark = pytest.mark.django_db

# A syntactically-valid but nonexistent workspace key: a request that clears the CSRF gate
# and authenticates reaches the team lookup and 404s — distinguishing "CSRF passed" from
# the CSRF 403, without depending on S3/permissions.
NONEXISTENT_TEAM = "AAAAAAAAAAAA"
BRANDING_URL = f"/api/v1/workspaces/{NONEXISTENT_TEAM}/branding/brand_color"
BODY = {"value": "#123456"}


def test_session_mutation_without_csrf_token_is_forbidden(sample_user):
    """A session-authenticated API mutation without X-CSRFToken must be rejected (403)."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(sample_user)

    resp = client.patch(BRANDING_URL, data=BODY, content_type="application/json")

    assert resp.status_code == 403


def test_session_mutation_with_csrf_token_passes_the_gate(sample_user):
    """A session-authenticated API mutation WITH a valid X-CSRFToken clears the CSRF gate."""
    from django.middleware.csrf import get_token
    from django.test import RequestFactory

    client = Client(enforce_csrf_checks=True)
    client.force_login(sample_user)
    # The same masked token in the cookie and the header unmask to the same secret,
    # which is exactly what Django's CSRF check validates.
    token = get_token(RequestFactory().get("/"))
    client.cookies["csrftoken"] = token

    resp = client.patch(
        BRANDING_URL, data=BODY, content_type="application/json", HTTP_X_CSRFTOKEN=token
    )

    assert resp.status_code != 403  # gate cleared (404 for the nonexistent team)


def test_bearer_mutation_without_csrf_token_is_exempt(authenticated_api_client):
    """A PAT/bearer API mutation without X-CSRFToken must be CSRF-exempt and authenticate."""
    client, token = authenticated_api_client

    resp = client.patch(
        BRANDING_URL, data=BODY, content_type="application/json", **get_api_headers(token)
    )

    # Not a CSRF 403: the bearer request clears the gate, authenticates, and 404s on the team.
    assert resp.status_code == 404
