"""The custom CSRF failure view turns the stock dead-end 403 into a retry."""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.mark.django_db
class TestCsrfFailureRecovery:
    def _client(self, sample_user) -> Client:
        client = Client(enforce_csrf_checks=True)
        client.force_login(sample_user)
        return client

    def test_stale_token_redirects_back_with_a_message(self, sample_user):
        client = self._client(sample_user)
        response = client.post(
            "/workspaces/onboarding/",
            {"company_name": "Acme"},
            HTTP_REFERER="http://testserver/workspaces/onboarding/?step=setup",
        )
        assert response.status_code == 302
        assert response["Location"] == "http://testserver/workspaces/onboarding/?step=setup"

    def test_htmx_request_gets_an_htmx_error(self, sample_user):
        client = self._client(sample_user)
        response = client.post("/workspaces/onboarding/", {}, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert response.headers.get("HX-Reswap") == "none"

    def test_no_referer_falls_back_to_the_error_page(self, sample_user):
        client = self._client(sample_user)
        response = client.post("/workspaces/onboarding/", {})
        assert response.status_code == 403
        assert b"submit the form again" in response.content
