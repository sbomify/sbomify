from __future__ import annotations

import json
from html.parser import HTMLParser
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.teams.models import ContactEntity, ContactProfile, Member, Team


class DeleteFormParser(HTMLParser):
    action: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "delete-contact-profile-modal-form":
            self.action = attributes.get("hx-post")


def profile_form_data() -> dict[str, str]:
    return {
        "name": "Primary Contacts",
        "entities-TOTAL_FORMS": "1",
        "entities-INITIAL_FORMS": "0",
        "entities-0-name": "Example Corp",
        "entities-0-email": "support@example.com",
        "entities-0-is_manufacturer": "on",
        "entities-0-contacts-TOTAL_FORMS": "1",
        "entities-0-contacts-INITIAL_FORMS": "0",
        "entities-0-contacts-0-name": "Alice",
        "entities-0-contacts-0-email": "alice@example.com",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("extra_payload", [{}, {"entities": None}, {"entities": []}])
def test_api_rejects_empty_profile_without_changing_default(
    sample_team_with_owner_member: Member,
    authenticated_api_client: tuple[Client, AccessToken],
    extra_payload: dict[str, Any],
) -> None:
    workspace = sample_team_with_owner_member.team
    previous_default = ContactProfile.objects.create(team=workspace, name="Existing", is_default=True)
    client, token = authenticated_api_client

    response = client.post(
        f"/api/v1/workspaces/{workspace.key}/contact-profiles",
        json.dumps({"name": "Empty", "is_default": True, **extra_payload}),
        content_type="application/json",
        **get_api_headers(token),
    )

    assert response.status_code == 400
    assert "at least one entity" in response.json()["detail"]
    assert not ContactProfile.objects.filter(team=workspace, name="Empty").exists()
    previous_default.refresh_from_db()
    assert previous_default.is_default


@pytest.mark.django_db
@pytest.mark.parametrize("deleted_entity", [False, True])
def test_form_rejects_profile_without_entities(
    authenticated_web_client: Client, team_with_business_plan: Team, deleted_entity: bool
) -> None:
    workspace = team_with_business_plan
    data = profile_form_data()
    if deleted_entity:
        data["entities-0-DELETE"] = "on"
    else:
        data["entities-TOTAL_FORMS"] = "0"

    response = authenticated_web_client.post(
        reverse("teams:contact_profiles_form", args=[workspace.key]), data, HTTP_HX_REQUEST="true"
    )

    messages = json.loads(response["HX-Trigger"])["messages"]
    assert messages[0]["type"] == "error"
    assert "at least one entity" in messages[0]["message"]
    assert not ContactProfile.objects.filter(team=workspace, name=data["name"]).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("render_source", ["list", "create", "update"])
@pytest.mark.parametrize("incomplete_entity", [False, True])
def test_delete_incomplete_profile_from_every_list_render(
    authenticated_web_client: Client,
    team_with_business_plan: Team,
    render_source: str,
    incomplete_entity: bool,
) -> None:
    workspace = team_with_business_plan
    empty_profile = ContactProfile.objects.create(team=workspace, name="Empty profile")
    if incomplete_entity:
        ContactEntity.objects.create(profile=empty_profile, is_author=True)

    list_url = reverse("teams:contact_profiles_list", args=[workspace.key])
    create_url = reverse("teams:contact_profiles_form", args=[workspace.key])
    client = authenticated_web_client
    if render_source == "list":
        response = client.get(list_url, HTTP_HX_REQUEST="true")
    else:
        data = profile_form_data()
        response = client.post(create_url, data, HTTP_HX_REQUEST="true")
        profile = ContactProfile.objects.get(team=workspace, name=data["name"])
        if render_source == "update":
            entity = profile.entities.get()
            contact = entity.contacts.get()
            data.update(
                {
                    "entities-INITIAL_FORMS": "1",
                    "entities-0-id": entity.pk,
                    "entities-0-contacts-INITIAL_FORMS": "1",
                    "entities-0-contacts-0-id": contact.pk,
                }
            )
            response = client.post(
                reverse("teams:contact_profiles_detail_form", args=[workspace.key, profile.pk]),
                data,
                HTTP_HX_REQUEST="true",
            )

    assert response.status_code == 200
    parser = DeleteFormParser()
    parser.feed(response.content.decode())
    assert parser.action is not None
    deletion = client.post(parser.action, {"_method": "DELETE", "profile_id": empty_profile.pk}, HTTP_HX_REQUEST="true")

    assert not ContactProfile.objects.filter(pk=empty_profile.pk).exists()
    assert json.loads(deletion["HX-Trigger"])["refreshProfileList"] is True
    assert parser.action == list_url
