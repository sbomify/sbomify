import os
from urllib.parse import urlencode

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken


def _clear_current_team(client: Client) -> None:
    """Clear current_team from session to prevent redirect to team tokens page."""
    session = client.session
    if "current_team" in session:
        del session["current_team"]
    session.save()


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

    # Mark plan as selected so the plan selection redirect is skipped
    from sbomify.apps.teams.models import Member

    member = Member.objects.filter(user=sample_user, is_default_team=True).first()
    if member:
        member.team.has_selected_billing_plan = True
        member.team.save(update_fields=["has_selected_billing_plan"])

    response: HttpResponse = client.get(reverse("core:dashboard"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_access_token_creation_blocked_without_workspace(sample_user: AbstractBaseUser):  # noqa: F811
    """Token creation via legacy settings POST is blocked without a workspace context."""
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    _clear_current_team(client)

    uri = reverse("core:settings")
    form_data = urlencode({"description": "Test Token"})
    response = client.post(uri, form_data, content_type="application/x-www-form-urlencoded")
    assert response.status_code == 200
    msgs = list(get_messages(response.wsgi_request))
    assert any("Tokens can only be created from a workspace" in m.message for m in msgs)
    access_tokens = AccessToken.objects.filter(user=sample_user).all()
    assert len(access_tokens) == 0


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
        expected_redirect = "post_logout_redirect_uri=http%3A%2F%2Ftest-return.url"
        assert expected_redirect in response.url


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
        expected_redirect = "post_logout_redirect_uri=http%3A%2F%2Ftest-return.url"
        assert expected_redirect in response.url


@pytest.mark.django_db
def test_delete_nonexistent_access_token(sample_user: AbstractBaseUser):
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response = client.post(reverse("core:delete_access_token", kwargs={"token_id": 999}))
    assert response.status_code == 404
    # No message is actually added in the view for this case, just the 404 response


@pytest.mark.django_db
def test_delete_another_users_token(guest_user: AbstractBaseUser, sample_user: AbstractBaseUser):
    # Create token directly for guest user
    from sbomify.apps.access_tokens.utils import create_personal_access_token

    token_str = create_personal_access_token(guest_user)
    guest_token = AccessToken.objects.create(user=guest_user, encoded_token=token_str, description="Guest Token")

    # Log in as sample user and try to delete guest's token
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response = client.post(reverse("core:delete_access_token", kwargs={"token_id": guest_token.id}))
    assert response.status_code == 403
    assert AccessToken.objects.filter(id=guest_token.id).exists()


@pytest.mark.django_db
def test_delete_access_token_with_delete_method(sample_user: AbstractBaseUser):
    """Test that DELETE method works for deleting access tokens."""
    from sbomify.apps.access_tokens.utils import create_personal_access_token

    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    # Create a token directly
    token_str = create_personal_access_token(sample_user)
    token = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="Test Token")

    # Delete using DELETE method
    response = client.delete(reverse("core:delete_access_token", kwargs={"token_id": token.id}))
    assert response.status_code == 200
    assert not AccessToken.objects.filter(id=token.id).exists()


@pytest.mark.django_db
def test_delete_access_token_json_request(sample_user: AbstractBaseUser):
    """Test that JSON request returns JSON response."""
    from sbomify.apps.access_tokens.utils import create_personal_access_token

    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    # Create a token directly
    token_str = create_personal_access_token(sample_user)
    token = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="Test Token JSON")

    # Delete using DELETE method with JSON content type
    response = client.delete(
        reverse("core:delete_access_token", kwargs={"token_id": token.id}), content_type="application/json"
    )
    assert response.status_code == 200
    assert not AccessToken.objects.filter(id=token.id).exists()


@pytest.mark.django_db
def test_delete_access_token_htmx_request(sample_user: AbstractBaseUser):
    """Test that HTMX request returns proper response."""
    from sbomify.apps.access_tokens.utils import create_personal_access_token

    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    # Create a token directly
    token_str = create_personal_access_token(sample_user)
    token = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="Test Token HTMX")

    # Delete using POST method with HTMX header
    response = client.post(reverse("core:delete_access_token", kwargs={"token_id": token.id}), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert not AccessToken.objects.filter(id=token.id).exists()


@pytest.mark.django_db
def test_delete_access_token_json_error_responses(sample_user: AbstractBaseUser, guest_user: AbstractBaseUser):
    """Test that JSON requests return JSON error responses."""
    from sbomify.apps.access_tokens.utils import create_personal_access_token

    # Create token directly for guest user
    token_str = create_personal_access_token(guest_user)
    guest_token = AccessToken.objects.create(user=guest_user, encoded_token=token_str, description="Guest Token")

    # Log in as sample user and try to delete guest's token
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    # Test 403 error with JSON request
    response = client.delete(
        reverse("core:delete_access_token", kwargs={"token_id": guest_token.id}),
        content_type="application/json",
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 403
    assert response["Content-Type"] == "application/json"
    data = response.json()
    assert "detail" in data
    assert "Not allowed" in data["detail"]

    # Test 404 error with JSON request
    response = client.delete(
        reverse("core:delete_access_token", kwargs={"token_id": 99999}),
        content_type="application/json",
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"] == "application/json"
    data = response.json()
    assert "detail" in data


@pytest.mark.django_db
def test_settings_post_redirects_with_workspace(sample_user: AbstractBaseUser):
    """POST to legacy settings with a workspace redirects to team tokens."""
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    initial_count = AccessToken.objects.count()

    # Submit form - user has a workspace from login, so POST redirects
    response = client.post(
        reverse("core:settings"),
        {"description": "Test Token"},
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 302
    assert "/tokens" in response.url
    assert AccessToken.objects.count() == initial_count


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
        response = client.get(reverse("core:keycloak_login") + f"?next={malicious_url}", follow=False)
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
