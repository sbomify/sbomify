"""Tests for RFC 9116 security.txt generation service and view."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from django.test import RequestFactory

from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact
from sbomify.apps.teams.services.security_txt import generate_security_txt
from sbomify.apps.teams.views.security_txt import SecurityTxtView


def _create_security_contact(team, email: str = "security@example.com") -> ContactProfileContact:
    """Helper to create a security contact for a team's default contact profile."""
    profile = ContactProfile.objects.create(team=team, name="Default", is_default=True)
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Test Corp",
        email="info@test.com",
        is_manufacturer=True,
    )
    return ContactProfileContact.objects.create(
        entity=entity,
        name="Security Team",
        email=email,
        is_security_contact=True,
    )


@pytest.mark.django_db
class TestGenerateSecurityTxtDisabled:
    """Tests for when security.txt generation is disabled."""

    def test_returns_empty_when_config_is_empty(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {}
        team.save(update_fields=["security_txt_config"])

        assert generate_security_txt(team) == ""

    def test_returns_empty_when_disabled(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {"enabled": False}
        team.save(update_fields=["security_txt_config"])

        assert generate_security_txt(team) == ""

    def test_returns_empty_when_enabled_key_missing(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {"policy_url": "https://example.com/vdp"}
        team.save(update_fields=["security_txt_config"])

        assert generate_security_txt(team) == ""


@pytest.mark.django_db
class TestGenerateSecurityTxtNoContact:
    """Tests for when enabled but no security contact exists."""

    def test_returns_empty_without_security_contact(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["security_txt_config"])

        assert generate_security_txt(team) == ""

    def test_returns_empty_when_contact_not_on_default_profile(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["security_txt_config"])

        # Create contact on a non-default profile
        profile = ContactProfile.objects.create(team=team, name="Secondary", is_default=False)
        entity = ContactEntity.objects.create(profile=profile, name="Corp", email="info@corp.com", is_manufacturer=True)
        ContactProfileContact.objects.create(entity=entity, name="Sec", email="sec@corp.com", is_security_contact=True)

        assert generate_security_txt(team) == ""

    def test_returns_empty_when_contact_not_marked_security(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["security_txt_config"])

        profile = ContactProfile.objects.create(team=team, name="Default", is_default=True)
        entity = ContactEntity.objects.create(profile=profile, name="Corp", email="info@corp.com", is_manufacturer=True)
        ContactProfileContact.objects.create(
            entity=entity, name="Regular", email="regular@corp.com", is_security_contact=False
        )

        assert generate_security_txt(team) == ""


@pytest.mark.django_db
class TestGenerateSecurityTxtMinimal:
    """Tests for minimal security.txt output (just Contact + Expires)."""

    def test_generates_contact_and_expires(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["security_txt_config"])
        _create_security_contact(team, "security@example.com")

        result = generate_security_txt(team)

        assert "Contact: mailto:security@example.com" in result
        assert "Expires:" in result

    def test_ends_with_newline(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["security_txt_config"])
        _create_security_contact(team)

        result = generate_security_txt(team)

        assert result.endswith("\n")

    def test_expires_defaults_to_future(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["security_txt_config"])
        _create_security_contact(team)

        result = generate_security_txt(team)

        for line in result.splitlines():
            if line.startswith("Expires:"):
                expires_str = line.split(":", 1)[1].strip()
                expires_dt = datetime.fromisoformat(expires_str)
                assert expires_dt > datetime.now(timezone.utc)
                break
        else:
            pytest.fail("No Expires field found")


@pytest.mark.django_db
class TestGenerateSecurityTxtOptionalFields:
    """Tests for optional RFC 9116 fields."""

    def test_includes_all_optional_fields(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {
            "enabled": True,
            "policy_url": "https://example.com/vdp",
            "encryption_url": "https://example.com/pgp.txt",
            "acknowledgments_url": "https://example.com/thanks",
            "hiring_url": "https://example.com/jobs",
            "preferred_languages": "en, de",
            "canonical_url": "https://example.com/.well-known/security.txt",
        }
        team.save(update_fields=["security_txt_config"])
        _create_security_contact(team, "sec@example.com")

        result = generate_security_txt(team)

        assert "Contact: mailto:sec@example.com" in result
        assert "Policy: https://example.com/vdp" in result
        assert "Encryption: https://example.com/pgp.txt" in result
        assert "Acknowledgments: https://example.com/thanks" in result
        assert "Canonical: https://example.com/.well-known/security.txt" in result
        assert "Hiring: https://example.com/jobs" in result
        assert "Preferred-Languages: en, de" in result
        assert "Expires:" in result

    def test_omits_empty_optional_fields(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {
            "enabled": True,
            "policy_url": "",
            "encryption_url": "",
        }
        team.save(update_fields=["security_txt_config"])
        _create_security_contact(team, "sec@example.com")

        result = generate_security_txt(team)

        assert "Policy:" not in result
        assert "Encryption:" not in result
        assert "Contact: mailto:sec@example.com" in result

    def test_custom_expires_override(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.security_txt_config = {
            "enabled": True,
            "expires": "2027-06-01T00:00:00+00:00",
        }
        team.save(update_fields=["security_txt_config"])
        _create_security_contact(team, "sec@example.com")

        result = generate_security_txt(team)

        assert "Expires: 2027-06-01T00:00:00+00:00" in result


@pytest.mark.django_db
class TestSecurityTxtView:
    """Tests for the /.well-known/security.txt endpoint."""

    def _make_request(self, team=None):
        """Create a GET request with custom_domain_team set."""
        factory = RequestFactory()
        request = factory.get("/.well-known/security.txt")
        if team is not None:
            request.custom_domain_team = team
        return request

    def test_returns_404_when_no_team_resolved(self) -> None:
        request = self._make_request(team=None)
        response = SecurityTxtView.as_view()(request)
        assert response.status_code == 404

    def test_returns_404_when_team_not_public(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.is_public = False
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["is_public", "security_txt_config"])

        request = self._make_request(team=team)
        response = SecurityTxtView.as_view()(request)
        assert response.status_code == 404

    def test_returns_404_when_security_txt_disabled(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.is_public = True
        team.security_txt_config = {"enabled": False}
        team.save(update_fields=["is_public", "security_txt_config"])

        request = self._make_request(team=team)
        response = SecurityTxtView.as_view()(request)
        assert response.status_code == 404

    def test_returns_404_when_no_security_contact(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.is_public = True
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["is_public", "security_txt_config"])

        request = self._make_request(team=team)
        response = SecurityTxtView.as_view()(request)
        assert response.status_code == 404

    def test_returns_200_with_correct_content_type(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        team.is_public = True
        team.security_txt_config = {"enabled": True}
        team.save(update_fields=["is_public", "security_txt_config"])
        _create_security_contact(team, "security@test.com")

        request = self._make_request(team=team)
        response = SecurityTxtView.as_view()(request)

        assert response.status_code == 200
        assert response["Content-Type"] == "text/plain; charset=utf-8"
        assert b"Contact: mailto:security@test.com" in response.content
        assert b"Expires:" in response.content
