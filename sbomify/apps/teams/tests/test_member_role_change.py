"""Changing a member's role, from the members tab and over the API.

Owners manage everyone. Admins manage the roles below their own: they can move
members and operators around (up to admin), but cannot touch an owner or another
admin, and cannot make anyone an owner. Guests and trusted-publisher bots are
never changed here, and a workspace always keeps an owner.
"""

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.teams.models import Member, Workspace
from sbomify.apps.teams.permissions import assignable_roles_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def team():
    return Workspace.objects.create(name="Role Change Workspace")


@pytest.fixture
def make_member(django_user_model, team):
    def make(username, role):
        user = django_user_model.objects.create_user(
            username=username, email=f"{username}@example.com", first_name=username.title()
        )
        member = Member(team=team, user=user, role=role)
        # A bot row is only ever written by OIDC provisioning; stand in for it.
        member._is_oidc_bot_provisioning = role == "bot"
        member.save()
        return member

    return make


def _settings_client(member):
    client = Client()
    client.force_login(member.user)
    session = client.session
    session["current_workspace"] = {"key": member.team.key, "name": member.team.name, "role": member.role}
    session.save()
    return client


def _post_role(client, team, target, role):
    url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": team.key, "tab": "members"})
    return client.post(
        url, {"member_role_action": "update", "member_id": target.id, "role": role, "active_tab": "members"}
    )


def _api_client(member, scopes=None):
    encoded = create_personal_access_token(member.user)
    AccessToken.objects.create(user=member.user, encoded_token=encoded, description="roles", scopes=scopes)
    return Client(HTTP_AUTHORIZATION=f"Bearer {encoded}")


def _patch_role(client, team, target_id, role, version="v1"):
    return client.patch(
        f"/api/{version}/workspaces/{team.key}/members/{target_id}",
        {"role": role},
        content_type="application/json",
    )


def _role(member):
    member.refresh_from_db()
    return member.role


class TestOwner:
    @pytest.mark.parametrize("start,end", [("member", "admin"), ("admin", "operator"), ("operator", "owner")])
    def test_owner_can_change_any_role(self, team, make_member, start, end):
        owner = make_member("owner", "owner")
        target = make_member("target", start)

        response = _post_role(_settings_client(owner), team, target, end)

        assert response.status_code == 302
        assert _role(target) == end

    def test_owner_can_demote_another_owner(self, team, make_member):
        owner = make_member("owner", "owner")
        other = make_member("other", "owner")

        _post_role(_settings_client(owner), team, other, "admin")

        assert _role(other) == "admin"

    def test_owner_can_step_down_when_another_owner_remains(self, team, make_member):
        owner = make_member("owner", "owner")
        make_member("other", "owner")

        _post_role(_settings_client(owner), team, owner, "admin")

        assert _role(owner) == "admin"

    def test_only_owner_cannot_step_down(self, team, make_member):
        owner = make_member("owner", "owner")

        response = _post_role(_settings_client(owner), team, owner, "admin")

        assert response.status_code == 302
        assert _role(owner) == "owner"
        messages = [str(m) for m in response.wsgi_request._messages]
        assert any("only owner" in m for m in messages)

    def test_change_invalidates_the_target_session_cache(self, team, make_member):
        owner = make_member("owner", "owner")
        target = make_member("target", "member")
        cache.delete(f"user_teams_invalidate:{target.user_id}")

        _post_role(_settings_client(owner), team, target, "operator")

        assert cache.get(f"user_teams_invalidate:{target.user_id}") is True


class TestAdmin:
    @pytest.mark.parametrize("start,end", [("member", "operator"), ("operator", "member"), ("member", "admin")])
    def test_admin_can_change_roles_below_their_own(self, team, make_member, start, end):
        admin = make_member("admin", "admin")
        target = make_member("target", start)

        _post_role(_settings_client(admin), team, target, end)

        assert _role(target) == end

    @pytest.mark.parametrize("target_role", ["owner", "admin"])
    def test_admin_cannot_change_an_owner_or_another_admin(self, team, make_member, target_role):
        owner = make_member("owner", "owner")
        admin = make_member("admin", "admin")
        target = owner if target_role == "owner" else make_member("target", target_role)

        response = _post_role(_settings_client(admin), team, target, "member")

        assert response.status_code == 302
        assert _role(target) == target_role

    def test_admin_cannot_change_their_own_role(self, team, make_member):
        admin = make_member("admin", "admin")

        _post_role(_settings_client(admin), team, admin, "member")

        assert _role(admin) == "admin"

    def test_admin_cannot_make_an_owner(self, team, make_member):
        admin = make_member("admin", "admin")
        target = make_member("target", "member")

        _post_role(_settings_client(admin), team, target, "owner")

        assert _role(target) == "member"

    def test_admin_cannot_remove_another_admin(self, team, make_member):
        admin = make_member("admin", "admin")
        other = make_member("other", "admin")

        url = reverse("workspaces:team_settings", kwargs={"workspace_key": team.key})
        response = _settings_client(admin).post(url, {"_method": "DELETE", "member_id": other.id})

        assert response.status_code == 302
        assert Member.objects.filter(pk=other.pk).exists()

    def test_owner_can_still_remove_an_admin(self, team, make_member):
        owner = make_member("owner", "owner")
        admin = make_member("admin", "admin")

        url = reverse("workspaces:team_settings", kwargs={"workspace_key": team.key})
        _settings_client(owner).post(url, {"_method": "DELETE", "member_id": admin.id})

        assert not Member.objects.filter(pk=admin.pk).exists()


class TestOutOfReach:
    @pytest.mark.parametrize("actor_role", ["member", "operator"])
    def test_non_admins_are_refused(self, team, make_member, actor_role):
        actor = make_member("actor", actor_role)
        target = make_member("target", "member")

        response = _post_role(_settings_client(actor), team, target, "operator")

        assert response.status_code == 403
        assert _role(target) == "member"

    @pytest.mark.parametrize("target_role", ["guest", "bot"])
    def test_guests_and_bots_are_not_changed(self, team, make_member, target_role):
        owner = make_member("owner", "owner")
        target = make_member("target", target_role)

        _post_role(_settings_client(owner), team, target, "member")

        assert _role(target) == target_role

    @pytest.mark.parametrize("new_role", ["guest", "bot"])
    def test_guest_and_bot_are_not_assignable(self, team, make_member, new_role):
        owner = make_member("owner", "owner")
        target = make_member("target", "member")

        _post_role(_settings_client(owner), team, target, new_role)

        assert _role(target) == "member"

    def test_member_of_another_workspace_is_not_found(self, team, make_member, django_user_model):
        owner = make_member("owner", "owner")
        elsewhere = Workspace.objects.create(name="Elsewhere")
        stranger = Member.objects.create(
            team=elsewhere, user=django_user_model.objects.create_user(username="stranger"), role="member"
        )

        _post_role(_settings_client(owner), team, stranger, "admin")

        assert _role(stranger) == "member"


class TestApi:
    def test_owner_changes_a_role(self, team, make_member):
        owner = make_member("owner", "owner")
        target = make_member("target", "member")

        response = _patch_role(_api_client(owner), team, target.id, "admin")

        assert response.status_code == 200
        assert response.json() == {"id": target.id, "user_id": target.user_id, "role": "admin"}
        assert _role(target) == "admin"

    def test_v2_serves_the_same_endpoint(self, team, make_member):
        owner = make_member("owner", "owner")
        target = make_member("target", "member")

        assert _patch_role(_api_client(owner), team, target.id, "operator", version="v2").status_code == 200
        assert _role(target) == "operator"

    @pytest.mark.parametrize(
        "target_role,new_role,expected",
        [("member", "operator", 200), ("member", "owner", 403), ("admin", "member", 400), ("owner", "member", 400)],
    )
    def test_admin_rules(self, team, make_member, target_role, new_role, expected):
        if target_role != "owner":
            make_member("owner", "owner")
        admin = make_member("admin", "admin")
        target = make_member("target", target_role)

        response = _patch_role(_api_client(admin), team, target.id, new_role)

        assert response.status_code == expected
        assert _role(target) == (new_role if expected == 200 else target_role)

    def test_member_is_forbidden(self, team, make_member):
        member = make_member("member", "member")
        target = make_member("target", "operator")

        assert _patch_role(_api_client(member), team, target.id, "member").status_code == 403

    def test_last_owner_is_refused(self, team, make_member):
        owner = make_member("owner", "owner")

        response = _patch_role(_api_client(owner), team, owner.id, "admin")

        assert response.status_code == 400
        assert _role(owner) == "owner"

    def test_bot_membership_is_not_found(self, team, make_member):
        owner = make_member("owner", "owner")
        bot = make_member("bot", "bot")

        assert _patch_role(_api_client(owner), team, bot.id, "member").status_code == 404

    def test_unknown_role_is_rejected(self, team, make_member):
        owner = make_member("owner", "owner")
        target = make_member("target", "member")

        assert _patch_role(_api_client(owner), team, target.id, "superuser").status_code == 400

    def test_read_only_token_is_refused(self, team, make_member):
        owner = make_member("owner", "owner")
        target = make_member("target", "member")

        response = _patch_role(_api_client(owner, scopes=SCOPE_PRESETS["read_only"]), team, target.id, "admin")

        assert response.status_code == 403
        assert _role(target) == "member"


class TestMembersTab:
    def test_owner_sees_role_options(self, team, make_member):
        owner = make_member("owner", "owner")
        make_member("target", "member")

        url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": team.key, "tab": "members"})
        content = _settings_client(owner).get(url).content.decode()

        assert 'name="member_role_action"' in content
        assert "Make admin" in content
        assert "Make owner" in content

    def test_admin_is_not_offered_owner_or_admin_rows(self, team, make_member):
        make_member("owner", "owner")
        admin = make_member("admin", "admin")
        make_member("other", "admin")

        url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": team.key, "tab": "members"})
        content = _settings_client(admin).get(url).content.decode()

        assert 'name="member_role_action"' not in content

    @pytest.mark.parametrize(
        "actor_role,target_role,is_self,expected",
        [
            ("owner", "member", False, ["owner", "admin", "operator"]),
            ("owner", "owner", True, ["admin", "member", "operator"]),
            ("admin", "member", False, ["admin", "operator"]),
            ("admin", "operator", False, ["admin", "member"]),
            ("admin", "admin", False, []),
            ("admin", "admin", True, []),
            ("admin", "owner", False, []),
            ("owner", "guest", False, []),
            ("owner", "bot", False, []),
            ("member", "operator", False, []),
        ],
    )
    def test_offered_roles(self, actor_role, target_role, is_self, expected):
        assert assignable_roles_for(actor_role, 1, target_role, 1 if is_self else 2) == expected
