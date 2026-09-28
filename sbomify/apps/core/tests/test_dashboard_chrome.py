"""The shared chrome must follow live capabilities and keep working links."""

import json
import re

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.models import User
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def test_chrome_reflects_demotion_without_waiting_for_fragment_cache(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    member = sample_team_with_owner_member
    workspace = member.team
    setup_authenticated_client_session(client, workspace, sample_user)
    session = client.session
    session["current_team"]["has_completed_wizard"] = True
    session.save()
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    owner_page = client.get(reverse("core:dashboard"))
    assert owner_page.status_code == 200
    assert b'aria-label="Posture"' in owner_page.content
    assert b'aria-label="Plugins"' in owner_page.content
    assert b"Set up your first repository" in owner_page.content
    assert reverse("core:component_new").encode() in owner_page.content
    owner_suggestions = re.search(
        rb'<script id="navbar-search-suggestions" type="application/json">(.*?)</script>', owner_page.content
    )
    assert owner_suggestions
    assert "api key" in {item.get("query") for item in json.loads(owner_suggestions[1])}

    member.role = "member"
    member.save(update_fields=["role"])
    contributor_page = client.get(reverse("core:dashboard"))
    assert contributor_page.status_code == 200
    assert b'aria-label="Posture"' not in contributor_page.content
    assert b'aria-label="Plugins"' not in contributor_page.content
    assert b"Set up your first repository" in contributor_page.content
    assert reverse("core:component_new").encode() in contributor_page.content
    assert b'aria-current="page"' in contributor_page.content
    assert b"<c-" not in contributor_page.content
    member_suggestions = re.search(
        rb'<script id="navbar-search-suggestions" type="application/json">(.*?)</script>', contributor_page.content
    )
    assert member_suggestions
    assert "api key" not in {item.get("query") for item in json.loads(member_suggestions[1])}

    member.role = "guest"
    member.save(update_fields=["role"])
    guest_page = client.get(reverse("core:dashboard"))
    assert guest_page.status_code == 302
    assert guest_page.url != reverse("core:dashboard")


def test_cryptography_is_reachable_from_the_rail(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    """The workspace crypto page lost its only entry point in the prototype
    migration: the Overview quick-actions tile that used to link to it was
    replaced by a creation-only strip, and nothing took its place. The page
    kept working, so only a link check catches it."""
    member = sample_team_with_owner_member
    workspace = member.team
    setup_authenticated_client_session(client, workspace, sample_user)
    session = client.session
    session["current_team"]["has_completed_wizard"] = True
    session.save()
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    destination = reverse("sboms:workspace_crypto", args=[workspace.key]).encode()

    owner_page = client.get(reverse("core:dashboard"))
    assert owner_page.status_code == 200
    assert b'aria-label="Cryptography"' in owner_page.content
    assert destination in owner_page.content

    # WorkspaceCryptoView admits every role but guest, so a contributor keeps it.
    member.role = "member"
    member.save(update_fields=["role"])
    contributor_page = client.get(reverse("core:dashboard"))
    assert contributor_page.status_code == 200
    assert b'aria-label="Cryptography"' in contributor_page.content
    assert destination in contributor_page.content


def test_trends_page_hands_its_filters_to_the_fragment_it_fetches(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    """A bookmarked or shared Trends link opened on the defaults.

    The page fetches its own content, so a filter in the address bar has to
    travel with that fetch. The chart view is not one of them: only the browser
    reads that, and sending it would mean the server rendered it too.
    """
    workspace = sample_team_with_owner_member.team
    setup_authenticated_client_session(client, workspace, sample_user)
    session = client.session
    session["current_team"]["has_completed_wizard"] = True
    session.save()
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)
    fragment = reverse("vulnerability_scanning:vulnerability_trends")

    bare = client.get(reverse("core:dashboard_trends"))
    assert f'hx-get="{fragment}?show_product_filter=true"'.encode() in bare.content

    filtered = client.get(
        reverse("core:dashboard_trends"),
        {"days": "7", "release_id": "", "chart": "severity", "not_a_filter": "x"},
    )
    assert filtered.status_code == 200
    hx_get = re.search(rb'hx-get="([^"]+)"', filtered.content)
    assert hx_get
    assert hx_get[1].decode() == f"{fragment}?show_product_filter=true&amp;release_id=&amp;days=7"
