"""Plugin settings must be authorized against the URL workspace, not the caller's session
workspace (cross-workspace IDOR class)."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from sbomify.apps.plugins.apis import UpdateTeamPluginSettingsRequest, update_team_plugin_settings
from sbomify.apps.teams.models import Workspace


@pytest.mark.django_db
def test_plugin_settings_write_denies_cross_workspace(sample_team_with_owner_member):
    """A user who owns their own workspace must not update another workspace's plugin settings."""
    attacker = sample_team_with_owner_member.user  # owner of their own workspace only
    victim = Workspace.objects.create(name="Victim WS")  # Team.save() populates .key

    req = RequestFactory().post("/")
    req.user = attacker
    payload = UpdateTeamPluginSettingsRequest(enabled_plugins=[], plugin_configs=None)

    status, _body = update_team_plugin_settings(req, victim.key, payload)
    assert status == 403

    # Control: the attacker CAN update their own workspace's settings.
    own_status, _ = update_team_plugin_settings(req, sample_team_with_owner_member.team.key, payload)
    assert own_status == 200


@pytest.mark.django_db
def test_plugin_settings_write_denies_anonymous(sample_team_with_owner_member):
    """An unauthenticated request is a clean 403, not a 500 from the Member lookup."""
    req = RequestFactory().post("/")
    req.user = AnonymousUser()
    payload = UpdateTeamPluginSettingsRequest(enabled_plugins=[], plugin_configs=None)

    status, _body = update_team_plugin_settings(req, sample_team_with_owner_member.team.key, payload)
    assert status == 403
