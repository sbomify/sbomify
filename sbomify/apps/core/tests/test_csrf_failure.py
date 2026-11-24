"""The custom CSRF failure view turns the stock dead-end 403 into a retry."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory

from sbomify.apps.core.views.csrf_failure import RETRY_MESSAGE, csrf_failure


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

    def test_htmx_request_is_redirected_to_a_fresh_render(self, sample_user):
        client = self._client(sample_user)
        response = client.post(
            "/workspaces/onboarding/",
            {},
            HTTP_HX_REQUEST="true",
            HTTP_REFERER="http://testserver/workspaces/onboarding/?step=setup",
        )
        assert response.status_code == 204
        assert response.headers["HX-Redirect"] == "http://testserver/workspaces/onboarding/?step=setup"

    def test_htmx_request_without_referer_redirects_to_the_same_path(self, sample_user):
        client = self._client(sample_user)
        response = client.post("/workspaces/onboarding/", {}, HTTP_HX_REQUEST="true")
        assert response.status_code == 204
        assert response.headers["HX-Redirect"] == "/workspaces/onboarding/"

    def test_no_referer_falls_back_to_the_error_page(self, sample_user):
        client = self._client(sample_user)
        response = client.post("/workspaces/onboarding/", {})
        assert response.status_code == 403
        assert b"submit the form again" in response.content


class TestRefererBranch:
    """Which branch the view picks, taken at the view rather than end to end.

    The fallback branch renders the full error page, so a test that drives it
    through the client is really a test of the template and its built assets.
    What is worth pinning here is smaller and was the actual defect: a Referer
    that is not a URL used to leave this view by raising, so the view whose job
    is to turn a 403 into something friendly answered 500 instead.

    ``url_has_allowed_host_and_scheme`` does not catch that on its own. It asks
    whether a value points at a host we own, and every relative value passes,
    including a bare word. ``redirect()`` then reads a string with no path
    separator as a view name and reverses it. Django's CSRF middleware calls
    this view *because* it rejected the request, and a malformed Referer is one
    of the reasons it rejects one, so this is the expected input, not a rare
    one.
    """

    @staticmethod
    def _request(referer: str | None = None, *, htmx: bool = False) -> HttpRequest:
        extra = {}
        if referer is not None:
            extra["HTTP_REFERER"] = referer
        if htmx:
            extra["HTTP_HX_REQUEST"] = "true"
        request = RequestFactory().post("/workspaces/onboarding/", **extra)
        request.session = SessionBase()
        request._messages = FallbackStorage(request)
        return request

    @pytest.mark.parametrize(
        "referer",
        [
            # A bare word, and a relative path with no leading slash. Both
            # point at no host, so the host check passes them, and both reach
            # reverse() as view names. This is the live defect.
            "not-a-url",
            "workspaces/onboarding/",
            # Percent-encoded rather than literal, so Django's own
            # leading-control-character check does not see it.
            "%00",
            # A literal control character. Django rejects this one on its own
            # today; pinned so the branch does not depend on that staying true.
            "\x00",
            # Off-site. Rejected before this change too, and still rejected.
            "https://evil.example.com/phish",
        ],
    )
    def test_an_unusable_referer_falls_back_to_the_error_page(self, referer):
        with patch("sbomify.apps.core.errors.error_response") as error_page:
            error_page.return_value = HttpResponse(RETRY_MESSAGE, status=403)
            response = csrf_failure(self._request(referer))

        assert error_page.called
        assert response.status_code == 403

    def test_an_unusable_referer_does_not_reach_the_htmx_redirect_header(self):
        response = csrf_failure(self._request("not-a-url", htmx=True))

        assert response.status_code == 204
        assert response.headers["HX-Redirect"] == "/workspaces/onboarding/"

    def test_a_same_host_referer_is_still_a_redirect(self):
        response = csrf_failure(self._request("http://testserver/workspaces/onboarding/?step=setup"))

        assert response.status_code == 302
        assert response["Location"] == "http://testserver/workspaces/onboarding/?step=setup"

    def test_a_root_relative_referer_is_still_a_redirect(self):
        response = csrf_failure(self._request("/workspaces/onboarding/?step=setup"))

        assert response.status_code == 302
        assert response["Location"] == "/workspaces/onboarding/?step=setup"
