"""The `member` role boundary, end to end.

A member does the day-to-day work and nothing outward-facing or destructive.
These tests are written from both sides deliberately: a role that cannot do its
job is as much a bug as one that can do too much.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.fixtures import (  # noqa: F401
    sample_team_with_member_role,
    sample_team_with_owner_member,
)
from sbomify.apps.teams.models import Member


@pytest.fixture
def member_client(sample_team_with_member_role: Member, ensure_billing_plans):  # noqa: F811
    """A member, in a workspace with a plan.

    The plan matters: creating a product or component is refused with
    NO_BILLING_PLAN before authorization is ever consulted, so without it the
    "member can do the work" tests would pass or fail for the wrong reason.
    """
    client = Client()
    team = sample_team_with_member_role.team
    team.billing_plan = "community"
    team.save(update_fields=["billing_plan"])
    setup_authenticated_client_session(client, team, sample_team_with_member_role.user)
    return client, team


@pytest.mark.django_db
class TestMemberCanDoTheWork:
    """The half that must work, or the role is pointless."""

    def test_member_can_create_a_component(self, member_client):
        client, team = member_client
        response = client.post(
            "/api/v1/components",
            data=json.dumps({"name": "member-made", "component_type": "bom"}),
            content_type="application/json",
        )
        assert response.status_code == 201, response.content

    def test_member_can_edit_a_component(self, member_client):
        client, team = member_client
        component = Component.objects.create(name="editable", team=team)
        response = client.patch(
            f"/api/v1/components/{component.id}",
            data=json.dumps({"name": "renamed-by-member"}),
            content_type="application/json",
        )
        assert response.status_code == 200, response.content
        component.refresh_from_db()
        assert component.name == "renamed-by-member"

    def test_member_can_read_internal_inventory(self, member_client):
        client, team = member_client
        Product.objects.create(name="internal-only", team=team, is_public=False)
        response = client.get("/api/v1/products")
        assert response.status_code == 200
        assert "internal-only" in response.content.decode()

    def test_member_can_reach_the_dashboard(self, member_client):
        client, _team = member_client
        response = client.get(reverse("core:dashboard"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestMemberCannotOverstep:
    """The half that must not work."""

    def test_member_cannot_delete_a_component(self, member_client):
        client, team = member_client
        component = Component.objects.create(name="not-yours-to-delete", team=team)
        response = client.delete(f"/api/v1/components/{component.id}")
        assert response.status_code == 403
        assert Component.objects.filter(id=component.id).exists()

    def test_member_cannot_delete_a_product(self, member_client):
        client, team = member_client
        product = Product.objects.create(name="keep-me", team=team)
        response = client.delete(f"/api/v1/products/{product.id}")
        assert response.status_code == 403
        assert Product.objects.filter(id=product.id).exists()

    def test_member_cannot_publish_a_component(self, member_client):
        """The carve-out: editing is MANAGE, but making it public is ADMINISTER."""
        client, team = member_client
        component = Component.objects.create(
            name="stays-private", team=team, visibility=Component.Visibility.PRIVATE
        )
        response = client.patch(
            f"/api/v1/components/{component.id}",
            data=json.dumps({"visibility": "public"}),
            content_type="application/json",
        )
        assert response.status_code == 403, response.content
        component.refresh_from_db()
        assert component.visibility == Component.Visibility.PRIVATE

    def test_member_cannot_publish_a_product(self, member_client):
        client, team = member_client
        product = Product.objects.create(name="stays-private", team=team, is_public=False)
        response = client.patch(
            f"/api/v1/products/{product.id}",
            data=json.dumps({"is_public": True}),
            content_type="application/json",
        )
        assert response.status_code == 403, response.content
        product.refresh_from_db()
        assert product.is_public is False

    def test_member_sees_only_their_own_settings_sections(self, member_client):
        """Settings admits members, but per-tab filtering decides what they see.

        A member needs the API tokens tab (token creation is workspace-scoped
        only), so the page itself cannot be closed to them. ``visible_tabs()``
        is what keeps them out of General, Trust Center, Billing and the rest.
        """
        from sbomify.apps.teams.settings_tabs import visible_tabs

        client, team = member_client
        tabs = {tab.key for tab in visible_tabs("member", billing_enabled=True)}
        assert tabs == {"tokens", "account"}, tabs

        response = client.get(reverse("teams:team_settings", kwargs={"team_key": team.key}))
        assert response.status_code == 200
        body = response.content.decode()
        assert "Trust Center" not in body
        assert "Branding" not in body

    def test_member_cannot_change_workspace_settings(self, member_client):
        """Reaching the page is not the same as being able to act on it.

        Needs a paid plan and is_public=False to be a real test: the model default
        is True, and Team.save() force-sets is_public back to True when the plan
        cannot be private — so on a community workspace this would assert on state
        the model controls rather than on the guard.
        """
        client, team = member_client
        team.billing_plan = "business"
        team.is_public = False
        team.save(update_fields=["billing_plan", "is_public"])
        team.refresh_from_db()
        assert team.is_public is False, "setup failed: workspace should start private"

        response = client.post(
            reverse("teams:team_settings", kwargs={"team_key": team.key}),
            {"visibility_action": "update", "is_public": ["false", "true"]},
        )
        assert response.status_code in (302, 403)
        team.refresh_from_db()
        assert team.is_public is False, "a member must not be able to publish the workspace"

    def test_member_cannot_invite(self, member_client):
        client, team = member_client
        response = client.post(
            reverse("teams:invite_user", kwargs={"team_key": team.key}),
            {"email": "someone@example.com", "role": "owner"},
        )
        assert response.status_code == 403

    def test_member_cannot_change_the_billing_plan(self, member_client):
        client, team = member_client
        response = client.post(
            reverse("api-1:change_plan"),
            json.dumps({"team_key": team.key, "plan": "community", "billing_period": None}),
            content_type="application/json",
        )
        assert response.status_code == 403
