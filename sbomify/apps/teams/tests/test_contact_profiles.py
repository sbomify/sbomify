from __future__ import annotations

import json

import pytest

from sbomify.apps.core.tests.shared_fixtures import authenticated_api_client, get_api_headers, guest_api_client
from sbomify.apps.teams.fixtures import (  # noqa: F401
    sample_team_with_guest_member,
    sample_team_with_owner_member,
)
from sbomify.apps.teams.models import ContactProfile


@pytest.mark.django_db
def test_contact_profile_crud(sample_team_with_owner_member, authenticated_api_client):  # noqa: F811
    team = sample_team_with_owner_member.team
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    base_url = f"/api/v1/workspaces/{team.key}/contact-profiles"
    create_url = base_url
    list_url = base_url

    payload = {
        "name": "Primary Contacts",
        "company": "Example Corp",
        "supplier_name": "Example Supplier",
        "vendor": "Example Vendor",
        "email": "support@example.com",
        "phone": "+1-555-0100",
        "address": "100 Example Avenue",
        "website_urls": ["https://example.com"],
        "contacts": [
            {"name": "Alice", "email": "alice@example.com", "phone": "555-0101"},
            {"name": "Bob", "email": "bob@example.com", "phone": "555-0102"},
        ],
        "is_default": False,
    }

    response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
    assert response.status_code == 201
    profile_data = response.json()
    profile_id = profile_data["id"]

    assert ContactProfile.objects.filter(id=profile_id, team=team).exists()

    # List profiles and ensure newly created profile is present
    response = client.get(list_url, **headers)
    assert response.status_code == 200
    profiles = response.json()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "Primary Contacts"
    assert profiles[0]["is_default"] is False

    # Update profile, mark as default
    update_url = f"{base_url}/{profile_id}"
    update_payload = {"supplier_name": "Updated Supplier", "is_default": True}
    response = client.patch(update_url, json.dumps(update_payload), content_type="application/json", **headers)
    assert response.status_code == 200
    updated = response.json()
    assert updated["supplier_name"] == "Updated Supplier"
    assert updated["is_default"] is True

    # Creating a second profile as default should clear previous default
    second_payload = {
        "name": "Backup Contacts",
        "company": "Backup LLC",
        "supplier_name": "Backup Supplier",
        "is_default": True,
    }
    response = client.post(create_url, json.dumps(second_payload), content_type="application/json", **headers)
    assert response.status_code == 201
    second_profile = response.json()

    first_profile = ContactProfile.objects.get(pk=profile_id)
    assert first_profile.is_default is False
    assert ContactProfile.objects.get(pk=second_profile["id"]).is_default is True

    # Delete second profile
    delete_url = f"{base_url}/{second_profile['id']}"
    response = client.delete(delete_url, **headers)
    assert response.status_code == 204
    assert not ContactProfile.objects.filter(pk=second_profile["id"]).exists()


@pytest.mark.django_db
def test_contact_profile_access_forbidden_for_guest(sample_team_with_guest_member, guest_api_client):  # noqa: F811
    team = sample_team_with_guest_member.team
    client, token = guest_api_client
    headers = get_api_headers(token)

    list_url = f"/api/v1/workspaces/{team.key}/contact-profiles"
    response = client.get(list_url, **headers)
    assert response.status_code == 403
