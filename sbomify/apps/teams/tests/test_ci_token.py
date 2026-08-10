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


class TestTheResponseIsNotCacheable:
    def test_it_is_marked_no_store(self, client_and_member) -> None:
        """The body is a live credential. Without this a back-navigation or a
        shared proxy could hand it to someone else."""
        client, member = client_and_member

        response = client.post(_url(member))

        assert response["Cache-Control"] == "no-store"


class TestCsrfIsRequired:
    def test_a_post_without_a_csrf_token_mints_nothing(self, sample_team_with_owner_member: Member) -> None:
        """Pinned rather than assumed: this endpoint returns a credential, so a
        middleware or settings change that weakened it should fail here rather
        than be discovered from the outside."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(sample_team_with_owner_member.user)
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )

        response = client.post(_url(sample_team_with_owner_member))

        assert response.status_code == 403
        assert AccessToken.objects.count() == 0


class TestItAuthorizesTheWorkspaceInTheUrl:
    """TeamRoleRequiredMixin reads session["current_team"], so on its own it
    answers whether the caller administers whatever workspace they happen to
    have selected — not the one being minted for.

    A legacy ``role="member"`` row is refused a few layers down by
    ``can("workspace:read")`` inside ``get_team``, so this was closed already.
    It is checked here so that it stays closed for a reason this endpoint owns.
    """

    def test_a_member_of_another_workspace_cannot_mint_for_it(
        self, sample_team_with_owner_member: Member
    ) -> None:
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Team

        user = sample_team_with_owner_member.user
        owned = sample_team_with_owner_member.team
        other = Team.objects.create(name="Another Workspace")
        other.key = number_to_random_token(other.pk)
        other.save(update_fields=["key"])
        Member.objects.create(user=user, team=other, role="member")

        client = Client()
        client.force_login(user)
        # The session names the workspace they *do* own.
        setup_authenticated_client_session(client, owned, user)

        response = client.post(reverse("teams:ci_token", kwargs={"team_key": other.key}))

        assert response.status_code == 403
        assert not AccessToken.objects.filter(team=other).exists()

    def test_an_owner_of_a_second_workspace_still_can(
        self, sample_team_with_owner_member: Member
    ) -> None:
        """The check must not break the legitimate case: minting for a
        workspace you own while another is selected."""
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Team

        user = sample_team_with_owner_member.user
        owned = sample_team_with_owner_member.team
        second = Team.objects.create(name="Second Workspace")
        second.key = number_to_random_token(second.pk)
        second.save(update_fields=["key"])
        Member.objects.create(user=user, team=second, role="owner")

        client = Client()
        client.force_login(user)
        setup_authenticated_client_session(client, owned, user)

        response = client.post(reverse("teams:ci_token", kwargs={"team_key": second.key}))

        assert response.status_code == 200
        assert AccessToken.objects.filter(team=second).count() == 1


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
