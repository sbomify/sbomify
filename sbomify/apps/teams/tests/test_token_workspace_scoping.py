"""Regression tests: a workspace-scoped access token must only see and act on
its bound workspace, even when the user is owner/admin of other workspaces.

Covers the production incident where a token scoped to workspace A could list
every workspace the user belongs to (which made the sbomify-action wizard bind
to the wrong workspace) and could create contact profiles in workspace B.
"""

from __future__ import annotations

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import ContactProfile, Member, Team

WORKSPACES_URL = "/api/v1/workspaces/"


@pytest.fixture
def owner_of_two_workspaces(db, django_user_model):
    """A user who is owner of two workspaces: the token-bound one and another."""
    user = django_user_model.objects.create_user(username="multiws", email="multiws@example.com", password="pw")
    bound = Team.objects.create(name="Bound WS")
    bound.key = number_to_random_token(bound.pk)
    bound.save()
    other = Team.objects.create(name="Other WS")
    other.key = number_to_random_token(other.pk)
    other.save()
    Member.objects.create(user=user, team=bound, role="owner", is_default_team=False)
    Member.objects.create(user=user, team=other, role="owner", is_default_team=True)
    return user, bound, other


@pytest.fixture
def scoped_token(owner_of_two_workspaces):
    user, bound, _ = owner_of_two_workspaces
    return AccessToken.objects.create(
        user=user, encoded_token=create_personal_access_token(user), team=bound, description="Scoped token"
    )


@pytest.fixture
def unscoped_token(owner_of_two_workspaces):
    user, _, _ = owner_of_two_workspaces
    return AccessToken.objects.create(
        user=user, encoded_token=create_personal_access_token(user), description="Unscoped token"
    )


def _headers(token: AccessToken) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token.encoded_token}"}


def _post_json(client: Client, url: str, payload: dict, token: AccessToken):
    return client.post(url, json.dumps(payload), content_type="application/json", **_headers(token))


def _patch_json(client: Client, url: str, payload: dict, token: AccessToken):
    return client.patch(url, json.dumps(payload), content_type="application/json", **_headers(token))


@pytest.mark.django_db
class TestWorkspaceListingScope:
    def test_scoped_token_lists_only_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, bound, _ = owner_of_two_workspaces
        response = Client().get(WORKSPACES_URL, **_headers(scoped_token))
        assert response.status_code == 200
        keys = [ws["key"] for ws in response.json()]
        assert keys == [bound.key]

    def test_unscoped_token_lists_all_workspaces(self, owner_of_two_workspaces, unscoped_token):
        _, bound, other = owner_of_two_workspaces
        response = Client().get(WORKSPACES_URL, **_headers(unscoped_token))
        assert response.status_code == 200
        keys = {ws["key"] for ws in response.json()}
        assert keys == {bound.key, other.key}

    def test_session_lists_all_workspaces(self, owner_of_two_workspaces):
        user, bound, other = owner_of_two_workspaces
        client = Client()
        client.force_login(user)
        response = client.get(WORKSPACES_URL)
        assert response.status_code == 200
        keys = {ws["key"] for ws in response.json()}
        assert keys == {bound.key, other.key}

    def test_publish_only_token_cannot_list_workspaces(self, owner_of_two_workspaces):
        user, bound, _ = owner_of_two_workspaces
        token = AccessToken.objects.create(
            user=user,
            encoded_token=create_personal_access_token(user),
            team=bound,
            scopes=["artifact:publish"],
            description="Publish-only token",
        )
        response = Client().get(WORKSPACES_URL, **_headers(token))
        assert response.status_code == 403

    def test_read_scoped_token_lists_bound_workspace(self, owner_of_two_workspaces):
        user, bound, _ = owner_of_two_workspaces
        token = AccessToken.objects.create(
            user=user,
            encoded_token=create_personal_access_token(user),
            team=bound,
            scopes=["workspace:read"],
            description="Read-scoped token",
        )
        response = Client().get(WORKSPACES_URL, **_headers(token))
        assert response.status_code == 200
        assert [ws["key"] for ws in response.json()] == [bound.key]


@pytest.mark.django_db
class TestContactProfileScope:
    def test_scoped_token_cannot_list_profiles_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        response = Client().get(f"{WORKSPACES_URL}{other.key}/contact-profiles", **_headers(scoped_token))
        assert response.status_code == 403

    def test_scoped_token_cannot_get_profile_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        profile = ContactProfile.objects.create(team=other, name="Existing")
        response = Client().get(f"{WORKSPACES_URL}{other.key}/contact-profiles/{profile.id}", **_headers(scoped_token))
        assert response.status_code == 403

    def test_scoped_token_cannot_create_profile_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        response = _post_json(
            Client(), f"{WORKSPACES_URL}{other.key}/contact-profiles", {"name": "Sneaky"}, scoped_token
        )
        assert response.status_code == 403
        assert not ContactProfile.objects.filter(team=other, name="Sneaky").exists()

    def test_scoped_token_cannot_update_profile_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        profile = ContactProfile.objects.create(team=other, name="Existing")
        response = _patch_json(
            Client(),
            f"{WORKSPACES_URL}{other.key}/contact-profiles/{profile.id}",
            {"name": "Renamed"},
            scoped_token,
        )
        assert response.status_code == 403
        profile.refresh_from_db()
        assert profile.name == "Existing"

    def test_scoped_token_cannot_delete_profile_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        profile = ContactProfile.objects.create(team=other, name="Existing")
        response = Client().delete(
            f"{WORKSPACES_URL}{other.key}/contact-profiles/{profile.id}", **_headers(scoped_token)
        )
        assert response.status_code == 403
        assert ContactProfile.objects.filter(pk=profile.pk).exists()

    def test_scoped_token_can_manage_profiles_in_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, bound, _ = owner_of_two_workspaces
        client = Client()
        base_url = f"{WORKSPACES_URL}{bound.key}/contact-profiles"

        response = _post_json(client, base_url, {"name": "In scope"}, scoped_token)
        assert response.status_code == 201
        profile_id = response.json()["id"]

        response = _patch_json(client, f"{base_url}/{profile_id}", {"name": "Still in scope"}, scoped_token)
        assert response.status_code == 200

        response = client.delete(f"{base_url}/{profile_id}", **_headers(scoped_token))
        assert response.status_code == 204

    def test_unscoped_token_can_manage_profiles_in_any_workspace(self, owner_of_two_workspaces, unscoped_token):
        _, _, other = owner_of_two_workspaces
        response = _post_json(
            Client(), f"{WORKSPACES_URL}{other.key}/contact-profiles", {"name": "Unscoped"}, unscoped_token
        )
        assert response.status_code == 201
        assert ContactProfile.objects.filter(team=other, name="Unscoped").exists()


@pytest.mark.django_db
class TestWorkspaceSettingsScope:
    def test_scoped_token_cannot_patch_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        response = _patch_json(Client(), f"{WORKSPACES_URL}{other.key}", {"name": "Hijacked"}, scoped_token)
        assert response.status_code == 403
        other.refresh_from_db()
        assert other.name == "Other WS"

    def test_scoped_token_cannot_update_branding_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        response = _patch_json(
            Client(), f"{WORKSPACES_URL}{other.key}/branding/brand_color", {"value": "#123456"}, scoped_token
        )
        assert response.status_code == 403

    def test_scoped_token_cannot_put_branding_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        response = Client().put(
            f"{WORKSPACES_URL}{other.key}/branding",
            json.dumps({"brand_color": "#123456"}),
            content_type="application/json",
            **_headers(scoped_token),
        )
        assert response.status_code == 403
        other.refresh_from_db()
        assert not other.branding_info.get("brand_color")

    def test_scoped_token_cannot_upload_branding_file_in_non_bound_workspace(
        self, owner_of_two_workspaces, scoped_token
    ):
        _, _, other = owner_of_two_workspaces
        response = Client().post(
            f"{WORKSPACES_URL}{other.key}/branding/upload/icon",
            {"file": SimpleUploadedFile("icon.png", b"not-a-real-png", content_type="image/png")},
            **_headers(scoped_token),
        )
        assert response.status_code == 403
        other.refresh_from_db()
        assert not other.branding_info.get("icon")

    def test_scoped_token_cannot_set_domain_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        for method in ("put", "patch"):
            response = getattr(Client(), method)(
                f"{WORKSPACES_URL}{other.key}/domain",
                json.dumps({"domain": "hijacked.example.com"}),
                content_type="application/json",
                **_headers(scoped_token),
            )
            assert response.status_code == 403
        other.refresh_from_db()
        assert not other.custom_domain

    def test_scoped_token_cannot_delete_domain_in_non_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, _, other = owner_of_two_workspaces
        other.custom_domain = "trust.other.example"
        other.custom_domain_validated = True
        other.save(update_fields=["custom_domain", "custom_domain_validated"])
        response = Client().delete(f"{WORKSPACES_URL}{other.key}/domain", **_headers(scoped_token))
        assert response.status_code == 403
        other.refresh_from_db()
        assert other.custom_domain == "trust.other.example"

    def test_scoped_token_can_patch_bound_workspace(self, owner_of_two_workspaces, scoped_token):
        _, bound, _ = owner_of_two_workspaces
        response = _patch_json(Client(), f"{WORKSPACES_URL}{bound.key}", {"name": "Renamed WS"}, scoped_token)
        assert response.status_code == 200
        bound.refresh_from_db()
        assert bound.name == "Renamed WS"
