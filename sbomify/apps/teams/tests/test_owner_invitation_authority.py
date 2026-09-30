"""Only an owner can make someone an owner, by invitation or on accepting one."""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Invitation, Member, Team


@pytest.fixture
def team(ensure_billing_plans):
    return Team.objects.create(name="Owner Grant Workspace", billing_plan="business")


@pytest.fixture
def make_member(django_user_model, team):
    def make(username, role):
        user = django_user_model.objects.create_user(
            username=username, email=f"{username}@example.com", email_verified=True
        )
        Member.objects.create(team=team, user=user, role=role)
        return user

    return make


def _client_for(team, user):
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


def _invite(client, team, email, role):
    return client.post(reverse("teams:invite_user", kwargs={"team_key": team.key}), {"email": email, "role": role})


def _accept(client, invitation):
    return client.post(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))


@pytest.mark.django_db
class TestIssuingOwnerInvitations:
    def test_admin_cannot_invite_an_owner(self, team, make_member):
        admin = make_member("admin1", "admin")

        response = _invite(_client_for(team, admin), team, "admin1-alt@example.com", "owner")

        assert response.status_code == 200
        assert not Invitation.objects.filter(team=team).exists()

    def test_admin_cannot_invite_themselves_as_owner(self, team, make_member):
        admin = make_member("admin1", "admin")

        _invite(_client_for(team, admin), team, admin.email, "owner")

        assert not Invitation.objects.filter(team=team).exists()

    def test_admin_is_not_offered_the_owner_role(self, team, make_member):
        admin = make_member("admin1", "admin")

        response = _client_for(team, admin).get(reverse("teams:invite_user", kwargs={"team_key": team.key}))

        assert response.status_code == 200
        assert 'value="owner"' not in response.content.decode()
        assert 'value="admin"' in response.content.decode()

    def test_admin_can_still_invite_an_admin(self, team, make_member):
        admin = make_member("admin1", "admin")

        response = _invite(_client_for(team, admin), team, "new-admin@example.com", "admin")

        assert response.status_code == 302
        invitation = Invitation.objects.get(team=team)
        assert invitation.role == "admin"
        assert invitation.invited_by == admin

    def test_owner_can_invite_an_owner(self, team, make_member):
        owner = make_member("owner1", "owner")
        client = _client_for(team, owner)

        assert (
            'value="owner"' in client.get(reverse("teams:invite_user", kwargs={"team_key": team.key})).content.decode()
        )
        response = _invite(client, team, "new-owner@example.com", "owner")

        assert response.status_code == 302
        invitation = Invitation.objects.get(team=team)
        assert invitation.role == "owner"
        assert invitation.invited_by == owner


@pytest.mark.django_db
class TestAcceptingOwnerInvitations:
    def test_owner_issued_invitation_makes_an_existing_admin_owner(self, team, make_member):
        owner = make_member("owner1", "owner")
        admin = make_member("admin1", "admin")
        invitation = Invitation.objects.create(team=team, email=admin.email, role="owner", invited_by=owner)

        _accept(_client_for(team, admin), invitation)

        assert Member.objects.get(team=team, user=admin).role == "owner"

    def test_invitation_without_a_recorded_issuer_does_not_make_an_owner(self, team, make_member):
        make_member("owner1", "owner")
        admin = make_member("admin1", "admin")
        invitation = Invitation.objects.create(team=team, email=admin.email, role="owner")

        _accept(_client_for(team, admin), invitation)

        assert Member.objects.get(team=team, user=admin).role == "admin"
        assert not Invitation.objects.filter(pk=invitation.pk).exists()

    def test_admin_issued_invitation_does_not_make_an_owner(self, team, make_member):
        admin = make_member("admin1", "admin")
        invitation = Invitation.objects.create(team=team, email=admin.email, role="owner", invited_by=admin)

        _accept(_client_for(team, admin), invitation)

        assert Member.objects.get(team=team, user=admin).role == "admin"

    def test_invitation_from_a_demoted_owner_does_not_make_an_owner(self, team, make_member):
        former_owner = make_member("owner1", "owner")
        make_member("owner2", "owner")
        member = make_member("member1", "member")
        invitation = Invitation.objects.create(team=team, email=member.email, role="owner", invited_by=former_owner)
        Member.objects.filter(team=team, user=former_owner).update(role="admin")

        _accept(_client_for(team, member), invitation)

        assert Member.objects.get(team=team, user=member).role == "admin"

    def test_new_member_joins_as_admin_when_the_issuer_is_not_an_owner(self, team, make_member, django_user_model):
        admin = make_member("admin1", "admin")
        newcomer = django_user_model.objects.create_user(
            username="newcomer", email="newcomer@example.com", email_verified=True
        )
        invitation = Invitation.objects.create(team=team, email=newcomer.email, role="owner", invited_by=admin)
        client = Client()
        client.force_login(newcomer)

        _accept(client, invitation)

        assert Member.objects.get(team=team, user=newcomer).role == "admin"

    def test_new_member_joins_as_owner_when_an_owner_issued_it(self, team, make_member, django_user_model):
        owner = make_member("owner1", "owner")
        newcomer = django_user_model.objects.create_user(
            username="newcomer", email="newcomer@example.com", email_verified=True
        )
        invitation = Invitation.objects.create(team=team, email=newcomer.email, role="owner", invited_by=owner)
        client = Client()
        client.force_login(newcomer)

        _accept(client, invitation)

        assert Member.objects.get(team=team, user=newcomer).role == "owner"

    def test_settings_accept_applies_the_same_rule(self, team, make_member, django_user_model):
        admin = make_member("admin1", "admin")
        newcomer = django_user_model.objects.create_user(
            username="newcomer", email="newcomer@example.com", email_verified=True
        )
        invitation = Invitation.objects.create(team=team, email=newcomer.email, role="owner", invited_by=admin)
        client = Client()
        client.force_login(newcomer)

        client.post(reverse("core:accept_user_invitation", kwargs={"invitation_id": invitation.id}))

        assert Member.objects.get(team=team, user=newcomer).role == "admin"

    def test_sign_in_auto_accept_applies_the_same_rule(self, team, make_member, django_user_model):
        from sbomify.apps.teams.signals.handlers import _accept_pending_invitations

        admin = make_member("admin1", "admin")
        newcomer = django_user_model.objects.create_user(
            username="newcomer", email="newcomer@example.com", email_verified=True
        )
        Invitation.objects.create(team=team, email=newcomer.email, role="owner", invited_by=admin)

        _accept_pending_invitations(newcomer)

        assert Member.objects.get(team=team, user=newcomer).role == "admin"


@pytest.mark.django_db
class TestShowingOwnerInvitations:
    def test_admin_invite_page_does_not_describe_the_owner_role(self, team, make_member):
        admin = make_member("admin1", "admin")

        body = (
            _client_for(team, admin).get(reverse("teams:invite_user", kwargs={"team_key": team.key})).content.decode()
        )

        assert "has full control" not in body

    def test_owner_invite_page_describes_the_owner_role(self, team, make_member):
        owner = make_member("owner1", "owner")

        body = (
            _client_for(team, owner).get(reverse("teams:invite_user", kwargs={"team_key": team.key})).content.decode()
        )

        assert "has full control" in body

    def test_members_tab_lists_an_invitation_by_the_role_it_grants(self, team, make_member):
        owner = make_member("owner1", "owner")
        Invitation.objects.create(team=team, email="legacy@example.com", role="owner")
        Invitation.objects.create(team=team, email="real@example.com", role="owner", invited_by=owner)

        response = _client_for(team, owner).get(
            reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "members"})
        )

        invitations = {i["email"]: i["role"] for i in response.context["team"]["invitations"]}
        assert invitations == {"legacy@example.com": "admin", "real@example.com": "owner"}

    def test_invitee_sees_the_role_the_invitation_grants(self, team, make_member, django_user_model):
        from sbomify.apps.teams.queries import get_pending_invitations_for_user

        admin = make_member("admin1", "admin")
        newcomer = django_user_model.objects.create_user(
            username="newcomer", email="newcomer@example.com", email_verified=True
        )
        Invitation.objects.create(team=team, email=newcomer.email, role="owner", invited_by=admin)

        assert [i["role"] for i in get_pending_invitations_for_user(newcomer)] == ["admin"]
