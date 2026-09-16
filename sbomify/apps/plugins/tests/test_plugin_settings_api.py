"""Turning a workspace's plugins on and off over the API.

The logic has always been here: ``get_team_plugin_settings`` and
``update_team_plugin_settings`` validate against ``RegisteredPlugin``, check the
workspace's plan, and guard against rewriting another workspace's settings. They
were reachable only from the settings page, so a scanner could be enabled by a
person in a browser and not from CI, which is where the rest of our surface
lives.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_component,
    sample_product,
    sample_sbom,
)
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _url(team_key: str) -> str:
    return f"/api/v1/plugins/workspaces/{team_key}/settings"


@pytest.fixture
def registered_plugin():
    plugin, _ = RegisteredPlugin.objects.update_or_create(
        name="osv",
        defaults={
            "display_name": "OSV Vulnerability Scanner",
            "category": "security",
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.osv.OSVPlugin",
            "is_enabled": True,
        },
    )
    return plugin


@pytest.fixture
def owner(sample_sbom, sample_user):  # noqa: F811
    team = sample_sbom.component.team
    Member.objects.get_or_create(user=sample_user, team=team, defaults={"role": "owner"})
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": []})
    client = Client()
    client.force_login(sample_user)
    session = client.session
    session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
    session.save()
    return client, team


class TestReadingTheSettings:
    def test_it_lists_what_is_enabled_and_what_is_available(self, owner, registered_plugin):
        client, team = owner
        TeamPluginSettings.objects.filter(team=team).update(enabled_plugins=["osv"])

        response = client.get(_url(team.key))

        assert response.status_code == 200
        body = response.json()
        assert body["team_key"] == team.key
        assert body["enabled_plugins"] == ["osv"]
        assert any(p["name"] == "osv" for p in body["available_plugins"])
        # Declared on the schema, so it reaches a caller rather than being
        # dropped on the way out.
        assert body["team_plan"]

    def test_a_workspace_you_are_not_in_is_refused(self, owner, registered_plugin, guest_user):
        client, team = owner
        Member.objects.filter(team=team).delete()
        client.force_login(guest_user)

        assert client.get(_url(team.key)).status_code == 403

    def test_an_unknown_workspace_is_a_404(self, owner, registered_plugin):
        client, _team = owner

        assert client.get(_url("nosuchteam")).status_code == 404


class TestWritingTheSettings:
    def _put(self, client, team_key, payload):
        return client.put(_url(team_key), data=json.dumps(payload), content_type="application/json")

    def test_a_plugin_can_be_turned_on(self, owner, registered_plugin):
        client, team = owner

        response = self._put(client, team.key, {"enabled_plugins": ["osv"]})

        assert response.status_code == 200
        assert response.json()["enabled_plugins"] == ["osv"]
        assert TeamPluginSettings.objects.get(team=team).enabled_plugins == ["osv"]

    def test_a_plugin_can_be_turned_off_again(self, owner, registered_plugin):
        client, team = owner
        TeamPluginSettings.objects.filter(team=team).update(enabled_plugins=["osv"])

        response = self._put(client, team.key, {"enabled_plugins": []})

        assert response.status_code == 200
        assert TeamPluginSettings.objects.get(team=team).enabled_plugins == []

    def test_a_plugin_nobody_registered_is_refused(self, owner, registered_plugin):
        """Otherwise a typo turns into a setting that silently never runs."""
        client, team = owner

        response = self._put(client, team.key, {"enabled_plugins": ["osv", "not-a-plugin"]})

        assert response.status_code == 400
        assert TeamPluginSettings.objects.get(team=team).enabled_plugins == []

    def test_a_workspace_you_are_not_in_is_refused(self, owner, registered_plugin, guest_user):
        client, team = owner
        Member.objects.filter(team=team).delete()
        client.force_login(guest_user)

        assert self._put(client, team.key, {"enabled_plugins": ["osv"]}).status_code == 403
        assert TeamPluginSettings.objects.get(team=team).enabled_plugins == []


class TestAScopedTokenCannotExceedItself:
    """A token's scope narrows its owner, and the Member check cannot see it.

    Both handlers ask whether the caller is an owner or admin of the workspace,
    which is the whole question for the settings page. A token asks a second
    one: its owner may well be an admin and the token still be scoped to reads.
    """

    def _token_client(self, user, team, scopes):
        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.access_tokens.utils import create_personal_access_token

        encoded = create_personal_access_token(user)
        AccessToken.objects.create(user=user, encoded_token=encoded, description="scoped", team=team, scopes=scopes)
        return Client(), {"HTTP_AUTHORIZATION": f"Bearer {encoded}"}

    def test_a_read_only_token_may_not_change_them(self, owner, registered_plugin, sample_user):  # noqa: F811
        _session_client, team = owner
        client, headers = self._token_client(sample_user, team, ["sbom:read"])

        response = client.put(
            _url(team.key),
            data=json.dumps({"enabled_plugins": ["osv"]}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 403
        assert TeamPluginSettings.objects.get(team=team).enabled_plugins == []

    def test_a_read_only_token_may_not_read_them_either(self, owner, registered_plugin, sample_user):  # noqa: F811
        """The gate is on both verbs: the settings carry the workspace's plan."""
        _session_client, team = owner
        client, headers = self._token_client(sample_user, team, ["sbom:read"])

        assert client.get(_url(team.key), **headers).status_code == 403

    def test_a_token_scoped_to_workspace_management_may_read_them(self, owner, registered_plugin, sample_user):  # noqa: F811
        _session_client, team = owner
        TeamPluginSettings.objects.filter(team=team).update(enabled_plugins=["osv"])
        client, headers = self._token_client(sample_user, team, ["workspace:manage"])

        response = client.get(_url(team.key), **headers)

        assert response.status_code == 200
        assert response.json()["enabled_plugins"] == ["osv"]

    def test_a_token_scoped_to_workspace_management_may(self, owner, registered_plugin, sample_user):  # noqa: F811
        _session_client, team = owner
        client, headers = self._token_client(sample_user, team, ["workspace:manage"])

        response = client.put(
            _url(team.key),
            data=json.dumps({"enabled_plugins": ["osv"]}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200
        assert TeamPluginSettings.objects.get(team=team).enabled_plugins == ["osv"]
