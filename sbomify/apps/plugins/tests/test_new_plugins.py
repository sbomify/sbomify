"""Plugins registered after a workspace last saved its plugin settings are marked new."""

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings
from sbomify.apps.plugins.services.new_plugins import plugins_added_since_last_save
from sbomify.apps.teams.models import Team

NEW_BADGE = b'title="Added since this page was last saved"'


@pytest.fixture(autouse=True)
def built_in_plugins_registered_long_ago(db: None) -> None:
    RegisteredPlugin.objects.update(created_at=timezone.now() - timedelta(days=30))


def _register(name: str) -> RegisteredPlugin:
    return RegisteredPlugin.objects.create(
        name=name,
        display_name=f"{name} display",
        description="A plugin for these tests.",
        category="compliance",
        version="1.0.0",
        plugin_class_path="sbomify.apps.plugins.builtins.osv.OSVPlugin",
    )


def _saved_an_hour_ago(team: Team, enabled: list[str] | None = None) -> None:
    settings, _ = TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": enabled or []})
    TeamPluginSettings.objects.filter(pk=settings.pk).update(updated_at=timezone.now() - timedelta(hours=1))


def _settings_page(client: Client, team: Team) -> tuple[list[str], bytes]:
    response = client.get(
        reverse("plugins:team_plugin_settings", kwargs={"team_key": team.key}), HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200
    plugins = response.context["plugin_settings"]["available_plugins"]
    return [plugin["name"] for plugin in plugins if plugin["is_new"]], response.content


@pytest.mark.django_db
def test_only_plugins_registered_after_the_last_save_are_new(team_with_business_plan: Team) -> None:
    _saved_an_hour_ago(team_with_business_plan)
    _register("newer-plugin")

    assert plugins_added_since_last_save(team_with_business_plan.key).value == {"newer-plugin"}


@pytest.mark.django_db
def test_a_workspace_that_never_saved_has_nothing_new(team_with_business_plan: Team) -> None:
    _register("newer-plugin")

    assert plugins_added_since_last_save(team_with_business_plan.key).value == set()


@pytest.mark.django_db
def test_disabled_registry_plugins_are_never_new(team_with_business_plan: Team) -> None:
    _saved_an_hour_ago(team_with_business_plan)
    hidden = _register("hidden-plugin")
    RegisteredPlugin.objects.filter(pk=hidden.pk).update(is_enabled=False)

    assert plugins_added_since_last_save(team_with_business_plan.key).value == set()


@pytest.mark.django_db
def test_settings_page_marks_new_plugins_until_saved(
    authenticated_web_client: Client, team_with_business_plan: Team
) -> None:
    _register("enabled-plugin")
    _saved_an_hour_ago(team_with_business_plan, enabled=["enabled-plugin"])
    _register("newer-plugin")
    _register("also-newer-enabled")
    TeamPluginSettings.objects.filter(team=team_with_business_plan).update(
        enabled_plugins=["enabled-plugin", "also-newer-enabled"]
    )

    new, content = _settings_page(authenticated_web_client, team_with_business_plan)
    assert new == ["newer-plugin"]
    assert content.count(NEW_BADGE) == 1

    authenticated_web_client.post(
        reverse("plugins:team_plugin_settings", kwargs={"team_key": team_with_business_plan.key}),
        {"enabled_plugins": ["enabled-plugin", "also-newer-enabled"]},
        HTTP_HX_REQUEST="true",
    )

    new, content = _settings_page(authenticated_web_client, team_with_business_plan)
    assert new == []
    assert NEW_BADGE not in content


@pytest.mark.django_db
def test_plugins_the_plan_does_not_include_are_not_marked_new(
    authenticated_web_client: Client, team_with_business_plan: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    _saved_an_hour_ago(team_with_business_plan)
    _register("gated-plugin")
    monkeypatch.setattr("sbomify.apps.plugins.apis.team_has_plugin_access", lambda team, name: name != "gated-plugin")

    new, content = _settings_page(authenticated_web_client, team_with_business_plan)
    assert new == []
    assert NEW_BADGE not in content
