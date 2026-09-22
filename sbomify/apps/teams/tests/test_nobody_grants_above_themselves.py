"""An inviter may not hand out a role above their own.

The invite form offered every invitable role to anyone who could reach it, and
the view never compared the role being granted against the inviter's own. So an
admin could invite an owner, at an address of their choosing, and owner is the
one tier admins are deliberately denied: it holds workspace deletion and the
right to remove an owner.

Relational, like the owner-protection rules in check_member_removal: what an
actor may grant depends on what the actor is, which is why it is not a
capability tier in authz.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.forms import InviteUserForm
from sbomify.apps.teams.models import Invitation, Member
from sbomify.apps.teams.permissions import grantable_roles

pytestmark = pytest.mark.django_db


class TestWhatEachRoleMayHandOut:
    def test_an_owner_may_grant_anything_invitable(self) -> None:
        assert [role for role, _ in grantable_roles("owner")] == ["owner", "admin", "member"]

    def test_an_admin_may_not_grant_ownership(self) -> None:
        assert [role for role, _ in grantable_roles("admin")] == ["admin", "member"]

    def test_a_member_may_grant_nothing(self) -> None:
        assert grantable_roles("member") == []

    def test_neither_may_grant_bot(self) -> None:
        """bot is for OIDC binding identities and must never be assignable by a
        human, whatever their role."""
        for actor in ("owner", "admin", "member", None):
            assert "bot" not in [role for role, _ in grantable_roles(actor)]

    def test_neither_may_grant_guest(self) -> None:
        """guest is reached through the trust centre's access request, not by
        invitation."""
        for actor in ("owner", "admin"):
            assert "guest" not in [role for role, _ in grantable_roles(actor)]


class TestTheFormRefusesWhatItDoesNotOffer:
    def test_an_admin_posting_owner_is_invalid(self) -> None:
        """Narrowing the choices is the enforcement, not decoration: a
        ChoiceField refuses anything outside them, so the crafted POST is
        refused by the same line that shortens the dropdown."""
        form = InviteUserForm({"email": "someone@example.test", "role": "owner"}, actor_role="admin")

        assert not form.is_valid()
        assert "role" in form.errors

    def test_an_admin_posting_admin_is_valid(self) -> None:
        form = InviteUserForm({"email": "someone@example.test", "role": "admin"}, actor_role="admin")

        assert form.is_valid(), form.errors

    def test_an_owner_posting_owner_is_valid(self) -> None:
        form = InviteUserForm({"email": "someone@example.test", "role": "owner"}, actor_role="owner")

        assert form.is_valid(), form.errors


class TestTheInviteViewHoldsToIt:
    def _client(self, team, user) -> Client:
        client = Client()
        setup_authenticated_client_session(client, team, user)
        return client

    def test_an_admin_cannot_create_an_owner_invitation(self, team_with_business_plan, guest_user) -> None:
        team = team_with_business_plan
        Member.objects.create(user=guest_user, team=team, role="admin")
        client = self._client(team, guest_user)

        client.post(
            reverse("teams:invite_user", kwargs={"team_key": team.key}),
            {"email": "escalated@example.test", "role": "owner"},
        )

        assert not Invitation.objects.filter(team=team, email="escalated@example.test").exists()

    def test_an_admin_can_still_invite_an_admin(self, team_with_business_plan, guest_user) -> None:
        """The half that proves the guard is a rule rather than a wall."""
        team = team_with_business_plan
        Member.objects.create(user=guest_user, team=team, role="admin")
        client = self._client(team, guest_user)

        client.post(
            reverse("teams:invite_user", kwargs={"team_key": team.key}),
            {"email": "colleague@example.test", "role": "admin"},
        )

        invitation = Invitation.objects.filter(team=team, email="colleague@example.test").first()
        assert invitation is not None
        assert invitation.role == "admin"
