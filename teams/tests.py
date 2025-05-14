# skip_file  # nosec
from __future__ import annotations

import os
from urllib.parse import urlencode
import boto3

import pytest
from django.http import HttpResponse, HttpResponseRedirect
from django.test import Client, TestCase
from django.urls import reverse
import django.contrib.messages as django_messages
from django.contrib.messages import get_messages
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser

from core.utils import number_to_random_token

from .fixtures import (  # noqa: F401
    sample_user,
    guest_user,
    sample_team,
    sample_team_with_owner_member,
    sample_team_with_guest_member,
)
from .models import Team, Member, Invitation
from .schemas import BrandingInfo


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
    form_data = urlencode({"name": "New Test Team"})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 302
    assert response.url == reverse("teams:teams_dashboard")
    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert messages[0].message == "Team New Test Team created successfully"

    team = Team.objects.filter(name="New Test Team").first()
    assert team is not None  # nosec
    assert team.key is not None  # nosec
    assert len(team.key) > 0  # nosec


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
    client = Client()

    # User not logged in
    uri = reverse("teams:team_details", kwargs={"team_key": sample_team_with_owner_member.team.key})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == uri


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

    response: HttpResponse = client.get(uri)

    assert response.status_code == 403
    assert "Only allowed for owners" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_set_default_team(sample_team_with_owner_member: Member):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    uri = reverse("teams:set_default_team", kwargs={"membership_id": sample_team_with_owner_member.id})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url == reverse("teams:teams_dashboard")

    membership = Member.objects.filter(
        user_id=sample_team_with_owner_member.user_id, team_id=sample_team_with_owner_member.team_id
    ).first()

    assert membership.is_default_team is True


@pytest.mark.django_db
def test_delete_team(sample_user: AbstractBaseUser):
    """Test deleting a team"""
    # Create a team with an owner
    team = Team.objects.create(name="Temporary Test Team")
    team.key = number_to_random_token(team.pk)
    team.save()

    owner = Member.objects.create(team=team, user=sample_user, role="owner")

    # Set up session data
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )
    session = client.session
    session["user_teams"] = {
        team.key: {"role": "owner", "name": team.name}
    }
    session.save()

    # Try to delete the team
    response = client.post(reverse("teams:delete_team", kwargs={"team_key": team.key}))

    # Check redirect to teams dashboard
    assert response.status_code == 302
    assert response.url == reverse("teams:teams_dashboard")

    # Verify team is deleted
    assert not Team.objects.filter(pk=team.pk).exists()

    # Verify member is deleted (due to CASCADE)
    assert not Member.objects.filter(pk=owner.pk).exists()

    # Check success message
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert str(messages[0]) == f"Team {team.name} has been deleted"


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
    response = client.post(reverse("teams:delete_team", kwargs={"team_key": team.key}))

    # Check forbidden response
    assert response.status_code == 403

    # Verify team still exists
    assert Team.objects.filter(pk=team.pk).exists()


@pytest.mark.django_db
def test_only_owners_are_allowed_to_open_team_invitation_form_view(sample_team: Team):  # noqa: F811
    client = Client()

    uri = reverse("teams:invite_user", kwargs={"team_key": sample_team.key})
    response: HttpResponse = client.get(uri)

    assert response.status_code == 403
    assert "Only allowed for owners" in response.content.decode("utf-8")


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

    uri = reverse("teams:invite_user", kwargs={"team_key": sample_team.key})
    form_data = urlencode({"email": "guest@example.com", "role": "guest"})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 403
    assert "Only allowed for owners" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_team_invitation(sample_team_with_owner_member: Member):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    uri = reverse("teams:invite_user", kwargs={"team_key": sample_team_with_owner_member.team.key})
    form_data = urlencode({"email": "guest@example.com", "role": "guest"})
    response: HttpResponse = client.post(
        uri, form_data, content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 302

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert messages[0].message == "Invite sent to guest@example.com"

    invitations = Invitation.objects.filter(email="guest@example.com").all()

    assert len(invitations) == 1
    assert invitations[0].team == sample_team_with_owner_member.team
    assert invitations[0].role == "guest"
    assert invitations[0].has_expired is False


@pytest.mark.django_db
def test_accept_invitation(
    sample_team_with_owner_member: Member,  # noqa: F811
    guest_user: AbstractBaseUser,  # noqa: F811
):
    test_team_invitation(sample_team_with_owner_member)

    # accept_invite
    client = Client()
    assert client.login(username="guest", password="guest")  # nosec B106

    invitation = Invitation.objects.filter(email="guest@example.com").first()
    uri = reverse("teams:accept_invite", kwargs={"invite_id": invitation.id})

    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert messages[0].message.startswith("You have joined")


@pytest.mark.django_db
def test_delete_membership(
    sample_team_with_owner_member: Member,  # noqa: F811
    guest_user: AbstractBaseUser,  # noqa: F811
):
    test_accept_invitation(sample_team_with_owner_member, guest_user)

    membership = Member.objects.filter(
        user_id=guest_user.id, team_id=sample_team_with_owner_member.team_id
    ).first()

    uri = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})

    client = Client()

    # Guest user should not be able to remove the membership where his role is 'guest'
    assert client.login(username="guest", password="guest")  # nosec B106
    response: HttpResponse = client.get(uri)
    assert response.status_code == 403

    # Admin user (sample_user or test_user in this case) should be able to delete the membership (as he is owner)
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )
    response: HttpResponse = client.get(uri)
    assert response.status_code == 302

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert (
        messages[0].message
        == f"Member {membership.user.username} removed from team {membership.team.name}"
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

    invitation = Invitation.objects.filter(email="guest@example.com").first()
    uri = reverse("teams:team_invitation_delete", kwargs={"invitation_id": invitation.id})

    response: HttpResponse = client.get(uri)

    assert response.status_code == 302

    messages = list(get_messages(response.wsgi_request))

    assert len(messages) == 1
    assert messages[0].message == f"Invitation for {invitation.email} deleted"
    with pytest.raises(Invitation.DoesNotExist):
        Invitation.objects.get(pk=invitation.id)


@pytest.mark.django_db
def test_only_owners_are_allowed_to_access_team_settings(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    client = Client()

    # User not logged in
    uri = reverse(
        "teams:team_settings", kwargs={"team_key": sample_team_with_owner_member.team.key}
    )
    response: HttpResponse = client.get(uri)

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == uri


@pytest.mark.django_db
def test_team_branding_api(sample_team_with_owner_member: Member, mocker):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    team_key = sample_team_with_owner_member.team.key
    base_uri = f'/api/v1/teams/{team_key}/branding'

    # Mock S3 client methods
    mock_upload = mocker.patch("core.object_store.S3Client.upload_media")
    mock_delete = mocker.patch("core.object_store.S3Client.delete_object")

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
    response = client.patch(f'{base_uri}/brand_color',
                          {"value": "#ff0000"},
                          content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["brand_color"] == "#ff0000"

    # Test updating accent color
    response = client.patch(f'{base_uri}/accent_color',
                          {"value": "#00ff00"},
                          content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["accent_color"] == "#00ff00"

    # Test updating prefer_logo_over_icon
    response = client.patch(f'{base_uri}/prefer_logo_over_icon',
                          {"value": True},
                          content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["prefer_logo_over_icon"] is True

    # Test invalid field name
    response = client.patch(f'{base_uri}/invalid_field',
                          {"value": "test"},
                          content_type="application/json")
    assert response.status_code == 400
    assert "Invalid field" in response.json()["detail"]

    # Test file upload
    with open("test_icon.png", "wb") as f:
        f.write(b"fake png content")

    with open("test_icon.png", "rb") as f:
        response = client.post(f'{base_uri}/upload/icon',
                             {"file": f},
                             format="multipart")
        assert response.status_code == 200
        data = response.json()
        assert "icon_url" in data
        # Verify the filename matches what we expect
        assert mock_upload.filename == f"{team_key}_icon.png"
        assert data["icon"].endswith(mock_upload.filename)

    # Clean up test file
    os.remove("test_icon.png")

    # Test file deletion
    response = client.patch(f'{base_uri}/icon',
                          {"value": None},
                          content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["icon"] == ""
    # Verify delete was called
    mock_delete.assert_called_once()


@pytest.mark.django_db
def test_team_branding_api_permissions(sample_team_with_guest_member: Member):  # noqa: F811
    client = Client()

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    team_key = sample_team_with_guest_member.team.key
    base_uri = f'/api/v1/teams/{team_key}/branding'

    # Test GET branding info as non-owner
    response = client.get(base_uri)
    assert response.status_code == 200

    # Test updating brand color as non-owner
    response = client.patch(f'{base_uri}/brand_color',
                          {"value": "#ff0000"},
                          content_type="application/json")
    assert response.status_code == 403
    assert "Only allowed for owners" in response.json()["detail"]

    # Test file upload as non-owner
    with open("test_icon.png", "wb") as f:
        f.write(b"fake png content")

    with open("test_icon.png", "rb") as f:
        response = client.post(f'{base_uri}/upload/icon',
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
        == settings.AWS_ENDPOINT_URL_S3 + "/" + settings.AWS_MEDIA_STORAGE_BUCKET_NAME + "/icon.png"
    )
    assert (
        branding_info.brand_logo_url
        == settings.AWS_ENDPOINT_URL_S3 + "/" + settings.AWS_MEDIA_STORAGE_BUCKET_NAME + "/logo.png"
    )
    assert (
        branding_info.brand_image
        == settings.AWS_ENDPOINT_URL_S3 + "/" + settings.AWS_MEDIA_STORAGE_BUCKET_NAME + "/logo.png"
    )

    branding_info.prefer_logo_over_icon = False
    assert (
        branding_info.brand_image
        == settings.AWS_ENDPOINT_URL_S3 + "/" + settings.AWS_MEDIA_STORAGE_BUCKET_NAME + "/icon.png"
    )

    branding_info.prefer_logo_over_icon = True
    branding_info.logo = ""
    assert (
        branding_info.brand_image
        == settings.AWS_ENDPOINT_URL_S3 + "/" + settings.AWS_MEDIA_STORAGE_BUCKET_NAME + "/icon.png"
    )

    branding_info.icon = ""
    assert branding_info.brand_image == ""
