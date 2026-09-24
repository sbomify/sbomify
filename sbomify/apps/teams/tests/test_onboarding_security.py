"""Onboarding saves identity and security choices together, without creating inventory."""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper

from sbomify.apps.core.models import Component, Product, User
from sbomify.apps.teams.models import ContactProfile, ContactProfileContact, Member, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_client(client: Client, sample_user: User, sample_team_with_owner_member: Member) -> tuple[Client, Team]:
    workspace = sample_team_with_owner_member.team
    client.force_login(sample_user)
    session = client.session
    session["current_team"] = {"key": workspace.key, "role": "owner", "has_completed_wizard": False}
    session.save()
    return client, workspace


def setup_data(**changes: Any) -> dict[str, Any]:
    return {
        "company_name": "Example Software",
        "contact_name": "Example Author",
        "email": "author@example.com",
        "address": "1 Example Street",
        "security_email": "security@example.com",
        "publish_security_txt": "on",
        "default_support_period_years": "7",
        "mode": "custom",
        "critical": "3",
        "high": "14",
        "medium": "60",
        **changes,
    }


def test_security_setup_is_saved_together(setup_client: tuple[Client, Team], settings: SettingsWrapper) -> None:
    settings.BILLING = False
    client, workspace = setup_client
    response = client.post(reverse("teams:onboarding_wizard"), setup_data())
    assert response.status_code == 302
    workspace.refresh_from_db()
    assert workspace.has_completed_wizard
    assert workspace.default_support_period_years == 7
    assert workspace.patch_sla_days == {"critical": 3, "high": 14, "medium": 60, "low": None}
    contact = ContactProfileContact.objects.get(entity__profile__team=workspace, is_security_contact=True)
    assert contact.email == "security@example.com"
    assert contact.entity.address == "1 Example Street"
    assert workspace.security_txt_config["contact_id"] == contact.pk
    assert workspace.security_txt_config["enabled"] is True
    assert not Product.objects.filter(team=workspace).exists()
    assert not Component.objects.filter(team=workspace).exists()


@pytest.mark.parametrize(
    "invalid",
    [
        {"publish_security_txt": "on", "security_email": ""},
        {"default_support_period_years": "4"},
        {"mode": "custom", "critical": "-1"},
    ],
)
def test_invalid_security_settings_keep_answers_without_partial_save(
    setup_client: tuple[Client, Team], invalid: dict[str, str]
) -> None:
    client, workspace = setup_client
    original_name = workspace.name
    response = client.post(reverse("teams:onboarding_wizard"), setup_data(**invalid))
    assert response.status_code == 200
    assert response.context["wizard_config"]["step"] == "security"
    assert response.context["form"]["company_name"].value() == "Example Software"
    assert response.context["form"]["address"].value() == "1 Example Street"
    workspace.refresh_from_db()
    assert workspace.name == original_name
    assert not workspace.has_completed_wizard
    assert not ContactProfile.objects.filter(team=workspace).exists()


def test_security_contact_does_not_publish_without_opt_in(setup_client: tuple[Client, Team]) -> None:
    client, workspace = setup_client
    response = client.post(reverse("teams:onboarding_wizard"), setup_data(publish_security_txt=""))
    assert response.status_code == 302
    workspace.refresh_from_db()
    assert not workspace.security_txt_config.get("enabled")


def test_support_default_can_be_changed_and_cleared_in_settings(setup_client: tuple[Client, Team]) -> None:
    client, workspace = setup_client
    url = reverse("teams:team_general", args=[workspace.key])
    for value, expected in [("10", 10), ("", None)]:
        response = client.post(url, {"action": "update_support_period", "default_support_period_years": value})
        assert response.status_code == 200
        workspace.refresh_from_db()
        assert workspace.default_support_period_years == expected
    client.post(url, {"action": "update_support_period", "default_support_period_years": "4"})
    workspace.refresh_from_db()
    assert workspace.default_support_period_years is None
