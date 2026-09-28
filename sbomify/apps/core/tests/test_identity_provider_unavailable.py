"""Sign-in answers 503, not 500, when the identity provider cannot be reached."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
from django.test import Client, RequestFactory
from django.urls import resolve

from sbomify.apps.core.middleware import IdentityProviderUnavailableMiddleware

LOGIN_URL = "/accounts/oidc/keycloak/login/"


def _provider_response(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://kc.example.test/realms/sbomify/.well-known/openid-configuration"
    return response


def _unavailable_response(*args: object, **kwargs: object) -> requests.Response:
    return _provider_response(503)


@pytest.mark.django_db
class TestSignInWhenIdentityProviderIsDown:
    def test_timeout_renders_sign_in_unavailable(self, client: Client) -> None:
        with patch("requests.Session.request", side_effect=requests.ReadTimeout("read timeout=5")):
            response = client.get(LOGIN_URL)

        assert response.status_code == 503
        assert "Sign-in is unavailable. Try again in a minute." in response.content.decode()

    def test_provider_503_renders_sign_in_unavailable(self, client: Client) -> None:
        with patch("requests.Session.request", side_effect=_unavailable_response):
            response = client.get(LOGIN_URL)

        assert response.status_code == 503
        assert "Sign-in is unavailable. Try again in a minute." in response.content.decode()


def test_network_errors_elsewhere_are_left_alone() -> None:
    request = RequestFactory().get("/")
    request.resolver_match = resolve("/")
    middleware = IdentityProviderUnavailableMiddleware(lambda r: None)

    assert middleware.process_exception(request, requests.ReadTimeout()) is None


@pytest.mark.parametrize(
    "exception",
    [
        requests.exceptions.MissingSchema("Invalid URL"),
        requests.HTTPError(response=_provider_response(404)),
    ],
)
def test_configuration_errors_at_sign_in_are_left_alone(exception: Exception) -> None:
    request = RequestFactory().get(LOGIN_URL)
    request.resolver_match = resolve(LOGIN_URL)
    middleware = IdentityProviderUnavailableMiddleware(lambda r: None)

    assert middleware.process_exception(request, exception) is None
