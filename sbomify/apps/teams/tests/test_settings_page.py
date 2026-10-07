"""Initial settings content, private token data and persisted patch targets."""

import json
from html.parser import HTMLParser

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import User
from sbomify.apps.core.services.dashboard_page import dashboard_cache_key
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import ContactProfile, Member, default_patch_sla_days

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


def test_saving_the_support_period_refreshes_that_form_alone(
    client: Client, sample_team_with_owner_member: Member
) -> None:
    """The saved value becomes the form's new starting point, and only that form
    re-renders: refreshing the whole tab would throw away an unsaved name or
    freshness edit in the card above."""
    workspace = sample_team_with_owner_member.team
    setup_authenticated_client_session(client, workspace, sample_team_with_owner_member.user)
    url = reverse("teams:team_general", args=[workspace.key])

    response = client.post(url, {"action": "update_support_period", "default_support_period_years": "7"})

    trigger = json.loads(response.headers["HX-Trigger"])
    assert "refreshSupportPeriod" in trigger
    assert "refreshTeamGeneral" not in trigger
    # The refresh selects the form alone, so its starting values must be inside it.
    html = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    form = html[html.index('id="support-period-form"') :]
    assert 'id="support-period-fields"' in form[: form.index("</form>")]


def test_saving_the_workspace_card_refreshes_that_card_alone(
    client: Client, sample_team_with_owner_member: Member
) -> None:
    """Refreshing the whole tab after a name or freshness save would throw away an
    unsaved patch-target or support-period edit further down."""
    workspace = sample_team_with_owner_member.team
    setup_authenticated_client_session(client, workspace, sample_team_with_owner_member.user)
    url = reverse("teams:team_general", args=[workspace.key])

    response = client.post(url, {"name": "Renamed workspace", "sbom_freshness_days": "30"})

    trigger = json.loads(response.headers["HX-Trigger"])
    assert "refreshWorkspaceCard" in trigger
    assert "refreshTeamGeneral" not in trigger
    # The refresh selects the card's forms alone, so the starting values must be inside them.
    html = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    form = html[html.index('id="team-general-form"') :]
    assert 'id="team-general-fields"' in form[: form.index("</form>")]


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
    cache_key = dashboard_cache_key(workspace.pk)
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


def test_a_party_renders_its_last_updated_date(client: Client, sample_team_with_owner_member: Member) -> None:
    """The schema carries updated_at as an ISO string.

    The date filter answers "" for anything that is not a date, so handing it
    the string straight through blanked every cell on the tab while the page
    still looked fine.
    """
    workspace = sample_team_with_owner_member.team
    ContactProfile.objects.create(team=workspace, name="Product contacts", is_default=True)
    setup_authenticated_client_session(client, workspace, sample_team_with_owner_member.user)

    response = client.get(reverse("teams:team_settings_tab", args=[workspace.key, "contact-profiles"]))
    payload = response.content.decode()
    profiles = json.loads(payload[payload.index('id="profiles-data"') :].split(">", 1)[1].split("</script>")[0])

    assert profiles
    assert all(profile["updated_display"] for profile in profiles)
    assert all(profile["updated_display"] != profile["updated_at"] for profile in profiles)


class _AncestorsOf(HTMLParser):
    """Records the open elements around the first element whose text is ``needle``."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self, needle: str) -> None:
        super().__init__()
        self.needle = needle
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.found: list[tuple[str, dict[str, str | None]]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.VOID:
            self.stack.append((tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.found is None and data.strip() == self.needle:
            self.found = list(self.stack)


def test_the_nda_card_footer_sits_on_the_card_surface(client: Client, sample_team_with_owner_member: Member) -> None:
    """The card does not clip, and rounds only its direct last child, so a footer
    band inside a nested form painted square corners over the card's curve."""
    workspace = sample_team_with_owner_member.team
    setup_authenticated_client_session(client, workspace, sample_team_with_owner_member.user)

    response = client.get(reverse("teams:team_settings_tab", args=[workspace.key, "trust-center"]))

    parser = _AncestorsOf("Upload NDA")
    parser.feed(response.content.decode())
    assert parser.found is not None
    footer_at = next(
        index
        for index in range(len(parser.found) - 1, -1, -1)
        if "border-t" in (parser.found[index][1].get("class") or "")
    )
    assert "data-surface" in parser.found[footer_at - 1][1]
