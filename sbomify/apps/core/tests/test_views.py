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
        KEYCLOAK_CLIENT_ID="sbomify",
        KEYCLOAK_PUBLIC_URL="https://test-domain.com/",
    ):
        response: HttpResponse = client.get(reverse("core:logout"))
        assert response.status_code == 302
        assert response.url.startswith("https://test-domain.com/realms/sbomify/protocol/openid-connect/logout?")
        assert "client_id=sbomify" in response.url
        assert "post_logout_redirect_uri=http%3A%2F%2Ftest-return.url%2Faccounts%2Foidc%2Fkeycloak%2Flogin%2F" in response.url


@pytest.mark.django_db
def test_logout_view(client: Client, sample_user: AbstractBaseUser):
    """Test that logout view works correctly."""
    client.force_login(sample_user)
    with override_settings(
        KEYCLOAK_SERVER_URL="https://test-domain.com",
        KEYCLOAK_REALM="sbomify",
        APP_BASE_URL="http://test-return.url",
        KEYCLOAK_CLIENT_ID="sbomify",
        KEYCLOAK_PUBLIC_URL="https://test-domain.com/",
    ):
        response = client.get(reverse("core:logout"))
        assert response.status_code == 302
        assert response.url.startswith("https://test-domain.com/realms/sbomify/protocol/openid-connect/logout?")
        assert "client_id=sbomify" in response.url
        assert "post_logout_redirect_uri=http%3A%2F%2Ftest-return.url%2Faccounts%2Foidc%2Fkeycloak%2Flogin%2F" in response.url


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
    """/login should now redirect straight into the Allauth Keycloak flow."""
    client.logout()
    response = client.get(reverse("core:keycloak_login"), follow=False)
    assert response.status_code in (301, 302)
    assert response["Location"].endswith("/accounts/oidc/keycloak/login/")


@pytest.mark.django_db
def test_login_page_renders_account_login(client: Client) -> None:
    """/login should redirect to the Keycloak provider login entrypoint."""
    client.logout()
    response = client.get("/login/", follow=False)
    assert response.status_code in (301, 302)
    assert response["Location"].endswith("/accounts/oidc/keycloak/login/")


@pytest.mark.django_db
def test_logout_unauthenticated_user_redirects_to_login(client: Client) -> None:
    """Unauthenticated user accessing logout should redirect to login page.

    This tests the behavior added to handle unauthenticated users gracefully.
    """
    client.logout()  # Ensure no session
    response = client.get(reverse("core:logout"), follow=False)
    assert response.status_code == 302
    # Should redirect to keycloak_login
    assert "/login" in response["Location"] or "keycloak" in response["Location"].lower()


@pytest.mark.django_db
def test_keycloak_login_rejects_malicious_next_parameter(client: Client) -> None:
    """Malicious 'next' parameters with external hosts should be rejected.

    The open redirect validation should strip out any next parameter that
    points to an external domain to prevent open redirect attacks.
    """
    client.logout()

    # Test with external URL - should NOT include the next parameter
    malicious_urls = [
        "https://evil.com/phishing",
        "//evil.com/path",
        "http://attacker.net/steal",
        "https://evil.com",
    ]

    for malicious_url in malicious_urls:
        response = client.get(
            reverse("core:keycloak_login") + f"?next={malicious_url}",
            follow=False
        )
        assert response.status_code in (301, 302)
        # The redirect URL should NOT contain the malicious next parameter
        location = response["Location"]
        assert malicious_url not in location, f"Malicious URL {malicious_url} should be rejected"
        # Should just redirect to the base login URL without the next param
        assert "/accounts/oidc/keycloak/login/" in location


@pytest.mark.django_db
def test_keycloak_login_preserves_valid_next_parameter(client: Client) -> None:
    """Valid internal 'next' parameters should be preserved.

    The open redirect validation should allow next parameters that point
    to the same host.
    """
    client.logout()

    # Test with valid internal path - should include the next parameter
    valid_next = "/dashboard/"
    response = client.get(
        reverse("core:keycloak_login") + f"?next={valid_next}",
        follow=False,
        HTTP_HOST="testserver",
    )
    assert response.status_code in (301, 302)
    location = response["Location"]
    # The redirect URL should contain the next parameter
    assert "/accounts/oidc/keycloak/login/" in location
    assert "next=" in location or "next%3D" in location.lower()
