import os
from urllib.parse import urlencode

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import reverse

from access_tokens.models import AccessToken


@pytest.mark.django_db
def test_homepage():
    client = Client()
    response: HttpResponse = client.get(reverse("core:home"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_dashboard_is_only_accessible_when_logged_in(sample_user: AbstractBaseUser):  # noqa: F811
    client = Client()
    response: HttpResponse = client.get(reverse("core:dashboard"))
    assert response.status_code == 302

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    response: HttpResponse = client.get(reverse("core:dashboard"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_access_token_creation(sample_user: AbstractBaseUser):  # noqa: F811
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    uri = reverse("core:settings")
    form_data = urlencode({"description": "Test Token"})
    response = client.post(uri, form_data, content_type="application/x-www-form-urlencoded")
    assert response.status_code == 200
    messages = list(get_messages(response.wsgi_request))
    assert any(m.message == "New access token created" for m in messages)
    access_tokens = AccessToken.objects.filter(user=sample_user).all()
    assert len(access_tokens) == 1


@pytest.mark.django_db
def test_logout_redirect(sample_user: AbstractBaseUser):
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    with override_settings(
        SOCIAL_AUTH_AUTH0_DOMAIN="test-domain.com",
        SOCIAL_AUTH_AUTH0_KEY="test-client-id",
        APP_BASE_URL="http://test-return.url",
        USE_KEYCLOAK=False,  # Force Auth0 logout flow for this test
    ):
        response: HttpResponse = client.get(reverse("core:logout"))
        assert response.status_code == 302
        assert response.url.startswith("https://test-domain.com/v2/logout")
        assert "client_id=test-client-id" in response.url
        assert "returnTo=http://test-return.url" in response.url


@pytest.mark.django_db
def test_logout_redirect_keycloak(django_user_model):
    """Test the logout redirect when Keycloak is enabled."""
    # Create a test user
    user = django_user_model.objects.create(
        username="keycloak_test_user",
        email="keycloak_test@example.com",
    )
    user.set_password("keycloak_test_password")
    user.save()

    client = Client()
    assert client.login(username="keycloak_test_user", password="keycloak_test_password")

    with override_settings(
        KEYCLOAK_SERVER_URL="http://test-keycloak.com/",
        KEYCLOAK_REALM="test-realm",
        APP_BASE_URL="http://test-return.url",
        USE_KEYCLOAK=True,  # Force Keycloak logout flow for this test
    ):
        response: HttpResponse = client.get(reverse("core:logout"))
        assert response.status_code == 302
        expected_url = "http://test-keycloak.com/realms/test-realm/protocol/openid-connect/logout"
        assert response.url.startswith(expected_url)
        assert "redirect_uri=http://test-return.url" in response.url


@pytest.mark.django_db
def test_delete_nonexistent_access_token(sample_user: AbstractBaseUser):
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response = client.post(reverse("core:delete_access_token", kwargs={"token_id": 999}))
    assert response.status_code == 404
    # No message is actually added in the view for this case, just the 404 response


@pytest.mark.django_db
def test_delete_another_users_token(guest_user: AbstractBaseUser, sample_user: AbstractBaseUser):
    # Create token with guest user
    client = Client()
    assert client.login(username="guest", password="guest")

    # Properly format form data and set content type
    form_data = urlencode({"description": "Guest Token"})
    response = client.post(
        reverse("core:settings"),
        form_data,
        content_type="application/x-www-form-urlencoded"
    )

    # Verify successful token creation
    assert response.status_code == 200
    messages = list(get_messages(response.wsgi_request))
    assert any(m.message == "New access token created" for m in messages)

    guest_token = AccessToken.objects.filter(user=guest_user).first()
    assert guest_token is not None, "Token should have been created for guest user"

    # Switch to sample user and try to delete
    client.logout()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"],
        password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    response = client.post(reverse("core:delete_access_token", kwargs={"token_id": guest_token.id}))
    assert response.status_code == 403
    assert AccessToken.objects.filter(id=guest_token.id).exists()


@pytest.mark.django_db
def test_settings_invalid_form_submission(sample_user: AbstractBaseUser):
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    initial_count = AccessToken.objects.count()

    # Submit empty form
    response = client.post(
        reverse("core:settings"),
        {"description": ""},  # Invalid empty description
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 200
    assert AccessToken.objects.count() == initial_count
    messages = list(get_messages(response.wsgi_request))
    assert not any(m.message == "New access token created" for m in messages)
