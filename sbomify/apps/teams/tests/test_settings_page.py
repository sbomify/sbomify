"""Initial settings content, private token data and persisted patch targets."""

import json
from html.parser import HTMLParser

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import User
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member, default_patch_sla_days

pytestmark = pytest.mark.django_db


class Elements(HTMLParser):
    def __init__(self, content: bytes) -> None:
        super().__init__()
        self.elements: list[dict[str, str | None]] = []
        self.feed(content.decode())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append(dict(attrs))

    def by_id(self, element_id: str) -> dict[str, str | None]:
        return next(element for element in self.elements if element.get("id") == element_id)


@pytest.mark.parametrize(
    "tab,control",
    [
        ("general", "workspace-name"),
        ("tokens", "tokenGenerationForm"),
        ("branding", "brand-color"),
        ("contact-profiles", "profiles-data"),
    ],
)
def test_initial_and_partial_settings_render_the_active_content(
    client: Client, sample_team_with_owner_member: Member, tab: str, control: str
) -> None:
    membership = sample_team_with_owner_member
    setup_authenticated_client_session(client, membership.team, membership.user)
    url = reverse("teams:team_settings_tab", args=[membership.team.key, tab])
    full = client.get(url)
    partial = client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="settings-content")
    assert full.status_code == partial.status_code == 200
    for response in (full, partial):
        elements = Elements(response.content)
        assert elements.by_id(control)
        assert elements.by_id("settings-content")["hx-history"] == "false"
        assert not any((element.get("hx-trigger") or "").startswith("load") for element in elements.elements)
        current = next(element for element in elements.elements if element.get("data-settings-tab") == tab)
        assert current["aria-current"] == "page"
        assert current["href"] == url
    assert b'id="sidebar"' in full.content
    assert b'id="sidebar"' not in partial.content
    assert "no-store" in partial.headers["Cache-Control"]


def test_tokens_remain_personal_on_full_and_partial_pages(
    client: Client, sample_team_with_owner_member: Member, guest_user: User
) -> None:
    membership = sample_team_with_owner_member
    workspace = membership.team
    setup_authenticated_client_session(client, workspace, membership.user)
    for user, name in ((membership.user, "My pipeline"), (guest_user, "Other pipeline")):
        Member.objects.get_or_create(user=user, team=workspace, defaults={"role": "member"})
        AccessToken.objects.create(user=user, team=workspace, description=name, encoded_token=f"secret-{user.pk}")
    for url_name, args in (
        ("teams:team_settings_tab", [workspace.key, "tokens"]),
        ("teams:team_tokens", [workspace.key]),
    ):
        response = client.get(reverse(url_name, args=args), HTTP_HX_REQUEST="true", HTTP_HX_TARGET="settings-content")
        text = response.content.decode()
        assert "My pipeline" in text
        assert "Other pipeline" not in text
        assert "secret-" not in text
        assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("role,allowed", [("owner", True), ("admin", True), ("member", False), ("guest", False)])
def test_patch_targets_require_workspace_administration(
    client: Client, sample_team_with_owner_member: Member, role: str, allowed: bool
) -> None:
    membership = sample_team_with_owner_member
    membership.role = role
    membership.save(update_fields=["role"])
    workspace = membership.team
    setup_authenticated_client_session(client, workspace, membership.user)
    before = workspace.patch_sla_days.copy()
    response = client.post(
        reverse("teams:team_general", args=[workspace.key]),
        {"action": "update_patch_sla", "mode": "custom", "critical": "0", "high": "14", "medium": "", "low": "3650"},
    )
    workspace.refresh_from_db()
    if allowed:
        assert response.status_code == 200
        assert workspace.patch_sla_days == {"critical": 0, "high": 14, "medium": None, "low": 3650}
        # Saving patch targets must not refresh the unsaved name/freshness form.
        trigger = json.loads(response.headers["HX-Trigger"])
        assert "refreshPatchSLA" in trigger
        assert "refreshTeamGeneral" not in trigger
    else:
        assert response.status_code in (302, 403)
        assert workspace.patch_sla_days == before


@pytest.mark.parametrize("value", ["-1", "3651", "1.5", "invalid"])
def test_invalid_patch_targets_do_not_change_saved_policy(
    client: Client, sample_team_with_owner_member: Member, value: str
) -> None:
    membership = sample_team_with_owner_member
    workspace = membership.team
    setup_authenticated_client_session(client, workspace, membership.user)
    client.post(
        reverse("teams:team_general", args=[workspace.key]),
        {"action": "update_patch_sla", "mode": "custom", "critical": value},
    )
    workspace.refresh_from_db()
    assert workspace.patch_sla_days == default_patch_sla_days()


def test_recommended_targets_restore_defaults_and_invalidate_dashboard(
    client: Client, sample_team_with_owner_member: Member, django_capture_on_commit_callbacks
) -> None:
    membership = sample_team_with_owner_member
    workspace = membership.team
    workspace.patch_sla_days = {"critical": 1, "high": None, "medium": None, "low": None}
    workspace.save(update_fields=["patch_sla_days"])
    setup_authenticated_client_session(client, workspace, membership.user)
    cache_key = f"dashboard-page:v3:{workspace.pk}"
    cache.set(cache_key, {"stale": True})
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("teams:team_general", args=[workspace.key]), {"action": "update_patch_sla", "mode": "recommended"}
        )
    assert response.status_code == 200
    workspace.refresh_from_db()
    assert workspace.patch_sla_days == default_patch_sla_days()
    assert cache.get(cache_key) is None


def test_admin_can_open_access_request_dialogs(client: Client, sample_team_with_owner_member: Member) -> None:
    membership = sample_team_with_owner_member
    membership.role = "admin"
    membership.save(update_fields=["role"])
    workspace = membership.team
    workspace.is_public = True
    workspace.save(update_fields=["is_public"])
    setup_authenticated_client_session(client, workspace, membership.user)
    response = client.get(reverse("teams:team_settings_tab", args=[workspace.key, "trust-center"]))
    elements = Elements(response.content)
    assert elements.by_id("inviteUserForm")
    assert "required" in elements.by_id("company_nda_file")
    assert "disabled" not in elements.by_id("company_nda_file")
    assert not any("x-html" in element for element in elements.elements)
