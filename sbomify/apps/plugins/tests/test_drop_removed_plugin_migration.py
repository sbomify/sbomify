from datetime import timedelta
from importlib import import_module

import pytest
from django.apps import apps
from django.utils import timezone

from sbomify.apps.plugins.models import TeamPluginSettings
from sbomify.apps.teams.models import Team

migration = import_module("sbomify.apps.plugins.migrations.0019_drop_cra_compliance_from_team_settings")


@pytest.mark.django_db
def test_removed_plugin_is_dropped_from_settings(sample_team) -> None:
    stale = TeamPluginSettings.objects.create(
        team=sample_team,
        enabled_plugins=["ntia-minimum-elements-2021", "cra-compliance-2024", "osv"],
        plugin_configs={"cra-compliance-2024": {"strict": True}, "osv": {"a": 1}},
    )
    clean = TeamPluginSettings.objects.create(
        team=Team.objects.create(name="Other"),
        enabled_plugins=["osv"],
        plugin_configs={"osv": {"a": 1}},
    )

    long_ago = timezone.now() - timedelta(days=30)
    TeamPluginSettings.objects.update(updated_at=long_ago)

    migration.drop_removed_plugin(apps, None)

    stale.refresh_from_db()
    clean.refresh_from_db()
    assert stale.enabled_plugins == ["ntia-minimum-elements-2021", "osv"]
    assert stale.plugin_configs == {"osv": {"a": 1}}
    assert clean.enabled_plugins == ["osv"]
    assert clean.plugin_configs == {"osv": {"a": 1}}
    assert stale.updated_at > long_ago
    assert clean.updated_at == long_ago
