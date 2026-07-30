"""The plugins summary fragment must not be reachable as a page.

It renders a template that extends no base, so a direct visit served a naked
partial: no head, no title, no CSS, no nav. It returns 200, so uptime checks
pass and only a title assertion catches it.

Scoped to this one view. The vulnerability-trends fragment has the same shape
but a whole test class exercises it directly, so whether it should 404 needs a
decision rather than a patch — see issue #1271.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

pytestmark = pytest.mark.django_db


def test_a_direct_visit_is_not_a_page(client: Client, sample_team_with_owner_member):
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(reverse("plugins:plugins_summary"))

    assert response.status_code == 404


def test_htmx_still_gets_the_fragment(client: Client, sample_team_with_owner_member):
    """The guard keys on the header htmx always sends, so the plugins page that
    swaps this in is unaffected."""
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(reverse("plugins:plugins_summary"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200


def test_the_plugins_page_still_asks_for_the_fragment():
    """Guards the regression the 404 could hide: if the page stopped including
    the fragment, the 404 would be masking a broken page rather than a non-page.

    Asserted against the template because a fresh test user has no data and is
    redirected to onboarding before reaching it.
    """
    from django.template.loader import get_template

    source = get_template("plugins/plugins_page.html.j2").template.source

    assert "plugins:plugins_summary" in source
    assert "hx-get" in source


@pytest.mark.parametrize("header", ["false", "1", "yes", ""])
def test_a_non_true_hx_request_header_does_not_bypass_the_guard(client: Client, sample_team_with_owner_member, header):
    """A bare truthiness check would let HX-Request: false through."""
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(reverse("plugins:plugins_summary"), HTTP_HX_REQUEST=header)

    assert response.status_code == 404
