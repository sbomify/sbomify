"""OIDC logout remains usable after local sign-out and reauthentication."""

from urllib.parse import parse_qs, urlsplit

import pytest
from allauth.core.context import request_context
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialAccount, SocialToken
from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter
from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.adapters import OIDC_ID_TOKEN_SESSION_KEY
from sbomify.apps.core.models import User
from sbomify.apps.core.views import logout


@pytest.mark.django_db
@pytest.mark.parametrize("already_authenticated", [False, True])
def test_completed_login_retains_logout_hint(already_authenticated: bool, mocker: MockerFixture) -> None:
    """Anonymous sign-in and replacement of an existing session both retain the validated token."""
    user = User.objects.create_user(username="returning", email="returning@example.com", email_verified=True)
    SocialAccount.objects.create(user=user, provider="keycloak", uid="returning")
    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    MessageMiddleware(lambda r: HttpResponse()).process_request(request)
    request.user = AnonymousUser()
    if already_authenticated:
        django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    claims = {"sub": "returning", "email": user.email, "email_verified": True}
    mocker.patch.object(OpenIDConnectOAuth2Adapter, "_decode_id_token", return_value=claims)
    mocker.patch.object(OpenIDConnectOAuth2Adapter, "_fetch_user_info", return_value=claims)
    with request_context(request):
        provider = get_adapter().get_provider(request, "keycloak")
        adapter = OpenIDConnectOAuth2Adapter(request, "keycloak")
        sociallogin = adapter.complete_login(
            request, provider.app, SocialToken(token="access-token"), response={"id_token": "validated.raw.token"}
        )
        sociallogin.state = {"process": "login"}
        complete_social_login(request, sociallogin)
    assert request.user.pk == user.pk
    assert request.session[OIDC_ID_TOKEN_SESSION_KEY] == "validated.raw.token"
    assert not hasattr(request, "_oidc_id_token")
    with override_settings(OIDC_LOGOUT_URL="https://idp.example.com/logout", APP_BASE_URL="http://testserver"):
        response = logout(request)
    assert parse_qs(urlsplit(response["Location"]).query)["id_token_hint"] == ["validated.raw.token"]
    assert OIDC_ID_TOKEN_SESSION_KEY not in request.session


@pytest.mark.django_db
def test_login_finished_after_the_signup_form_retains_logout_hint(mocker: MockerFixture) -> None:
    """A provider that sends no email stops at allauth's signup form, and login finishes in a later request."""
    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    MessageMiddleware(lambda r: HttpResponse()).process_request(request)
    request.user = AnonymousUser()
    claims = {"sub": "no-email"}
    mocker.patch.object(OpenIDConnectOAuth2Adapter, "_decode_id_token", return_value=claims)
    mocker.patch.object(OpenIDConnectOAuth2Adapter, "_fetch_user_info", return_value=claims)
    with request_context(request):
        provider = get_adapter().get_provider(request, "keycloak")
        adapter = OpenIDConnectOAuth2Adapter(request, "keycloak")
        sociallogin = adapter.complete_login(
            request, provider.app, SocialToken(token="access-token"), response={"id_token": "validated.raw.token"}
        )
        sociallogin.state = {"process": "login"}
        response = complete_social_login(request, sociallogin)
    assert response["Location"] == reverse("socialaccount_signup")
    request.session.save()

    client = Client()
    client.cookies[settings.SESSION_COOKIE_NAME] = request.session.session_key
    client.post(reverse("socialaccount_signup"), {"email": "late@example.com"})

    assert "_auth_user_id" in client.session
    assert client.session[OIDC_ID_TOKEN_SESSION_KEY] == "validated.raw.token"


@pytest.mark.django_db
@pytest.mark.parametrize("discovery_fails", [False, True])
def test_local_logout_waits_for_explicit_sign_in(client: Client, mocker: MockerFixture, discovery_fails: bool) -> None:
    """Missing logout metadata or a discovery outage must not restart an active provider session."""
    user = User.objects.create_user(username="reader", email="reader@example.com")
    client.force_login(user)
    config = {"authorization_endpoint": "https://idp.example.com/authorize"}
    discovery = mocker.patch.object(
        OpenIDConnectOAuth2Adapter, "openid_config", new_callable=mocker.PropertyMock, return_value=config
    )
    if discovery_fails:
        discovery.side_effect = RuntimeError("provider unavailable")
    with override_settings(
        OIDC_DISCOVERY_URL="https://idp.example.com/.well-known/openid-configuration", OIDC_LOGOUT_URL=""
    ):
        response = client.get(reverse("core:logout"), follow=True)
        assert response.status_code == 200
        assert response.redirect_chain == [(reverse("core:signed_out"), 302)]
        assert "_auth_user_id" not in client.session
        assert b"You are signed out" in response.content
        assert f'href="{reverse("core:keycloak_login")}"'.encode() in response.content
        discovery.assert_called_once()
        # Reloading the landing page also stays local and anonymous.
        assert client.get(reverse("core:signed_out")).status_code == 200
        discovery.assert_called_once()
