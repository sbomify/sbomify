# skip_file  # nosec
from __future__ import annotations

import json
import os
from datetime import timedelta
from urllib.parse import urlencode

import django.contrib.messages as django_messages
import pytest
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse, HttpResponseRedirect
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.shared_fixtures import (
    get_api_headers, setup_authenticated_client_session,
    team_with_business_plan, team_with_community_plan)
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.apis import _private_workspace_allowed
from sbomify.apps.teams.fixtures import (guest_user, sample_team,  # noqa: F401
                                         sample_team_with_admin_member,
                                         sample_team_with_guest_member,
                                         sample_team_with_owner_member,
                                         sample_user)
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.schemas import BrandingInfo
from sbomify.apps.teams.templatetags.teams import user_workspaces
from sbomify.apps.teams.utils import (compute_user_teams_checksum,
                                      create_user_team_and_subscription,
                                      get_user_teams,
                                      update_user_teams_session)


@pytest.fixture
def community_plan() -> BillingPlan:
    """Free community plan fixture."""
    plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan for small teams",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 1,
            "stripe_product_id": None,
            "stripe_price_monthly_id": None,
            "stripe_price_annual_id": None,
        }
    )
    return plan


@pytest.mark.django_db
def test_new_user_default_team_get_created(sample_user: AbstractBaseUser):  # noqa: F811
    client = Client()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )
    membership = Member.objects.filter(user=sample_user).first()
    assert membership.team.name == "Test's Workspace"
    assert membership.team.key is not None  # nosec


@pytest.mark.django_db
def test_update_user_teams_session_skips_when_checksum_matches(sample_team_with_owner_member: Member):  # noqa: F811
    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()

    user = sample_team_with_owner_member.user
    # First call populates session
    first_teams = update_user_teams_session(request, user)
    first_timestamp = request.session.get("user_teams_checked_at")
    request.session.modified = False  # reset flag

    # Second call should skip data update but still refresh the timestamp for TTL
    result = update_user_teams_session(request, user)

    assert result == first_teams
    assert request.session["user_teams"] == first_teams
    assert request.session["user_teams_version"] == compute_user_teams_checksum(first_teams)
    # Session is modified because timestamp is updated (for TTL reset), but data is unchanged
    assert request.session.modified is True
    assert request.session.get("user_teams_checked_at") is not None
    assert request.session.get("user_teams_checked_at") >= first_timestamp


@pytest.mark.django_db
def test_user_workspaces_refreshes_when_ttl_expires(sample_team_with_owner_member: Member):  # noqa: F811
    request = RequestFactory().get("/")
    request.user = sample_team_with_owner_member.user  # Authenticate request
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()

    user = sample_team_with_owner_member.user
    context = {"request": request}

    # Seed stale data with an old timestamp and mismatched checksum
    request.session["user_teams"] = {"stale": {"id": 1}}
    request.session["user_teams_version"] = "old"
    request.session["user_teams_checked_at"] = (timezone.now() - timedelta(seconds=400)).isoformat()
    request.session.save()

    teams = get_user_teams(user)

    refreshed = user_workspaces(context)

    assert refreshed == teams
    assert request.session["user_teams"] == teams
    assert request.session["user_teams_version"] == compute_user_teams_checksum(teams)


@pytest.mark.django_db
def test_teams_dashboard_only_accessible_when_logged_in(
    sample_user: AbstractBaseUser,  # noqa: F811
):
    client = Client()

    uri = reverse("teams:teams_dashboard")
    response: HttpResponse = client.get(uri)

    assert response.status_code == 302  # nosec
    assert response.url.startswith(settings.LOGIN_URL)  # nosec

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == uri


@pytest.mark.django_db
def test_team_creation(sample_user: AbstractBaseUser):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    uri = reverse("teams:teams_dashboard")
    form_data = urlencode({"_method": "POST", "name": "New Test Team"})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    team = Team.objects.filter(name="New Test Team").first()
    assert team is not None  # nosec
    assert team.key is not None  # nosec
    assert len(team.key) > 0  # nosec

    assert response.status_code == 302
    assert response.url == reverse("teams:switch_team", kwargs={"team_key": team.key})

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert messages[0].message == "Workspace New Test Team created successfully"



@pytest.mark.django_db
def test_only_logged_in_users_are_allowed_to_switch_teams(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    client = Client()
    uri = reverse("teams:switch_team", kwargs={"team_key": sample_team_with_owner_member.team.key})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")


@pytest.mark.django_db
def test_only_owners_are_allowed_to_access_team_details(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    from sbomify.apps.core.tests.shared_fixtures import \
        setup_authenticated_client_session

    client = Client()

    # User not logged in
    uri = reverse("teams:team_details", kwargs={"team_key": sample_team_with_owner_member.team.key})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)

    # Set up authenticated client session with proper team context
    setup_authenticated_client_session(
        client,
        sample_team_with_owner_member.team,
        sample_team_with_owner_member.user
    )

    response: HttpResponse = client.get(uri)

    # team_details now redirects to team_settings for unified interface
    assert response.status_code == 302
    assert response.url == reverse("teams:team_settings", kwargs={"team_key": sample_team_with_owner_member.team.key})


@pytest.mark.django_db
def test_non_owners_cannot_access_team_details(sample_team_with_guest_member: Member):  # noqa: F811
    client = Client()

    # User not logged in
    uri = reverse("teams:team_details", kwargs={"team_key": sample_team_with_guest_member.team.key})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    # Set up session data for guest user
    session = client.session
    session["current_team"] = {"key": sample_team_with_guest_member.team.key}
    session["user_teams"] = {
        sample_team_with_guest_member.team.key: {
            "role": "guest",
            "name": sample_team_with_guest_member.team.name
        }
    }
    session.save()

    response: HttpResponse = client.get(uri)

    assert response.status_code == 403


@pytest.mark.django_db
def test_set_default_team(sample_team_with_owner_member: Member):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    uri = reverse("teams:teams_dashboard")
    form_data = urlencode({"_method": "PATCH", "key": sample_team_with_owner_member.team.key})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 302
    assert response.url == reverse("teams:teams_dashboard")

    membership = Member.objects.filter(
        user_id=sample_team_with_owner_member.user_id, team_id=sample_team_with_owner_member.team_id
    ).first()

    assert membership.is_default_team is True


@pytest.mark.django_db
def test_delete_team(sample_user: AbstractBaseUser):
    """Test deleting a team"""
    # Create a default team first
    default_team = Team.objects.create(name="Default Team")
    default_team.key = number_to_random_token(default_team.pk)
    default_team.save()

    default_owner = Member.objects.create(team=default_team, user=sample_user, role="owner", is_default_team=True)

    # Create a team to delete
    team = Team.objects.create(name="Temporary Test Team")
    team.key = number_to_random_token(team.pk)
    team.save()

    owner = Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=False)

    # Set up session data
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )
    session = client.session
    session["user_teams"] = {
        default_team.key: {"role": "owner", "name": default_team.name, "is_default_team": True},
        team.key: {"role": "owner", "name": team.name, "is_default_team": False}
    }
    session.save()

    # Try to delete the non-default team
    uri = reverse("teams:teams_dashboard")
    form_data = urlencode({"_method": "DELETE", "key": team.key})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    # Check redirect to teams dashboard
    assert response.status_code == 302
    assert response.url == reverse("teams:teams_dashboard")

    # Verify team is deleted
    assert not Team.objects.filter(pk=team.pk).exists()

    # Verify member is deleted (due to CASCADE)
    assert not Member.objects.filter(pk=owner.pk).exists()

    # Verify default team still exists
    assert Team.objects.filter(pk=default_team.pk).exists()

    # Check success message
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert str(messages[0]) == f"Workspace {team.name} has been deleted"


@pytest.mark.django_db
def test_delete_team_not_owner(sample_user: AbstractBaseUser):  # noqa: F811
    """Test deleting a team without owner permissions fails"""
    # Create a team with a non-owner member
    team = Team.objects.create(name="Test Team")
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=sample_user, role="admin")

    # Set up session data
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )
    session = client.session
    session["user_teams"] = {
        team.key: {"role": "admin", "name": team.name}
    }
    session.save()

    # Try to delete the team
    uri = reverse("teams:teams_dashboard")
    form_data = urlencode({"_method": "DELETE", "key": team.key})
    response = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 302

    # Verify team still exists
    assert Team.objects.filter(pk=team.pk).exists()

    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert "Membership not found" in str(messages[0])


@pytest.mark.django_db
def test_only_owners_are_allowed_to_open_team_invitation_form_view(sample_team: Team):  # noqa: F811
    client = Client()

    # User not logged in - should redirect to login
    uri = reverse("teams:invite_user", kwargs={"team_key": sample_team.key})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)


@pytest.mark.django_db
def test_team_invitation_form_view(sample_team_with_owner_member: Member):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    uri = reverse("teams:invite_user", kwargs={"team_key": sample_team_with_owner_member.team.key})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert f'action="{uri}"' in response.content.decode("utf-8")


@pytest.mark.django_db
def test_only_owners_are_allowed_to_send_invitation(sample_team: Team):  # noqa: F811
    client = Client()

    # User not logged in - should redirect to login
    uri = reverse("teams:invite_user", kwargs={"team_key": sample_team.key})
    # Guest role is no longer available in invite form - use admin instead
    form_data = urlencode({"email": "admin@example.com", "role": "admin"})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)


@pytest.mark.django_db
def test_team_invitation(sample_team_with_owner_member: Member):  # noqa: F811
    from sbomify.apps.billing.models import BillingPlan

    client = Client()

    # Set up a billing plan that allows multiple users
    billing_plan, created = BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business Plan",
            "description": "Business Plan Description",
            "max_users": 10,
            "max_products": 100,
            "max_projects": 100,
            "max_components": 1000,
        }
    )
    sample_team_with_owner_member.team.billing_plan = billing_plan.key
    sample_team_with_owner_member.team.save()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    # Set up session data for owner user
    session = client.session
    session["current_team"] = {"key": sample_team_with_owner_member.team.key}
    session["user_teams"] = {
        sample_team_with_owner_member.team.key: {
            "role": "owner",
            "name": sample_team_with_owner_member.team.name
        }
    }
    session.save()

    uri = reverse("teams:invite_user", kwargs={"team_key": sample_team_with_owner_member.team.key})
    # Guest role is no longer available in invite form - use admin instead
    form_data = urlencode({"email": "admin@example.com", "role": "admin"})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 302

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert messages[0].message == "Invite sent to admin@example.com"

    invitations = Invitation.objects.filter(email="admin@example.com").all()

    assert len(invitations) == 1
    assert invitations[0].team == sample_team_with_owner_member.team
    assert invitations[0].role == "admin"
    assert invitations[0].has_expired is False


@pytest.mark.django_db
def test_accept_invitation(
    sample_team_with_owner_member: Member,  # noqa: F811
    django_user_model,
):
    test_team_invitation(sample_team_with_owner_member)

    invitation = Invitation.objects.filter(email="admin@example.com").first()
    assert invitation is not None

    # Create user with matching email
    django_user_model.objects.create_user(
        username="admin_user",
        email="admin@example.com",
        password="adminpass",
    )

    # accept_invite
    client = Client()
    uri = reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)})
    assert client.login(username="admin_user", password="adminpass")  # nosec B106

    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert messages[0].message.startswith("You have joined")


@pytest.mark.django_db
def test_accept_invitation_sets_default_team_and_session(django_user_model, community_plan):
    invited_user = django_user_model.objects.create_user(
        username="invited-user",
        email="invited-user@example.com",
        password="secret",
    )
    team = Team.objects.create(name="Invited Workspace")
    invitation = Invitation.objects.create(team=team, email=invited_user.email, role="admin")

    client = Client()
    assert client.login(username="invited-user", password="secret")

    response: HttpResponse = client.get(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))
    assert response.status_code == 302

    membership = Member.objects.get(user=invited_user, team=team)
    assert membership.is_default_team is True

    session = client.session
    assert session["current_team"]["key"] == team.key
    assert session["current_team"]["role"] == invitation.role
    assert session["user_teams"][team.key]["role"] == invitation.role
    assert session["user_teams"][team.key]["is_default_team"] is True


@pytest.mark.django_db
def test_skip_auto_workspace_creation_for_invited_user(django_user_model, community_plan):
    invited_user = django_user_model.objects.create_user(
        username="pending-invite-user",
        email="pending-invite@example.com",
        password="secret",
    )
    team = Team.objects.create(name="Host Workspace")
    Invitation.objects.create(team=team, email=invited_user.email, role="guest")

    created_team = create_user_team_and_subscription(invited_user)

    assert created_team is None
    assert Member.objects.filter(user=invited_user).count() == 0


@pytest.mark.django_db
def test_pending_invitation_auto_accept_on_login(django_user_model, community_plan):
    invited_user = django_user_model.objects.create_user(
        username="login-invite-user",
        email="login-invite@example.com",
        password="secret",
    )
    team = Team.objects.create(name="Invited Team")
    Invitation.objects.create(team=team, email=invited_user.email, role="guest")

    client = Client()
    assert client.login(username="login-invite-user", password="secret")

    # Session should now reflect the joined workspace
    session = client.session
    assert session["current_team"]["key"] == team.key
    assert session["current_team"]["role"] == "guest"

    membership = Member.objects.get(user=invited_user, team=team)
    assert membership.is_default_team is True
    assert not Invitation.objects.filter(email=invited_user.email, team=team).exists()


@pytest.mark.django_db
def test_accept_invitation_updates_existing_member_role(django_user_model, community_plan):
    """Test that accepting an invitation updates existing membership role."""
    # Create a user with existing guest membership (simulating access request approval)
    user = django_user_model.objects.create_user(
        username="existing-guest-user",
        email="existing-guest@example.com",
        password="secret",
    )
    team = Team.objects.create(name="Test Workspace")
    
    # Create existing guest membership (as if from access request)
    existing_membership = Member.objects.create(
        user=user,
        team=team,
        role="guest",
        is_default_team=True,
    )
    assert existing_membership.role == "guest"
    
    # Create an admin invitation for the same user
    invitation = Invitation.objects.create(team=team, email=user.email, role="admin")
    
    client = Client()
    assert client.login(username="existing-guest-user", password="secret")
    
    # Setup session with existing membership
    setup_authenticated_client_session(client, team, user)
    
    # Accept the invitation
    response: HttpResponse = client.get(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))
    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")
    
    # Verify membership role was updated
    existing_membership.refresh_from_db()
    assert existing_membership.role == "admin"
    
    # Verify session was updated with new role
    session = client.session
    assert session["current_team"]["key"] == team.key
    assert session["current_team"]["role"] == "admin"
    assert session["user_teams"][team.key]["role"] == "admin"
    
    # Verify invitation was deleted
    assert not Invitation.objects.filter(id=invitation.id).exists()
    
    # Verify success message indicates role update
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert "updated to admin" in messages[0].message


@pytest.mark.django_db
def test_accept_invitation_removes_access_requests_when_guest_upgraded(django_user_model, community_plan):
    """Test that access requests (both pending and approved) are removed when a guest user is upgraded to admin/owner."""
    from sbomify.apps.documents.access_models import AccessRequest
    from django.utils import timezone
    
    # Create a user with existing guest membership (from access request)
    user = django_user_model.objects.create_user(
        username="guest-upgrade-user",
        email="guest-upgrade@example.com",
        password="secret",
    )
    team = Team.objects.create(name="Test Workspace")
    
    # Create an admin user to approve the request
    admin_user = django_user_model.objects.create_user(
        username="admin-approver",
        email="admin-approver@example.com",
        password="secret",
    )
    Member.objects.create(user=admin_user, team=team, role="admin", is_default_team=False)
    
    # Create existing guest membership (as if from access request approval)
    existing_membership = Member.objects.create(
        user=user,
        team=team,
        role="guest",
        is_default_team=True,
    )
    
    # Create an approved access request for this user (unique constraint: one per user per team)
    approved_request = AccessRequest.objects.create(
        team=team,
        user=user,
        status=AccessRequest.Status.APPROVED,
        decided_by=admin_user,
        decided_at=timezone.now(),
    )
    
    # Verify approved request exists
    assert AccessRequest.objects.filter(team=team, user=user, status=AccessRequest.Status.APPROVED).count() == 1
    assert AccessRequest.objects.filter(team=team, user=user).count() == 1
    
    # Create an admin invitation for the same user
    invitation = Invitation.objects.create(team=team, email=user.email, role="admin")
    
    client = Client()
    assert client.login(username="guest-upgrade-user", password="secret")
    setup_authenticated_client_session(client, team, user)
    
    # Accept the invitation
    response: HttpResponse = client.get(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))
    assert response.status_code == 302
    
    # Verify membership role was updated
    existing_membership.refresh_from_db()
    assert existing_membership.role == "admin"
    
    # Verify approved access request was removed from "Approved Requests"
    assert AccessRequest.objects.filter(team=team, user=user).count() == 0
    assert AccessRequest.objects.filter(team=team, user=user, status=AccessRequest.Status.APPROVED).count() == 0
    assert not AccessRequest.objects.filter(id=approved_request.id).exists()


@pytest.mark.django_db
def test_accept_invitation_no_role_change_when_same_role(django_user_model, community_plan):
    """Test that accepting an invitation with same role doesn't show update message."""
    user = django_user_model.objects.create_user(
        username="same-role-user",
        email="same-role@example.com",
        password="secret",
    )
    team = Team.objects.create(name="Test Workspace")
    
    # Create existing admin membership
    existing_membership = Member.objects.create(
        user=user,
        team=team,
        role="admin",
        is_default_team=True,
    )
    
    # Create an admin invitation (same role)
    invitation = Invitation.objects.create(team=team, email=user.email, role="admin")
    
    client = Client()
    assert client.login(username="same-role-user", password="secret")
    setup_authenticated_client_session(client, team, user)
    
    # Accept the invitation
    response: HttpResponse = client.get(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))
    assert response.status_code == 302
    
    # Verify membership role unchanged
    existing_membership.refresh_from_db()
    assert existing_membership.role == "admin"
    
    # Verify message indicates already joined (not updated)
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert "already joined" in messages[0].message.lower()


@pytest.mark.django_db
def test_accept_invitation_workspace_full_status_page(django_user_model):
    owner = django_user_model.objects.create_user(
        username="capacity-owner",
        email="capacity-owner@example.com",
        password="secret",
    )
    invited_user = django_user_model.objects.create_user(
        username="capacity-guest",
        email="capacity-guest@example.com",
        password="secret",
    )

    team = Team.objects.create(name="Capacity Limited Workspace")
    Member.objects.create(user=owner, team=team, role="owner", is_default_team=True)
    invitation = Invitation.objects.create(team=team, email=invited_user.email, role="guest")

    client = Client()
    assert client.login(username="capacity-guest", password="secret")

    response: HttpResponse = client.get(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))

    assert response.status_code == 403
    assert any(t.name == "teams/workspace_availability.html.j2" for t in response.templates)

    availability = response.context["availability"]
    assert availability["plan_name"] == Team.Plan.COMMUNITY.label
    assert availability["member_limit"] == 1
    assert availability["current_members"] == 1


@pytest.mark.django_db
def test_delete_membership(
    sample_team_with_owner_member: Member,  # noqa: F811
    django_user_model,
):
    test_accept_invitation(sample_team_with_owner_member, django_user_model)

    # Get the invited user that was created in test_accept_invitation
    invited_user = django_user_model.objects.get(email="admin@example.com")
    membership = Member.objects.filter(
        user_id=invited_user.id, team_id=sample_team_with_owner_member.team_id
    ).first()
    assert membership is not None

    uri = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})

    client = Client()

    # Admin user should not be able to remove their own membership (only owners can delete memberships)
    assert client.login(username="admin_user", password="adminpass")  # nosec B106

    # Set up session data for admin user
    session = client.session
    session["current_team"] = {"key": membership.team.key}
    session["user_teams"] = {
        membership.team.key: {"role": "admin", "name": membership.team.name}
    }
    session.save()

    response: HttpResponse = client.get(uri)
    assert response.status_code == 403

    # Owner user should be able to delete the membership
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    # Set up session data for owner user
    session = client.session
    session["current_team"] = {"key": membership.team.key}
    session["user_teams"] = {
        membership.team.key: {"role": "owner", "name": membership.team.name}
    }
    session.save()

    response: HttpResponse = client.get(uri)
    assert response.status_code == 302

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    # When removing a user from their last workspace, a new personal workspace is created
    assert (
        messages[0].message
        == f"Member {membership.user.username} removed from workspace. A new personal workspace has been created for them."
    )
    with pytest.raises(Member.DoesNotExist):
        Member.objects.get(pk=membership.id)


@pytest.mark.django_db
def test_deleting_last_owner_of_team_is_not_allowed(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    client = Client()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    uri = reverse(
        "teams:team_membership_delete", kwargs={"membership_id": sample_team_with_owner_member.id}
    )

    response: HttpResponse = client.get(uri)

    assert response.status_code == HttpResponseRedirect.status_code
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert messages[0].level == django_messages.WARNING
    assert (
        messages[0].message
        == "Cannot delete the only owner of the team. Please assign another owner first."
    )


@pytest.mark.django_db
def test_delete_invitation(sample_team_with_owner_member: Member):  # noqa: F811
    test_team_invitation(sample_team_with_owner_member)

    # accept_invite
    client = Client()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    invitation = Invitation.objects.filter(email="admin@example.com").first()
    assert invitation is not None
    uri = reverse("teams:team_invitation_delete", kwargs={"invitation_id": invitation.id})

    response: HttpResponse = client.get(uri)

    assert response.status_code == 302

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert messages[0].message == f"Invitation for {invitation.email} deleted"
    with pytest.raises(Invitation.DoesNotExist):
        Invitation.objects.get(pk=invitation.id)


@pytest.mark.django_db
def test_access_team_settings__when_user_is_owner__should_succeed(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    client = Client()
    uri = reverse(
        "teams:team_settings", kwargs={"team_key": sample_team_with_owner_member.team.key}
    )

    setup_authenticated_client_session(
        client,
        sample_team_with_owner_member.team,
        sample_team_with_owner_member.user
    )

    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == uri


@pytest.mark.django_db
def test_team_settings_handles_invalid_billing_plan_gracefully(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "invalid_plan"
    team.save()

    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    # Page should render and default to public when plan is invalid
    assert team.is_public is True


@pytest.mark.django_db
def test_update_visibility_blocks_invalid_billing_plan(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "invalid_plan"
    team.save()

    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response: HttpResponse = client.post(
        uri,
        {"visibility_action": "update", "is_public": ["false"]},
    )

    assert response.status_code == 302
    assert response.url == uri

    messages = list(get_messages(response.wsgi_request))
    assert any("Disabling the Trust Center is available on Business or Enterprise plans." in str(msg) for msg in messages)


@pytest.mark.django_db
def test_access_team_settings__when_user_is_admin__should_succeed(
    sample_team_with_admin_member: Member,  # noqa: F811
):
    client = Client()
    uri = reverse(
        "teams:team_settings", kwargs={"team_key": sample_team_with_admin_member.team.key}
    )

    setup_authenticated_client_session(
        client,
        sample_team_with_admin_member.team,
        sample_team_with_admin_member.user
    )

    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == uri


@pytest.mark.django_db
def test_access_team_settings__when_user_is_guest__should_fail(
    sample_team_with_guest_member: Member,  # noqa: F811
):
    client = Client()
    uri = reverse(
        "teams:team_settings", kwargs={"team_key": sample_team_with_guest_member.team.key}
    )
    setup_authenticated_client_session(
        client,
        sample_team_with_guest_member.team,
        sample_team_with_guest_member.user
    )
    response: HttpResponse = client.get(uri)
    assert response.status_code == 403
    assert "sufficient permissions" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_access_team_settings__when_user_is_not_member__should_fail(
    sample_team: Team,
):
    client = Client()
    uri = reverse(
        "teams:team_settings", kwargs={"team_key": sample_team.key}
    )

    # Unauthenticated users get redirected to login
    response: HttpResponse = client.get(uri)
    assert response.status_code == 302
    
    # Authenticated but not a member should get 403
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.create_user(username="testuser", email="test@example.com", password="test")
    client.force_login(user)
    
    # Ensure no current_team in session
    session = client.session
    if "current_team" in session:
        del session["current_team"]
    session.save()
    
    response: HttpResponse = client.get(uri)
    # TeamRoleRequiredMixin checks for current_team in session first
    # If no current_team, it returns 403 with error message rendered in error.html.j2
    assert response.status_code == 403
    content = response.content.decode("utf-8")
    # The error template renders exception.content.decode() which contains the error message
    # HttpResponseForbidden("You are not a member of any team") should be in the content
    assert "You are not a member of any team" in content or "not a member" in content.lower(), \
        f"Expected error message not found. Content: {content[:500]}"


@pytest.mark.django_db
def test_visibility_toggle__owner_can_make_public(
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
):
    client = Client()
    # Start from private (paid plans default to private on creation)
    team_with_business_plan.is_public = False
    team_with_business_plan.billing_plan = Team.Plan.BUSINESS
    team_with_business_plan.save(update_fields=["is_public", "billing_plan"])

    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team_with_business_plan.key})
    response = client.post(
        uri,
        {"visibility_action": "update", "is_public": ["false", "true"]},
    )

    assert response.status_code == 302
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.is_public is True
    assert client.session["current_team"]["is_public"] is True

    messages = list(get_messages(response.wsgi_request))
    assert any("Trust center is now public." in msg.message for msg in messages)


@pytest.mark.django_db
def test_visibility_toggle__community_cannot_be_private(
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_community_plan: Team,  # noqa: F811
):
    client = Client()
    setup_authenticated_client_session(client, team_with_community_plan, sample_user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team_with_community_plan.key})
    response = client.post(
        uri,
        {"visibility_action": "update", "is_public": ["false"]},
    )

    assert response.status_code == 302
    team_with_community_plan.refresh_from_db()
    assert team_with_community_plan.is_public is True

    messages = list(get_messages(response.wsgi_request))
    assert any("Trust Center is available on Business or Enterprise plans" in msg.message for msg in messages)


@pytest.mark.django_db
def test_visibility_toggle__non_owner_blocked(
    sample_team_with_admin_member: Member,  # noqa: F811
):
    client = Client()
    team = sample_team_with_admin_member.team
    team.billing_plan = Team.Plan.BUSINESS
    team.is_public = False
    team.save(update_fields=["billing_plan", "is_public"])

    setup_authenticated_client_session(client, team, sample_team_with_admin_member.user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(
        uri,
        {"visibility_action": "update", "is_public": ["false", "true"]},
    )

    assert response.status_code == 302
    team.refresh_from_db()
    assert team.is_public is False

    messages = list(get_messages(response.wsgi_request))
    assert any("Only workspace owners can change visibility" in msg.message for msg in messages)


@pytest.mark.django_db
@override_settings(BILLING=False)
def test_visibility_toggle_disallowed_when_billing_disabled(
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_community_plan: Team,  # noqa: F811
):
    client = Client()
    setup_authenticated_client_session(client, team_with_community_plan, sample_user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team_with_community_plan.key})
    response = client.post(
        uri,
        {"visibility_action": "update", "is_public": ["false"]},
    )

    assert response.status_code == 302
    team_with_community_plan.refresh_from_db()
    assert team_with_community_plan.is_public is True
    messages = list(get_messages(response.wsgi_request))
    assert any("Trust Center is available on Business or Enterprise plans" in str(msg) for msg in messages)


@pytest.mark.django_db
@override_settings(BILLING=False)
def test_model_allows_private_when_billing_disabled():
    team = Team.objects.create(name="Dev Env Team", billing_plan=None, is_public=False)
    team.refresh_from_db()
    assert team.is_public is True


@pytest.mark.django_db
def test_team_branding_api(sample_team_with_owner_member: Member, mocker):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    team_key = sample_team_with_owner_member.team.key
    base_uri = f"/api/v1/workspaces/{team_key}/branding"

    # Mock S3 client methods
    mock_upload = mocker.patch("sbomify.apps.core.object_store.S3Client.upload_media")
    mock_delete = mocker.patch("sbomify.apps.core.object_store.S3Client.delete_object")

    # Set up mock to store the filename that was used
    def upload_side_effect(filename, data):
        mock_upload.filename = filename
    mock_upload.side_effect = upload_side_effect

    # Test GET branding info
    response = client.get(base_uri)
    assert response.status_code == 200
    data = response.json()
    assert "brand_color" in data
    assert "accent_color" in data
    assert "prefer_logo_over_icon" in data
    assert "icon_url" in data
    assert "logo_url" in data

    # Test updating brand color
    response = client.patch(f"{base_uri}/brand_color",
                          {"value": "#ff0000"},
                          content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["brand_color"] == "#ff0000"

    # Test updating accent color
    response = client.patch(f"{base_uri}/accent_color",
                          {"value": "#00ff00"},
                          content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["accent_color"] == "#00ff00"

    # Test updating prefer_logo_over_icon
    response = client.patch(f"{base_uri}/prefer_logo_over_icon",
                          {"value": True},
                          content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["prefer_logo_over_icon"] is True

    # Test invalid field name
    response = client.patch(f"{base_uri}/invalid_field",
                          {"value": "test"},
                          content_type="application/json")
    assert response.status_code == 400
    assert "Invalid field" in response.json()["detail"]

    # Test file upload
    with open("test_icon.png", "wb") as f:
        f.write(b"fake png content")

    with open("test_icon.png", "rb") as f:
        response = client.post(f"{base_uri}/upload/icon",
                             {"file": f},
                             format="multipart")
        assert response.status_code == 200
        data = response.json()
        assert "icon_url" in data
        # Verify the filename uses the new UUID format
        assert mock_upload.filename.startswith(f"team_{team_key}_icon_")
        assert mock_upload.filename.endswith(".png")
        assert data["icon"] == mock_upload.filename

    # Clean up test file
    os.remove("test_icon.png")

    # Test that uploaded file URL is correctly generated
    # The bug was that URLs were generated from old branding data before upload
    with open("test_logo.png", "wb") as f:
        f.write(b"fake logo content")

    with open("test_logo.png", "rb") as f:
        response = client.post(f"{base_uri}/upload/logo",
                             {"file": f},
                             format="multipart")
        assert response.status_code == 200
        data = response.json()
        # Ensure the returned URL contains the correct filename that was just uploaded
        assert data["logo"].startswith(f"team_{team_key}_logo_")
        assert data["logo"].endswith(".png")
        assert data["logo"] in data["logo_url"]

    # Clean up test file
    os.remove("test_logo.png")

    # Test file deletion
    response = client.patch(f"{base_uri}/icon",
                          {"value": None},
                          content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["icon"] == ""
    # Verify delete was called
    mock_delete.assert_called_once()


@pytest.mark.django_db
def test_team_branding_atomic_upload(sample_team_with_owner_member: Member, mocker):  # noqa: F811
    """Test that branding file uploads are atomic - proper cleanup on failures."""
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    team_key = sample_team_with_owner_member.team.key
    base_uri = f"/api/v1/workspaces/{team_key}/branding"

    # Mock S3 client methods
    mock_upload = mocker.patch("sbomify.apps.core.object_store.S3Client.upload_media")
    mock_delete = mocker.patch("sbomify.apps.core.object_store.S3Client.delete_object")

    uploaded_files = []
    deleted_files = []

    def upload_side_effect(filename, data):
        uploaded_files.append(filename)

    def delete_side_effect(bucket, filename):
        deleted_files.append(filename)

    mock_upload.side_effect = upload_side_effect
    mock_delete.side_effect = delete_side_effect

    # Test 1: Successful upload with old file cleanup for ICON
    team = sample_team_with_owner_member.team
    team.branding_info = {"icon": "old_icon_file.png", "logo": "", "brand_color": "", "accent_color": ""}
    team.save()

    # Upload new icon
    with open("test_icon.png", "wb") as f:
        f.write(b"fake icon content")

    with open("test_icon.png", "rb") as f:
        response = client.post(f"{base_uri}/upload/icon",
                             {"file": f},
                             format="multipart")
        assert response.status_code == 200
        data = response.json()

        # Verify new file was uploaded with UUID-based filename
        assert len(uploaded_files) == 1
        new_filename = uploaded_files[0]
        assert new_filename.startswith(f"team_{team_key}_icon_")
        assert new_filename.endswith(".png")
        assert len(new_filename.split("_")) >= 4  # team_KEY_icon_UUID.ext

        # Verify old file was deleted
        assert len(deleted_files) == 1
        assert deleted_files[0] == "old_icon_file.png"

        # Verify database was updated
        team.refresh_from_db()
        assert team.branding_info["icon"] == new_filename
        assert data["icon"] == new_filename

    os.remove("test_icon.png")

    # Test 2: Successful upload with old file cleanup for LOGO
    uploaded_files.clear()
    deleted_files.clear()

    # Set up existing logo
    team.branding_info = {"icon": new_filename, "logo": "old_logo_file.jpg", "brand_color": "", "accent_color": ""}
    team.save()

    with open("test_logo.jpg", "wb") as f:
        f.write(b"fake logo content")

    with open("test_logo.jpg", "rb") as f:
        response = client.post(f"{base_uri}/upload/logo",
                             {"file": f},
                             format="multipart")
        assert response.status_code == 200
        data = response.json()

        # Verify new file was uploaded with UUID-based filename
        assert len(uploaded_files) == 1
        new_logo_filename = uploaded_files[0]
        assert new_logo_filename.startswith(f"team_{team_key}_logo_")
        assert new_logo_filename.endswith(".jpg")

        # Verify old file was deleted
        assert len(deleted_files) == 1
        assert deleted_files[0] == "old_logo_file.jpg"

        # Verify database was updated
        team.refresh_from_db()
        assert team.branding_info["logo"] == new_logo_filename
        assert data["logo"] == new_logo_filename

    os.remove("test_logo.jpg")

    # Test 3: Upload when no existing file
    uploaded_files.clear()
    deleted_files.clear()

    # Clear existing icon
    team.branding_info = {"icon": "", "logo": new_logo_filename, "brand_color": "", "accent_color": ""}
    team.save()

    with open("test_icon_new.png", "wb") as f:
        f.write(b"new icon content")

    with open("test_icon_new.png", "rb") as f:
        response = client.post(f"{base_uri}/upload/icon",
                             {"file": f},
                             format="multipart")
        assert response.status_code == 200

        # Should upload new file but not delete anything
        assert len(uploaded_files) == 1
        assert len(deleted_files) == 0

        # Verify unique filename
        new_icon_filename = uploaded_files[0]
        assert new_icon_filename.startswith(f"team_{team_key}_icon_")
        assert new_icon_filename != new_filename  # Different from previous icon

    os.remove("test_icon_new.png")


@pytest.mark.django_db
def test_team_branding_api_permissions(sample_team_with_guest_member: Member):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    team_key = sample_team_with_guest_member.team.key
    base_uri = f"/api/v1/workspaces/{team_key}/branding"

    # Test GET branding info as non-owner
    response = client.get(base_uri)
    assert response.status_code == 200

    # Test updating brand color as non-owner
    response = client.patch(f"{base_uri}/brand_color",
                          {"value": "#ff0000"},
                          content_type="application/json")
    assert response.status_code == 403
    assert "Only allowed for owners" in response.json()["detail"]

    # Test file upload as non-owner
    with open("test_icon.png", "wb") as f:
        f.write(b"fake png content")

    with open("test_icon.png", "rb") as f:
        response = client.post(f"{base_uri}/upload/icon",
                             {"file": f},
                             format="multipart")
        assert response.status_code == 403
        assert "Only allowed for owners" in response.json()["detail"]

    # Clean up test file
    os.remove("test_icon.png")


def test_branding_schema():
    branding_info = BrandingInfo(
        brand_color="red",
        accent_color="blue",
        prefer_logo_over_icon=True,
        icon="icon.png",
        logo="logo.png",
    )

    assert branding_info.brand_color == "red"
    assert branding_info.accent_color == "blue"
    assert (
        branding_info.brand_icon_url
        == settings.AWS_MEDIA_STORAGE_BUCKET_URL + "/icon.png"
    )
    assert (
        branding_info.brand_logo_url
        == settings.AWS_MEDIA_STORAGE_BUCKET_URL + "/logo.png"
    )
    assert (
        branding_info.brand_image
        == settings.AWS_MEDIA_STORAGE_BUCKET_URL + "/logo.png"
    )

    branding_info.prefer_logo_over_icon = False
    assert (
        branding_info.brand_image
        == settings.AWS_MEDIA_STORAGE_BUCKET_URL + "/logo.png"
    )

    branding_info.icon = ""
    assert branding_info.brand_icon_url == ""

    branding_info.icon = "icon.png"
    assert branding_info.brand_icon_url == settings.AWS_MEDIA_STORAGE_BUCKET_URL + "/icon.png"
    branding_info.prefer_logo_over_icon = True
    branding_info.logo = ""
    assert (
        branding_info.brand_image
        == settings.AWS_MEDIA_STORAGE_BUCKET_URL + "/icon.png"
    )

    branding_info.icon = ""
    assert branding_info.brand_image == ""


def test_branding_schema_uses_bucket_url_over_endpoint():
    custom_bucket_url = "https://cdn.example.com/media-bucket"
    branding_info = BrandingInfo(
        icon="icon.png",
        logo="logo.png",
    )

    with override_settings(
        AWS_MEDIA_STORAGE_BUCKET_URL=custom_bucket_url,
        AWS_ENDPOINT_URL_S3="http://ignored-endpoint",
        AWS_MEDIA_STORAGE_BUCKET_NAME="should-not-appear",
    ):
        assert branding_info.brand_icon_url == f"{custom_bucket_url}/icon.png"
        assert branding_info.brand_logo_url == f"{custom_bucket_url}/logo.png"


@pytest.mark.django_db
def test_cannot_delete_default_team(sample_user: AbstractBaseUser):
    """Test that you cannot delete the default team"""
    # Create two teams
    team1 = Team.objects.create(name="Default Team")
    team1.key = number_to_random_token(team1.pk)
    team1.save()

    team2 = Team.objects.create(name="Second Team")
    team2.key = number_to_random_token(team2.pk)
    team2.save()

    # Create memberships - team1 is default
    member1 = Member.objects.create(team=team1, user=sample_user, role="owner", is_default_team=True)
    member2 = Member.objects.create(team=team2, user=sample_user, role="owner", is_default_team=False)

    client = Client()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    # Set up session data
    session = client.session
    session["user_teams"] = {
        team1.key: {"role": "owner", "name": team1.name, "is_default_team": True},
        team2.key: {"role": "owner", "name": team2.name, "is_default_team": False}
    }
    session.save()

    # Try to delete the default team - should fail
    uri = reverse("teams:teams_dashboard")
    form_data = urlencode({"_method": "DELETE", "key": team1.key})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 302

    # Verify team still exists
    assert Team.objects.filter(pk=team1.pk).exists()

    # Check error message
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert "Cannot delete the default workspace" in str(messages[0])


@pytest.mark.django_db
def test_cannot_delete_last_team(sample_user: AbstractBaseUser):
    """Test that you cannot delete your last/only team"""
    # Create only one team
    team = Team.objects.create(name="Only Team")
    team.key = number_to_random_token(team.pk)
    team.save()

    # Create membership - this is the only team so it's default
    member = Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

    client = Client()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    # Set up session data
    session = client.session
    session["user_teams"] = {
        team.key: {"role": "owner", "name": team.name, "is_default_team": True}
    }
    session.save()

    # Try to delete the only team - should fail
    uri = reverse("teams:teams_dashboard")
    form_data = urlencode({"_method": "DELETE", "key": team.key})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 302

    # Verify team still exists
    assert Team.objects.filter(pk=team.pk).exists()

    # Check error message
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert "Cannot delete the default workspace" in str(messages[0])


@pytest.mark.django_db
def test_can_delete_non_default_team_when_multiple_exist(sample_user: AbstractBaseUser):
    """Test that you can delete a non-default team when you have multiple teams"""
    # Create two teams
    team1 = Team.objects.create(name="Default Team")
    team1.key = number_to_random_token(team1.pk)
    team1.save()

    team2 = Team.objects.create(name="Non-Default Team")
    team2.key = number_to_random_token(team2.pk)
    team2.save()

    # Create memberships - team1 is default
    member1 = Member.objects.create(team=team1, user=sample_user, role="owner", is_default_team=True)
    member2 = Member.objects.create(team=team2, user=sample_user, role="owner", is_default_team=False)

    client = Client()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    # Set up session data
    session = client.session
    session["user_teams"] = {
        team1.key: {"role": "owner", "name": team1.name, "is_default_team": True},
        team2.key: {"role": "owner", "name": team2.name, "is_default_team": False}
    }
    session.save()

    # Try to delete the non-default team - should succeed
    uri = reverse("teams:teams_dashboard")
    form_data = urlencode({"_method": "DELETE", "key": team2.key})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    # Check redirect to teams dashboard
    assert response.status_code == 302
    assert response.url == reverse("teams:teams_dashboard")

    # Verify non-default team is deleted
    assert not Team.objects.filter(pk=team2.pk).exists()

    # Verify default team still exists
    assert Team.objects.filter(pk=team1.pk).exists()

    # Check success message
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert str(messages[0]) == f"Workspace {team2.name} has been deleted"


@pytest.mark.django_db
def test_delete_team_auto_makes_another_default_when_needed(sample_user: AbstractBaseUser):
    """Test that when a default team is deleted (if allowed), another team becomes default automatically"""
    # This test covers edge cases where we might allow default deletion in the future
    # For now, this documents expected behavior if the logic changes
    pass


# ============================================================================
# Workspaces API Tests
# ============================================================================

@pytest.mark.django_db
def test_list_teams_api_success(authenticated_api_client, sample_user):  # noqa: F811
    """Test successful listing of teams for authenticated user."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Create multiple teams for the user
    team1 = Team.objects.create(name="Team One", billing_plan="business")
    team1.key = number_to_random_token(team1.pk)
    team1.save()

    team2 = Team.objects.create(name="Team Two", billing_plan="community")
    team2.key = number_to_random_token(team2.pk)
    team2.save()

    # Add user as member to both teams
    Member.objects.create(team=team1, user=sample_user, role="owner", is_default_team=True)
    Member.objects.create(team=team2, user=sample_user, role="admin", is_default_team=False)

    # Test the API
    response = client.get("/api/v1/workspaces/", **headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    # Check that both teams are returned
    team_names = {team["name"] for team in data}
    assert "Team One" in team_names
    assert "Team Two" in team_names

    # Check response structure
    for team in data:
        assert "key" in team
        assert "name" in team
        assert "created_at" in team
        assert "has_completed_wizard" in team
        assert "is_public" in team
        assert "billing_plan" in team


@pytest.mark.django_db
def test_list_teams_api_empty_result(authenticated_api_client, sample_user):  # noqa: F811
    """Test listing teams when user has no teams."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Don't create any teams for the user

    response = client.get("/api/v1/workspaces/", **headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 0
    assert data == []


@pytest.mark.django_db
def test_list_teams_api_unauthenticated(client):
    """Test that unauthenticated requests are rejected."""
    response = client.get("/api/v1/workspaces/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_list_teams_api_only_user_teams(authenticated_api_client, sample_user, guest_user):  # noqa: F811
    """Test that users only see teams they are members of."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Create teams for sample_user
    user_team = Team.objects.create(name="User Team")
    user_team.key = number_to_random_token(user_team.pk)
    user_team.save()
    Member.objects.create(team=user_team, user=sample_user, role="owner")

    # Create team for guest_user (sample_user should not see this)
    other_team = Team.objects.create(name="Other Team")
    other_team.key = number_to_random_token(other_team.pk)
    other_team.save()
    Member.objects.create(team=other_team, user=guest_user, role="owner")

    response = client.get("/api/v1/workspaces/", **headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "User Team"


@pytest.mark.django_db
def test_get_team_api_success(authenticated_api_client, sample_user):  # noqa: F811
    """Test successful retrieval of team details."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Create a team
    team = Team.objects.create(
        name="Test Team",
        billing_plan="business",
        has_completed_wizard=True
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    # Add user as member
    Member.objects.create(team=team, user=sample_user, role="owner")

    response = client.get(f"/api/v1/workspaces/{team.key}", **headers)

    assert response.status_code == 200
    data = response.json()

    assert data["key"] == team.key
    assert data["name"] == "Test Team"
    assert data["billing_plan"] == "business"
    assert data["has_completed_wizard"] is True
    assert "created_at" in data


@pytest.mark.django_db
def test_get_team_api_invalid_team_key(authenticated_api_client):
    """Test get team with invalid team key returns 404."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    response = client.get("/api/v1/workspaces/invalid-key", **headers)

    assert response.status_code == 404
    data = response.json()
    assert "Workspace not found" in data["detail"]


@pytest.mark.django_db
def test_get_team_api_nonexistent_team(authenticated_api_client):
    """Test get team with nonexistent but valid team key format."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Use a valid format team key that doesn't exist
    fake_key = number_to_random_token(99999)

    response = client.get(f"/api/v1/workspaces/{fake_key}", **headers)

    assert response.status_code == 404
    data = response.json()
    assert "Workspace not found" in data["detail"]


@pytest.mark.django_db
def test_get_team_api_access_denied(authenticated_api_client, sample_user, guest_user):  # noqa: F811
    """Test that users cannot access teams they are not members of."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Create a team with a different user as owner
    team = Team.objects.create(name="Other Team")
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(team=team, user=guest_user, role="owner")

    # sample_user (authenticated user) should not be able to access this team
    response = client.get(f"/api/v1/workspaces/{team.key}", **headers)

    assert response.status_code == 403
    data = response.json()
    assert "Access denied" in data["detail"]


@pytest.mark.django_db
def test_get_team_api_unauthenticated(client):
    """Test that unauthenticated requests are rejected."""
    # Create a team
    team = Team.objects.create(name="Test Team")
    team.key = number_to_random_token(team.pk)
    team.save()

    response = client.get(f"/api/v1/workspaces/{team.key}")

    assert response.status_code == 401


@pytest.mark.django_db
def test_get_team_api_different_roles(authenticated_api_client, guest_api_client, sample_user, guest_user):  # noqa: F811
    """Test that guest members cannot access team details."""
    # Create a team
    team = Team.objects.create(name="Multi-Role Team")
    team.key = number_to_random_token(team.pk)
    team.save()

    # Add users with different roles
    Member.objects.create(team=team, user=sample_user, role="owner")
    Member.objects.create(team=team, user=guest_user, role="guest")

    # Test owner access
    owner_client, owner_token = authenticated_api_client
    owner_headers = get_api_headers(owner_token)

    response = owner_client.get(f"/api/v1/workspaces/{team.key}", **owner_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Multi-Role Team"

    # Test guest access
    guest_client, guest_token = guest_api_client
    guest_headers = get_api_headers(guest_token)

    response = guest_client.get(f"/api/v1/workspaces/{team.key}", **guest_headers)
    assert response.status_code == 403


@pytest.mark.django_db
def test_patch_team_toggles_public_flag(authenticated_api_client, sample_user):  # noqa: F811
    """Owners can toggle workspace public visibility via API."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    team = Team.objects.create(name="Visibility Toggle", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(team=team, user=sample_user, role="owner")

    response = client.patch(
        f"/api/v1/workspaces/{team.key}",
        json.dumps({"is_public": False}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_public"] is False

    team.refresh_from_db()
    assert team.is_public is False


@pytest.mark.django_db
def test_patch_team_private_not_allowed_on_community(authenticated_api_client, sample_user):  # noqa: F811
    """Community workspaces cannot be made private."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    team = Team.objects.create(name="Community Team")
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(team=team, user=sample_user, role="owner")

    response = client.patch(
        f"/api/v1/workspaces/{team.key}",
        json.dumps({"is_public": False}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 403
    assert "Trust Center" in response.json()["detail"]

    team.refresh_from_db()
    assert team.is_public is True


@pytest.mark.django_db
def test_paid_plans_default_private():
    """Business and Enterprise plans start private by default."""
    business = Team.objects.create(name="Business Default", billing_plan="business")
    assert business.is_public is False

    enterprise = Team.objects.create(name="Enterprise Default", billing_plan="enterprise")
    assert enterprise.is_public is False


@pytest.mark.django_db
def test_paid_plans_case_insensitive_for_privacy_flag():
    """Paid plans with capitalized keys should still allow private workspaces."""
    team = Team.objects.create(name="Business Case", billing_plan="Business", is_public=False)
    assert team.is_public is False


@pytest.mark.django_db
def test_private_workspace_allowed_case_insensitive():
    """API helper treats mixed-case plans as paid."""
    team = Team.objects.create(name="Enterprise Case", billing_plan="Enterprise", is_public=False)
    assert _private_workspace_allowed(team) is True


@pytest.mark.django_db
def test_private_workspace_rejects_unknown_plan():
    """Unsupported billing plans should not allow private workspaces."""
    team = Team(name="Custom Plan", billing_plan="test_plan", is_public=False)
    assert _private_workspace_allowed(team) is False


@pytest.mark.django_db
def test_private_workspace_allowed_custom_plan_when_registered():
    """Custom plans that exist in BillingPlan are treated as paid/allowing private workspaces."""
    plan = BillingPlan.objects.create(key="custom_plan", name="Custom Plan", description="Custom Plan Description")
    team = Team.objects.create(name="Custom Plan Workspace", billing_plan=plan.key, is_public=False)
    assert _private_workspace_allowed(team) is True


@pytest.mark.django_db
def test_community_plan_defaults_public_even_if_set_false():
    """Community plan workspaces cannot end up private."""
    team = Team.objects.create(name="Community Default", billing_plan="community", is_public=False)
    assert team.is_public is True


@pytest.mark.django_db
def test_community_plan_save_cannot_flip_to_private():
    """Existing community workspaces stay public even if saved with is_public=False."""
    team = Team.objects.create(name="Community Existing", billing_plan="community", is_public=True)

    team.is_public = False
    team.save()
    team.refresh_from_db()

    assert team.is_public is True


@pytest.mark.django_db
def test_downgrading_from_paid_to_community_forces_public():
    """Switching from paid plan back to community makes workspace public again."""
    team = Team.objects.create(name="Paid Workspace", billing_plan="business", is_public=False)

    team.billing_plan = "community"
    team.save()

    team.refresh_from_db()
    assert team.is_public is True


@pytest.mark.django_db
def test_teams_api_response_schema_validation(authenticated_api_client, sample_user):  # noqa: F811
    """Test that API responses match expected schema."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Create a team with all possible fields
    team = Team.objects.create(
        name="Schema Test Team",
        billing_plan="enterprise",
        has_completed_wizard=False
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=sample_user, role="admin")

    # Test list teams response schema
    response = client.get("/api/v1/workspaces/", **headers)
    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    team_data = data[0]

    # Required fields
    required_fields = ["key", "name", "created_at", "has_completed_wizard", "is_public", "billing_plan"]
    for field in required_fields:
        assert field in team_data, f"Field {field} missing from response"

    # Test get team response schema
    response = client.get(f"/api/v1/workspaces/{team.key}", **headers)
    assert response.status_code == 200
    data = response.json()

    for field in required_fields:
        assert field in data, f"Field {field} missing from response"

    # Validate data types
    assert isinstance(data["key"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["created_at"], str)
    assert isinstance(data["has_completed_wizard"], bool)
    assert isinstance(data["is_public"], bool)
    assert data["billing_plan"] is None or isinstance(data["billing_plan"], str)


# ==================== Team General Settings View Tests ====================


@pytest.mark.django_db
def test_team_general_get__when_user_is_owner__should_succeed(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that owners can access the general settings view."""
    client = Client()
    team = sample_team_with_owner_member.team
    uri = reverse("teams:team_general", kwargs={"team_key": team.key})

    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert team.name in response.content.decode("utf-8")


@pytest.mark.django_db
def test_team_general_get__when_user_is_admin__should_fail(
    sample_team_with_admin_member: Member,  # noqa: F811
):
    """Test that admins cannot access the general settings view (owner-only)."""
    client = Client()
    team = sample_team_with_admin_member.team
    uri = reverse("teams:team_general", kwargs={"team_key": team.key})

    setup_authenticated_client_session(client, team, sample_team_with_admin_member.user)

    response: HttpResponse = client.get(uri)

    assert response.status_code == 403


@pytest.mark.django_db
def test_team_general_get__when_user_is_guest__should_fail(
    sample_team_with_guest_member: Member,  # noqa: F811
):
    """Test that guests cannot access the general settings view."""
    client = Client()
    team = sample_team_with_guest_member.team
    uri = reverse("teams:team_general", kwargs={"team_key": team.key})

    setup_authenticated_client_session(client, team, sample_team_with_guest_member.user)

    response: HttpResponse = client.get(uri)

    assert response.status_code == 403


@pytest.mark.django_db
def test_team_general_post__update_name_successfully(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that owners can update the workspace name."""
    client = Client()
    team = sample_team_with_owner_member.team
    original_name = team.name
    new_name = "Updated Workspace Name"
    uri = reverse("teams:team_general", kwargs={"team_key": team.key})

    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response: HttpResponse = client.post(uri, {"name": new_name})

    assert response.status_code == 200
    # Check HX-Trigger header for HTMX success response
    assert "HX-Trigger" in response.headers

    # Verify the name was updated in the database
    team.refresh_from_db()
    assert team.name == new_name
    assert team.name != original_name


@pytest.mark.django_db
def test_team_general_post__empty_name_should_fail(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that empty workspace name is rejected."""
    client = Client()
    team = sample_team_with_owner_member.team
    original_name = team.name
    uri = reverse("teams:team_general", kwargs={"team_key": team.key})

    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response: HttpResponse = client.post(uri, {"name": ""})

    assert response.status_code == 200
    # Check for error in HX-Trigger
    assert "HX-Trigger" in response.headers
    trigger = json.loads(response.headers["HX-Trigger"])
    assert "messages" in trigger
    assert trigger["messages"][0]["type"] == "error"

    # Verify the name was not updated
    team.refresh_from_db()
    assert team.name == original_name


@pytest.mark.django_db
def test_team_general_post__admin_cannot_update_name(
    sample_team_with_admin_member: Member,  # noqa: F811
):
    """Test that admins cannot update the workspace name."""
    client = Client()
    team = sample_team_with_admin_member.team
    original_name = team.name
    uri = reverse("teams:team_general", kwargs={"team_key": team.key})

    setup_authenticated_client_session(client, team, sample_team_with_admin_member.user)

    response: HttpResponse = client.post(uri, {"name": "New Name"})

    # Should be forbidden
    assert response.status_code == 403

    # Verify the name was not updated
    team.refresh_from_db()
    assert team.name == original_name


@pytest.mark.django_db
def test_team_general_post__updates_session(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that updating workspace name also updates the session."""
    client = Client()
    team = sample_team_with_owner_member.team
    new_name = "Session Updated Name"
    uri = reverse("teams:team_general", kwargs={"team_key": team.key})

    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response: HttpResponse = client.post(uri, {"name": new_name})

    assert response.status_code == 200

    # Verify session was updated
    session = client.session
    assert session["current_team"]["name"] == new_name
