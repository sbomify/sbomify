"""The short-lived token the CI/CD dialog puts in its command.

The dialog hands the reader one command. Without a token in it they still have
to visit settings, pick a scope and a lifetime, and paste it back — the
configurator the dialog was replaced to avoid.

Minting a credential is not something a page render should do, so this is
POST-only and driven by an explicit click.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member
from sbomify.apps.teams.views.ci_token import CI_TOKEN_LIFETIME_DAYS

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_and_member(sample_team_with_owner_member: Member) -> tuple[Client, Member]:
    client = Client()
    client.force_login(sample_team_with_owner_member.user)
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)
    return client, sample_team_with_owner_member


def _url(member: Member) -> str:
    return reverse("teams:ci_token", kwargs={"team_key": member.team.key})


class TestWhatItMints:
    def test_it_returns_the_token_once(self, client_and_member) -> None:
        client, member = client_and_member

        response = client.post(_url(member))

        assert response.status_code == 200
        assert len(json.loads(response.content)["token"]) > 20

    def test_it_expires_in_seven_days(self, client_and_member) -> None:
        """Viktor's number, and the reason this exists rather than reusing the
        90-day default: a token pasted into a terminal or a screenshare stops
        being a credential within the week."""
        client, member = client_and_member

        client.post(_url(member))

        token = AccessToken.objects.get(user=member.user)
        assert token.expires_at is not None
        expected = timezone.now() + timedelta(days=CI_TOKEN_LIFETIME_DAYS)
        assert abs((token.expires_at - expected).total_seconds()) < 60

    def test_it_can_publish_and_nothing_else(self, client_and_member) -> None:
        """Least privilege for what the wizard does. Notably absent is anything
        that could change settings or delete an artifact."""
        client, member = client_and_member

        client.post(_url(member))

        scopes = set(AccessToken.objects.get(user=member.user).scopes or [])
        assert scopes == {"artifact:publish", "release:read", "release:create", "release:tag"}
        assert not any(s.endswith((":delete", ":administer")) for s in scopes)

    def test_it_is_scoped_to_the_workspace(self, client_and_member) -> None:
        client, member = client_and_member

        client.post(_url(member))

        assert AccessToken.objects.get(user=member.user).team_id == member.team.id

    def test_it_is_named_so_it_can_be_found_and_revoked(self, client_and_member) -> None:
        client, member = client_and_member

        client.post(_url(member))

        assert AccessToken.objects.get(user=member.user).description.startswith("CI/CD setup")


class TestWhenItRefuses:
    def test_a_get_mints_nothing(self, client_and_member) -> None:
        """The defect this shape prevents: a credential created by navigation,
        a prefetch, or anything that follows a link."""
        client, member = client_and_member

        response = client.get(_url(member))

        assert response.status_code == 405
        assert AccessToken.objects.count() == 0

    def test_an_anonymous_caller_mints_nothing(self) -> None:
        from sbomify.apps.teams.models import Team

        team = Team.objects.create(name="Someone Else's", key="strangerkey")

        response = Client().post(reverse("teams:ci_token", kwargs={"team_key": team.key}))

        assert response.status_code in (302, 403)
        assert AccessToken.objects.count() == 0

    def test_a_guest_mints_nothing(self, client_and_member) -> None:
        """Token management is owner/admin, and this is token management."""
        client, member = client_and_member
        Member.objects.filter(pk=member.pk).update(role="guest")

        response = client.post(_url(member))

        assert response.status_code != 200
        assert AccessToken.objects.count() == 0


class TestOnePerClick:
    def test_two_posts_make_two_tokens(self, client_and_member) -> None:
        """Recorded rather than prevented: the button guards the double-click on
        the client, and the endpoint stays a plain mint so a deliberate second
        request is honoured. If that ever needs bounding it belongs in a rate
        limit, not in a surprise here."""
        client, member = client_and_member

        client.post(_url(member))
        client.post(_url(member))

        assert AccessToken.objects.count() == 2
