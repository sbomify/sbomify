"""Saving the settings page keeps the plugins the plan no longer includes.

A plan-gated plugin renders as a *disabled* checkbox, and a disabled checkbox
submits nothing. The save path replaced the whole list with what was submitted,
so a workspace that had Dependency Track on a paid plan lost the setting the
first time anyone pressed Save after a downgrade — silently, and reported as a
success. Upgrading again did not bring it back, because the record of what the
workspace had asked for was gone.

The payload now replaces only the plugins the caller could have spoken for;
entries the plan excludes are carried over. Nothing runs them meanwhile — see
test_paid_plugins_after_downgrade.py for the refusal at every queueing path —
and the settings page says so on the row.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db

DT = "dependency-track"
OSV = "osv"

PLUGINS = {
    DT: ("Dependency Track", "sbomify.apps.plugins.builtins.dependency_track.DependencyTrackPlugin"),
    OSV: ("OSV Vulnerability Scanner", "sbomify.apps.plugins.builtins.osv.OSVPlugin"),
}


@pytest.fixture
def registered_plugins() -> None:
    for name, (display_name, class_path) in PLUGINS.items():
        RegisteredPlugin.objects.update_or_create(
            name=name,
            defaults={
                "display_name": display_name,
                "category": "security",
                "version": "1.0.0",
                "plugin_class_path": class_path,
                "is_enabled": True,
            },
        )


def _api_url(team_key: str) -> str:
    return f"/api/v1/plugins/workspaces/{team_key}/settings"


def _stored(team: Team) -> list[str]:
    return TeamPluginSettings.objects.get(team=team).enabled_plugins


def _client(team: Team, user) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


def _enable(team: Team, *plugins: str) -> None:
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": list(plugins)})


class TestTheApi:
    def test_a_plugin_the_plan_excludes_survives_a_save(
        self, ensure_billing_plans, team_with_community_plan, sample_user, registered_plugins
    ):
        # As a workspace downgraded from Business looks: it asked for both.
        _enable(team_with_community_plan, DT, OSV)

        response = _client(team_with_community_plan, sample_user).put(
            _api_url(team_with_community_plan.key),
            data=json.dumps({"enabled_plugins": [OSV]}),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert set(_stored(team_with_community_plan)) == {DT, OSV}
        # And the response says so rather than claiming the shorter list it was sent.
        assert set(response.json()["enabled_plugins"]) == {DT, OSV}

    def test_the_setting_takes_effect_again_on_upgrade(
        self, ensure_billing_plans, team_with_community_plan, sample_user, registered_plugins
    ):
        _enable(team_with_community_plan, DT, OSV)
        client = _client(team_with_community_plan, sample_user)
        client.put(
            _api_url(team_with_community_plan.key),
            data=json.dumps({"enabled_plugins": [OSV]}),
            content_type="application/json",
        )

        team_with_community_plan.billing_plan = "business"
        team_with_community_plan.save(update_fields=["billing_plan"])

        body = client.get(_api_url(team_with_community_plan.key)).json()
        assert DT in body["enabled_plugins"]
        dt = next(p for p in body["available_plugins"] if p["name"] == DT)
        assert dt["has_access"] is True
        assert dt["requires_upgrade"] is False

    def test_a_plugin_the_plan_includes_can_still_be_turned_off(
        self, ensure_billing_plans, team_with_community_plan, sample_user, registered_plugins
    ):
        _enable(team_with_community_plan, DT, OSV)

        response = _client(team_with_community_plan, sample_user).put(
            _api_url(team_with_community_plan.key),
            data=json.dumps({"enabled_plugins": []}),
            content_type="application/json",
        )

        assert response.status_code == 200
        # OSV is on every plan, so the caller's empty list disables it. DT is not
        # the caller's to drop.
        assert _stored(team_with_community_plan) == [DT]

    def test_asking_for_a_plugin_the_plan_excludes_is_still_refused(
        self, ensure_billing_plans, team_with_community_plan, sample_user, registered_plugins
    ):
        _enable(team_with_community_plan)

        response = _client(team_with_community_plan, sample_user).put(
            _api_url(team_with_community_plan.key),
            data=json.dumps({"enabled_plugins": [DT]}),
            content_type="application/json",
        )

        assert response.status_code == 403
        assert _stored(team_with_community_plan) == []

    def test_a_workspace_on_the_plan_replaces_its_list_as_before(
        self, ensure_billing_plans, team_with_business_plan, sample_user, registered_plugins
    ):
        _enable(team_with_business_plan, DT, OSV)

        response = _client(team_with_business_plan, sample_user).put(
            _api_url(team_with_business_plan.key),
            data=json.dumps({"enabled_plugins": [OSV]}),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert _stored(team_with_business_plan) == [OSV]


class TestTheSettingsPage:
    def test_pressing_save_with_nothing_changed_keeps_the_gated_plugin(
        self, ensure_billing_plans, team_with_community_plan, sample_user, registered_plugins
    ):
        _enable(team_with_community_plan, DT, OSV)
        client = _client(team_with_community_plan, sample_user)
        url = reverse("plugins:team_plugin_settings", kwargs={"team_key": team_with_community_plan.key})

        # Exactly what the browser posts: the disabled Dependency Track checkbox
        # contributes nothing, the enabled OSV one contributes its value.
        response = client.post(url, data={"enabled_plugins": [OSV]})

        assert response.status_code == 200
        assert set(_stored(team_with_community_plan)) == {DT, OSV}

    def test_the_row_says_the_plugin_is_paused_rather_than_off(
        self, ensure_billing_plans, team_with_community_plan, sample_user, registered_plugins
    ):
        _enable(team_with_community_plan, DT)
        client = _client(team_with_community_plan, sample_user)
        url = reverse("plugins:team_plugin_settings", kwargs={"team_key": team_with_community_plan.key})

        body = client.get(url).content.decode()

        assert "Paused by your plan" in body

    def test_a_plugin_that_was_never_enabled_is_not_called_paused(
        self, ensure_billing_plans, team_with_community_plan, sample_user, registered_plugins
    ):
        _enable(team_with_community_plan, OSV)
        client = _client(team_with_community_plan, sample_user)
        url = reverse("plugins:team_plugin_settings", kwargs={"team_key": team_with_community_plan.key})

        body = client.get(url).content.decode()

        assert "Paused by your plan" not in body
        assert "Business plan required" in body
