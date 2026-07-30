"""Fragment views must not be reachable as pages.

It renders a template that extends no base, so a direct visit served a naked
partial: no head, no title, no CSS, no nav. It returns 200, so uptime checks
pass and only a title assertion catches it.

Covers both fragment views. Neither is linked as a page: their host templates
carry hx-get references and no hrefs.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

pytestmark = pytest.mark.django_db

FRAGMENTS = ["plugins:plugins_summary", "vulnerability_scanning:vulnerability_trends"]


@pytest.mark.parametrize("view_name", FRAGMENTS)
def test_a_direct_visit_is_not_a_page(client: Client, sample_team_with_owner_member, view_name):
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(reverse(view_name))

    assert response.status_code == 404


@pytest.mark.parametrize("view_name", FRAGMENTS)
def test_htmx_still_gets_the_fragment(client: Client, sample_team_with_owner_member, view_name):
    """The guard keys on the header htmx always sends, so the plugins page that
    swaps this in is unaffected."""
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(reverse(view_name), HTTP_HX_REQUEST="true")

    assert response.status_code == 200


def test_the_host_pages_still_ask_for_their_fragments():
    """Guards the regression the 404 could hide: if the page stopped including
    the fragment, the 404 would be masking a broken page rather than a non-page.

    Asserted against the template because a fresh test user has no data and is
    redirected to onboarding before reaching it.
    """
    from django.template.loader import get_template

    for template, view_name in [
        ("plugins/plugins_page.html.j2", "plugins:plugins_summary"),
        ("core/dashboard.html.j2", "vulnerability_scanning:vulnerability_trends"),
    ]:
        source = get_template(template).template.source
        assert view_name in source, template
        assert "hx-get" in source, template


@pytest.mark.parametrize("view_name", FRAGMENTS)
@pytest.mark.parametrize("header", ["false", "1", "yes", ""])
def test_a_non_true_hx_request_header_does_not_bypass_the_guard(
    client: Client, sample_team_with_owner_member, header, view_name
):
    """A bare truthiness check would let HX-Request: false through."""
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(reverse(view_name), HTTP_HX_REQUEST=header)

    assert response.status_code == 404
