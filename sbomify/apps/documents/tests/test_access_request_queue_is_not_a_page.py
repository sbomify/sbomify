"""The access-request queue endpoint renders a section, not a page.

Its template extends no base, so a browser sent straight to it got the markup
with no stylesheet, no script and nothing on it that worked. The notification
email pointed its "Review request" button here, so that is what an admin saw
every time they went to review a request. Reported by a pilot customer.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _queue_url(team) -> str:
    return reverse("documents:access_request_queue", kwargs={"team_key": team.key})


def _settings_url(team) -> str:
    return reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "trust-center"})


def test_a_browser_is_sent_to_the_page_that_renders_it(sample_team_with_owner_member: Member) -> None:
    client = Client()
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(_queue_url(sample_team_with_owner_member.team))

    assert response.status_code == 302
    assert response.headers["Location"] == _settings_url(sample_team_with_owner_member.team)


def test_htmx_still_gets_the_section(sample_team_with_owner_member: Member) -> None:
    """The trust-center tab swaps this in, so the guard keys on the header htmx
    always sends rather than on anything about the URL."""
    client = Client()
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(_queue_url(sample_team_with_owner_member.team), headers={"hx-request": "true"})

    assert response.status_code == 200
    assert b"Access requests" in response.content


def test_the_review_button_points_at_a_real_page(sample_team_with_owner_member: Member, guest_user) -> None:
    """What the reporter actually clicked. Sending an admin to the section
    endpoint is sending them to unstyled markup however well the section
    itself renders inside its tab."""
    from django.core import mail

    from sbomify.apps.documents.models import AccessRequest
    from sbomify.apps.documents.services.access_emails import notify_admins_of_access_request

    team = sample_team_with_owner_member.team
    access_request = AccessRequest.objects.create(team=team, user=guest_user)

    mail.outbox.clear()
    notify_admins_of_access_request(access_request, team)

    assert mail.outbox, "no admin was notified"
    body = mail.outbox[0].body + "".join(part for part, _ in mail.outbox[0].alternatives)
    assert _settings_url(team) in body
    # Both parts, and the URL anywhere in either of them: the text part quotes
    # nothing, so a check that only matched a quoted one would pass on the very
    # mail that was reported.
    assert _queue_url(team) not in body
