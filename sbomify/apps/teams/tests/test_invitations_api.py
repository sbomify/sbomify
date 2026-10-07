"""Inviting members over the API: invite, list and revoke, on the members page's rules."""

from datetime import timedelta

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.teams.models import Invitation, Member, Team


@pytest.fixture
def team(ensure_billing_plans):
    return Team.objects.create(name="Invitations API Workspace", billing_plan="business")


@pytest.fixture
def make_member(django_user_model):
    def make(team, username, role):
        user = django_user_model.objects.create_user(username=username, email=f"{username}@example.com")
        Member.objects.create(team=team, user=user, role=role)
        return user

    return make


def _client(user, *, bound_to=None, scopes=None):
    encoded = create_personal_access_token(user)
    AccessToken.objects.create(
        user=user, encoded_token=encoded, description="invitations", team=bound_to, scopes=scopes
    )
    return Client(HTTP_AUTHORIZATION=f"Bearer {encoded}")


def _url(team, invitation_id=None, version="v1"):
    url = f"/api/{version}/workspaces/{team.key}/invitations"
    return url if invitation_id is None else f"{url}/{invitation_id}"


def _invite(client, team, email="new.dev@example.com", role="member", version="v1"):
    return client.post(_url(team, version=version), {"email": email, "role": role}, content_type="application/json")


@pytest.mark.django_db
class TestInvitationsApi:
    def test_owner_invites_lists_and_revokes(self, team, make_member):
        client = _client(make_member(team, "inv-owner", "owner"))

        response = _invite(client, team)

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "new.dev@example.com"
        assert body["role"] == "member"
        assert "token" not in body
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["new.dev@example.com"]

        listed = client.get(_url(team))
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [body["id"]]

        assert client.delete(_url(team, body["id"])).status_code == 204
        assert not Invitation.objects.filter(pk=body["id"]).exists()
        assert client.get(_url(team)).json() == []

    def test_v2_serves_the_same_endpoints(self, team, make_member):
        client = _client(make_member(team, "inv-owner-v2", "owner"))

        response = _invite(client, team, version="v2")

        assert response.status_code == 201
        assert client.get(_url(team, version="v2")).json()[0]["email"] == "new.dev@example.com"

    @pytest.mark.parametrize("role,expected", [("owner", 201), ("admin", 201), ("member", 403), ("guest", 403)])
    def test_only_owners_and_admins_can_invite(self, team, make_member, role, expected):
        client = _client(make_member(team, f"inv-{role}", role))

        assert _invite(client, team).status_code == expected
        assert client.get(_url(team)).status_code == (200 if expected == 201 else 403)

    def test_only_an_owner_can_invite_an_owner(self, team, make_member):
        admin = _client(make_member(team, "inv-admin", "admin"))
        owner = _client(make_member(team, "inv-owner2", "owner"))

        refused = _invite(admin, team, role="owner")
        assert refused.status_code == 403
        assert not Invitation.objects.filter(team=team).exists()

        assert _invite(owner, team, role="owner").status_code == 201

    @pytest.mark.parametrize("role", ["guest", "bot", "superuser"])
    def test_rejects_roles_the_members_page_does_not_offer(self, team, make_member, role):
        client = _client(make_member(team, "inv-owner3", "owner"))

        assert _invite(client, team, role=role).status_code == 400
        assert not Invitation.objects.filter(team=team).exists()

    def test_rejects_an_invalid_address(self, team, make_member):
        client = _client(make_member(team, "inv-owner4", "owner"))

        assert _invite(client, team, email="not-an-address").status_code == 400
        assert mail.outbox == []

    def test_pending_invitations_take_seats(self, team, make_member):
        BillingPlan.objects.filter(key="business").update(max_users=2)
        client = _client(make_member(team, "inv-owner5", "owner"))
        Invitation.objects.create(team=team, email="pending@example.com", role="member")

        response = _invite(client, team)

        assert response.status_code == 403
        assert response.json()["error_code"] == "BILLING_LIMIT_EXCEEDED"
        assert mail.outbox == []

    def test_a_live_invitation_conflicts_and_an_expired_one_is_replaced(self, team, make_member):
        client = _client(make_member(team, "inv-owner6", "owner"))
        existing = Invitation.objects.create(team=team, email="new.dev@example.com", role="member")

        assert _invite(client, team).status_code == 409

        Invitation.objects.filter(pk=existing.pk).update(expires_at=timezone.now() - timedelta(days=1))
        replaced = _invite(client, team)

        assert replaced.status_code == 201
        assert list(Invitation.objects.filter(team=team).values_list("pk", flat=True)) == [replaced.json()["id"]]

    def test_a_read_only_token_cannot_invite_or_list(self, team, make_member):
        client = _client(make_member(team, "inv-owner7", "owner"), scopes=SCOPE_PRESETS["read_only"])

        assert _invite(client, team).status_code == 403
        assert client.get(_url(team)).status_code == 403

    def test_a_token_bound_to_another_workspace_cannot_invite(self, team, make_member):
        owner = make_member(team, "inv-owner8", "owner")
        elsewhere = Team.objects.create(name="Other Workspace", billing_plan="business")
        Member.objects.create(team=elsewhere, user=owner, role="owner")

        assert _invite(_client(owner, bound_to=elsewhere), team).status_code == 403
        assert not Invitation.objects.filter(team=team).exists()

    def test_cannot_revoke_another_workspaces_invitation(self, team, make_member):
        owner = make_member(team, "inv-owner9", "owner")
        elsewhere = Team.objects.create(name="Other Workspace", billing_plan="business")
        theirs = Invitation.objects.create(team=elsewhere, email="theirs@example.com", role="member")

        assert _client(owner).delete(_url(team, theirs.pk)).status_code == 404
        assert Invitation.objects.filter(pk=theirs.pk).exists()
