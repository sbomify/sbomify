from __future__ import annotations

import json

import pytest

from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.teams.fixtures import (  # noqa: F401
    sample_contact_profile_with_contacts,
    sample_team_with_admin_member,
    sample_team_with_guest_member,
    sample_team_with_owner_member,
)
from sbomify.apps.teams.models import ContactProfile


@pytest.mark.django_db
def test_contact_profile_crud_with_entities(sample_team_with_owner_member, authenticated_api_client):  # noqa: F811
    """Test CRUD operations using the new entity-based structure."""
    team = sample_team_with_owner_member.team
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    base_url = f"/api/v1/workspaces/{team.key}/contact-profiles"

    # Create profile with entities (new structure)
    payload = {
        "name": "Primary Contacts",
        "entities": [
            {
                "name": "Example Corp",
                "email": "support@example.com",
                "phone": "+1-555-0100",
                "address": "100 Example Avenue",
                "website_urls": ["https://example.com"],
                "is_manufacturer": True,
                "is_supplier": True,
                "is_author": False,
                "contacts": [
                    {"name": "Alice", "email": "alice@example.com", "phone": "555-0101"},
                    {"name": "Bob", "email": "bob@example.com", "phone": "555-0102"},
                ],
            }
        ],
        "is_default": False,
    }

    response = client.post(base_url, json.dumps(payload), content_type="application/json", **headers)
    assert response.status_code == 201
    profile_data = response.json()
    profile_id = profile_data["id"]

    assert ContactProfile.objects.filter(id=profile_id, team=team).exists()
    assert len(profile_data["entities"]) == 1
    assert profile_data["entities"][0]["name"] == "Example Corp"
    assert profile_data["entities"][0]["is_manufacturer"] is True
    assert profile_data["entities"][0]["is_supplier"] is True
    assert len(profile_data["entities"][0]["contacts"]) == 2

    # Verify legacy fields are populated from first entity
    assert profile_data["company"] == "Example Corp"
    assert profile_data["email"] == "support@example.com"

    # List profiles
    response = client.get(base_url, **headers)
    assert response.status_code == 200
    profiles = response.json()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "Primary Contacts"

    # Update entity via legacy fields (backward compatibility)
    update_url = f"{base_url}/{profile_id}"
    update_payload = {"company": "Updated Corp", "is_default": True}
    response = client.patch(update_url, json.dumps(update_payload), content_type="application/json", **headers)
    assert response.status_code == 200
    updated = response.json()
    assert updated["company"] == "Updated Corp"
    assert updated["is_default"] is True
    # Legacy supplier_name and vendor also come from entity name
    assert updated["supplier_name"] == "Updated Corp"

    # Delete profile
    response = client.delete(update_url, **headers)
    assert response.status_code == 204
    assert not ContactProfile.objects.filter(pk=profile_id).exists()


@pytest.mark.django_db
def test_contact_profile_crud_legacy_backward_compatibility(sample_team_with_owner_member, authenticated_api_client):  # noqa: F811
    """Test CRUD using legacy flat fields for backward compatibility."""
    team = sample_team_with_owner_member.team
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    base_url = f"/api/v1/workspaces/{team.key}/contact-profiles"

    # Create profile using legacy flat fields (backward compatibility)
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
        ],
        "is_default": False,
    }

    response = client.post(base_url, json.dumps(payload), content_type="application/json", **headers)
    assert response.status_code == 201
    profile_data = response.json()
    profile_id = profile_data["id"]

    # An entity should be auto-created from legacy fields
    assert len(profile_data["entities"]) == 1
    # Entity name uses priority: company > supplier_name > vendor
    assert profile_data["entities"][0]["name"] == "Example Corp"
    # All role flags are set to True when using legacy fields
    assert profile_data["entities"][0]["is_manufacturer"] is True
    assert profile_data["entities"][0]["is_supplier"] is True
    assert profile_data["entities"][0]["is_author"] is True

    # Legacy fields should be populated
    assert profile_data["company"] == "Example Corp"
    assert profile_data["email"] == "support@example.com"

    # Second profile as default should clear previous default
    second_payload = {
        "name": "Backup Contacts",
        "company": "Backup LLC",
        "is_default": True,
    }
    response = client.post(base_url, json.dumps(second_payload), content_type="application/json", **headers)
    assert response.status_code == 201
    second_profile = response.json()

    first_profile = ContactProfile.objects.get(pk=profile_id)
    assert first_profile.is_default is False
    assert ContactProfile.objects.get(pk=second_profile["id"]).is_default is True


@pytest.mark.django_db
def test_contact_profile_access_allowed_for_guest(sample_team_with_guest_member, authenticated_api_client):  # noqa: F811
    """Guests can view contact profiles but cannot manage them."""
    team = sample_team_with_guest_member.team
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    list_url = f"/api/v1/workspaces/{team.key}/contact-profiles"
    response = client.get(list_url, **headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.django_db
def test_get_contact_profile_success(
    sample_team_with_owner_member,
    sample_contact_profile_with_contacts,
    authenticated_api_client,
):
    team = sample_team_with_owner_member.team
    profile = sample_contact_profile_with_contacts
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    response = client.get(f"/api/v1/workspaces/{team.key}/contact-profiles/{profile.id}", **headers)
    assert response.status_code == 200
    data = response.json()

    # Check structure
    assert data["id"] == profile.id
    assert data["name"] == "Test Profile"
    assert data["is_default"] is False

    # Check entities (new structure)
    assert len(data["entities"]) == 1
    entity = data["entities"][0]
    assert entity["name"] == "Test Company"
    assert entity["email"] == "company@example.com"
    assert entity["is_manufacturer"] is True
    assert entity["is_supplier"] is True
    assert entity["is_author"] is True
    assert len(entity["contacts"]) == 1
    assert entity["contacts"][0]["name"] == "John Doe"
    assert entity["contacts"][0]["email"] == "john@example.com"

    # Check legacy backward-compatible fields (populated from first entity)
    assert data["company"] == "Test Company"
    assert data["supplier_name"] == "Test Company"
    assert data["vendor"] == "Test Company"
    assert data["email"] == "company@example.com"
    assert len(data["contacts"]) == 1
    assert data["contacts"][0]["name"] == "John Doe"


@pytest.mark.django_db
def test_get_contact_profile_admin_access(
    sample_team_with_admin_member,
    sample_contact_profile_with_contacts,
    authenticated_api_client,
):
    team = sample_team_with_admin_member.team
    profile = sample_contact_profile_with_contacts
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    response = client.get(f"/api/v1/workspaces/{team.key}/contact-profiles/{profile.id}", **headers)
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == profile.id
    assert data["name"] == "Test Profile"
    assert len(data["entities"]) == 1
    assert data["entities"][0]["name"] == "Test Company"


@pytest.mark.django_db
def test_get_contact_profile_allowed_for_guest(
    sample_team_with_guest_member,
    sample_contact_profile_with_contacts,
    authenticated_api_client,
):
    """Guests can view contact profiles but cannot manage them."""
    team = sample_team_with_guest_member.team
    profile = sample_contact_profile_with_contacts
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    response = client.get(f"/api/v1/workspaces/{team.key}/contact-profiles/{profile.id}", **headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == profile.id
    assert data["name"] == profile.name


@pytest.mark.django_db
def test_get_contact_profile_not_found(
    sample_team_with_owner_member,
    authenticated_api_client,
):
    team = sample_team_with_owner_member.team
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    response = client.get(f"/api/v1/workspaces/{team.key}/contact-profiles/nonexistent-id", **headers)
    assert response.status_code == 404
    assert response.json() == {
        "detail": "Contact profile not found",
        "error_code": None,
    }


@pytest.mark.django_db
def test_entity_role_validation(sample_team_with_owner_member, authenticated_api_client):
    """Test that entities must have at least one role flag set."""
    team = sample_team_with_owner_member.team
    client, token = authenticated_api_client
    headers = get_api_headers(token)

    base_url = f"/api/v1/workspaces/{team.key}/contact-profiles"

    # Try to create entity with no roles
    payload = {
        "name": "Test Profile",
        "entities": [
            {
                "name": "No Role Corp",
                "email": "norole@example.com",
                "is_manufacturer": False,
                "is_supplier": False,
                "is_author": False,
                "contacts": [],
            }
        ],
    }

    response = client.post(base_url, json.dumps(payload), content_type="application/json", **headers)
    assert response.status_code == 422  # Validation error
