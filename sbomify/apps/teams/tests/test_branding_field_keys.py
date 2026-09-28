"""The branding icon and logo keys belong to the upload paths, and a branding
change only ever deletes an object the workspace uploaded itself."""

import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from sbomify.apps.teams.models import Member

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def owner_client(sample_team_with_owner_member: Member) -> Client:
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    return client


@pytest.fixture
def storage(mocker):
    deleted: list[str] = []
    mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_media")
    mocker.patch(
        "sbomify.apps.core.object_store.StorageClient.delete_object",
        side_effect=lambda bucket, key: deleted.append(key),
    )
    return deleted


def _set_branding(team, **fields) -> None:
    team.branding_info = {"icon": "", "logo": "", "brand_color": "", "accent_color": "", **fields}
    team.save()


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["icon", "logo"])
def test_patch_refuses_a_key_for_icon_or_logo(sample_team_with_owner_member, owner_client, storage, field):
    team = sample_team_with_owner_member.team
    own_key = f"team_{team.key}_{field}_existing.png"
    _set_branding(team, **{field: own_key})

    response = owner_client.patch(
        f"/api/v1/workspaces/{team.key}/branding/{field}",
        {"value": "team_someoneelse_logo_abc.png"},
        content_type="application/json",
    )

    assert response.status_code == 400
    team.refresh_from_db()
    assert team.branding_info[field] == own_key
    assert storage == []


@pytest.mark.django_db
def test_clearing_an_own_key_deletes_it(sample_team_with_owner_member, owner_client, storage):
    team = sample_team_with_owner_member.team
    own_key = f"team_{team.key}_icon_existing.png"
    _set_branding(team, icon=own_key)

    response = owner_client.patch(
        f"/api/v1/workspaces/{team.key}/branding/icon", {"value": None}, content_type="application/json"
    )

    assert response.status_code == 200
    assert response.json()["icon"] == ""
    assert storage == [own_key]


@pytest.mark.django_db
def test_clearing_a_legacy_own_key_deletes_it(sample_team_with_owner_member, owner_client, storage):
    team = sample_team_with_owner_member.team
    legacy_key = f"{team.key}_logo.png"
    _set_branding(team, logo=legacy_key)

    response = owner_client.patch(
        f"/api/v1/workspaces/{team.key}/branding/logo", {"value": None}, content_type="application/json"
    )

    assert response.status_code == 200
    assert storage == [legacy_key]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "stored",
    ["team_otherkey_icon_abc.png", "sboms/some-object.json", "otherkey_icon.png", "{key}_icon"],
)
def test_clearing_a_key_from_elsewhere_leaves_the_object(sample_team_with_owner_member, owner_client, storage, stored):
    team = sample_team_with_owner_member.team
    _set_branding(team, icon=stored.format(key=team.key))

    response = owner_client.patch(
        f"/api/v1/workspaces/{team.key}/branding/icon", {"value": None}, content_type="application/json"
    )

    assert response.status_code == 200
    assert response.json()["icon"] == ""
    assert storage == []


@pytest.mark.django_db
def test_upload_keeps_a_replaced_key_from_elsewhere(sample_team_with_owner_member, owner_client, storage):
    team = sample_team_with_owner_member.team
    _set_branding(team, logo="team_otherkey_logo_abc.png")

    response = owner_client.post(
        f"/api/v1/workspaces/{team.key}/branding/upload/logo",
        {"file": SimpleUploadedFile("logo.png", PNG, content_type="image/png")},
    )

    assert response.status_code == 200
    assert response.json()["logo"].startswith(f"team_{team.key}_logo_")
    assert storage == []


@pytest.mark.django_db
def test_upload_deletes_the_replaced_own_key(sample_team_with_owner_member, owner_client, storage):
    team = sample_team_with_owner_member.team
    own_key = f"team_{team.key}_logo_old.png"
    _set_branding(team, logo=own_key)

    response = owner_client.post(
        f"/api/v1/workspaces/{team.key}/branding/upload/logo",
        {"file": SimpleUploadedFile("logo.png", PNG, content_type="image/png")},
    )

    assert response.status_code == 200
    assert storage == [own_key]


@pytest.mark.django_db
def test_branding_form_removal_keeps_a_key_from_elsewhere(sample_team_with_owner_member, owner_client, storage):
    team = sample_team_with_owner_member.team
    _set_branding(team, icon="team_otherkey_icon_abc.png")

    response = owner_client.post(
        reverse("teams:team_branding", kwargs={"team_key": team.key}),
        {"brand_color": "#123456", "accent_color": "#654321", "icon_pending_deletion": "true"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    team.refresh_from_db()
    assert team.branding_info["icon"] == ""
    assert storage == []
