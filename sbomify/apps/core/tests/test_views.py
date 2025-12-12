import os
from urllib.parse import urlencode

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken


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

    # New users are redirected to onboarding wizard - set has_completed_wizard=True to skip
    session = client.session
    if "current_team" in session:
        session["current_team"]["has_completed_wizard"] = True
        session.save()

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
        KEYCLOAK_SERVER_URL="https://test-domain.com",
        KEYCLOAK_REALM="sbomify",
        APP_BASE_URL="http://test-return.url",
    ):
        response: HttpResponse = client.get(reverse("core:logout"))
        assert response.status_code == 302
        assert response.url.startswith("https://test-domain.com/realms/sbomify/protocol/openid-connect/logout")
        assert "redirect_uri=http://test-return.url" in response.url


@pytest.mark.django_db
def test_logout_view(client: Client, sample_user: AbstractBaseUser):
    """Test that logout view works correctly."""
    client.force_login(sample_user)
    with override_settings(
        KEYCLOAK_SERVER_URL="https://test-domain.com",
        KEYCLOAK_REALM="sbomify",
        APP_BASE_URL="http://test-return.url",
    ):
        response = client.get(reverse("core:logout"))
        assert response.status_code == 302
        assert response.url.startswith("https://test-domain.com/realms/sbomify/protocol/openid-connect/logout")
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


@pytest.mark.django_db
def test_keycloak_login_page_redirects_or_renders(client: Client) -> None:
    """Test that the custom Keycloak login page either renders or redirects to the Allauth login page."""
    client.logout()
    response = client.get(reverse("core:keycloak_login"), follow=False)
    # Accept either a direct render or a redirect to /accounts/login/
    if response.status_code in (301, 302):
        assert response["Location"].endswith("/accounts/login/")
    else:
        assert response.status_code == 200
        assert b"Log In / Register" in response.content


@pytest.mark.django_db
def test_login_page_renders_account_login(client: Client) -> None:
    """Test that /login renders the Allauth login page (account/login.html) without redirect."""
    client.logout()
    response = client.get("/login", follow=False)
    assert response.status_code == 200
    # Check for a string unique to the Allauth login page
    assert b"Sign In" in response.content or b"Log In" in response.content
