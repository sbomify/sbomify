"""Deleting a contact profile you just created.

The profile list is rendered by two views: the list endpoint, and the form
endpoint after a create or an update. The delete modal inside it used to post to
whatever URL had rendered it, so a profile deleted straight after being created
posted to the form endpoint, which validates the create form and answered

    * name
      * This field is required.

for a request that was never trying to create anything. Reloading the tab first
made it work, which is what made the report read as intermittent.
"""

from __future__ import annotations

import re

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import ContactProfile, Member


def _delete_form_action(html: str) -> str:
    """The URL the delete modal's form posts to."""
    form = re.search(r'<form id="delete-contact-profile-modal-form".*?>', html, re.S)
    assert form, "delete modal not rendered"
    action = re.search(r'hx-post="([^"]+)"', form.group(0))
    assert action, "delete modal form has no hx-post"
    return action.group(1)


@pytest.mark.django_db
class TestDeletingAProfileYouJustCreated:
    @pytest.fixture
    def signed_in(self, sample_team_with_owner_member: Member) -> tuple[Client, Member]:
        client = Client()
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        return client, sample_team_with_owner_member

    @staticmethod
    def _create(client: Client, team_key: str, name: str):
        """Create a profile the way the form does, and get the list back."""
        return client.post(
            reverse("teams:contact_profiles_form", args=[team_key]),
            {
                "name": name,
                "entities-TOTAL_FORMS": "0",
                "entities-INITIAL_FORMS": "0",
                "entities-MIN_NUM_FORMS": "0",
                "entities-MAX_NUM_FORMS": "1000",
            },
            headers={"hx-request": "true"},
        )

    def test_the_delete_form_points_at_the_list_whichever_view_rendered_it(self, signed_in) -> None:
        client, member = signed_in
        list_url = reverse("teams:contact_profiles_list", args=[member.team.key])

        from_list = client.get(list_url, headers={"hx-request": "true"}).content.decode()
        from_create = self._create(client, member.team.key, "test").content.decode()

        assert _delete_form_action(from_list) == list_url
        assert _delete_form_action(from_create) == list_url

    def test_a_profile_created_then_deleted_goes_away(self, signed_in) -> None:
        """The reported sequence: add a profile, then delete it without reloading."""
        client, member = signed_in
        created = self._create(client, member.team.key, "test")
        profile = ContactProfile.objects.get(team=member.team, name="test")

        response = client.post(
            _delete_form_action(created.content.decode()),
            {"_method": "DELETE", "profile_id": str(profile.id)},
            headers={"hx-request": "true"},
        )

        assert response.status_code == 200
        assert "This field is required" not in response.content.decode()
        assert not ContactProfile.objects.filter(pk=profile.pk).exists()

    def test_deleting_after_a_reload_still_works(self, signed_in) -> None:
        """The path that always worked, so the fix does not trade one for the other."""
        client, member = signed_in
        self._create(client, member.team.key, "test")
        profile = ContactProfile.objects.get(team=member.team, name="test")
        list_url = reverse("teams:contact_profiles_list", args=[member.team.key])
        reloaded = client.get(list_url, headers={"hx-request": "true"}).content.decode()

        response = client.post(
            _delete_form_action(reloaded),
            {"_method": "DELETE", "profile_id": str(profile.id)},
            headers={"hx-request": "true"},
        )

        assert response.status_code == 200
        assert not ContactProfile.objects.filter(pk=profile.pk).exists()
