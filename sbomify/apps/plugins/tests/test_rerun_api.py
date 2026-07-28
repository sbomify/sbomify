"""Manual assessment re-run.

Every layer below the API already supported a manual run (``RunReason.MANUAL``,
``AssessmentRun.triggered_by_user``, the task's ``triggered_by_user_id``) with
nothing able to call it, so these cover the endpoint that closes the gap and the
gates it has to hold.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_component,
    sample_product,
    sample_sbom,
)
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _url(sbom_id: str, plugin_name: str = "osv") -> str:
    return f"/api/v1/plugins/assessments/{sbom_id}/{plugin_name}/rerun"


@pytest.fixture
def enabled_plugin():
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
def owner_client(sample_sbom, sample_user):  # noqa: F811
    """A logged-in owner of the SBOM's workspace, with the plugin enabled.

    The enablement is part of the contract, not scenery: without a settings row
    the endpoint refuses, the same way every other path reads a missing row as
    "nothing enabled".
    """
    team = sample_sbom.component.team
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": ["osv"]})
    Member.objects.get_or_create(user=sample_user, team=team, defaults={"role": "owner"})
    client = Client()
    client.force_login(sample_user)
    session = client.session
    session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
    session.save()
    return client


class TestRerunSucceeds:
    def test_owner_queues_a_run(self, owner_client, sample_sbom, enabled_plugin, mocker):  # noqa: F811
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = owner_client.post(_url(sample_sbom.id))

        assert response.status_code == 202
        assert response.json() == {"sbom_id": sample_sbom.id, "plugin_name": "osv", "status": "queued"}
        send.assert_called_once()

    def test_the_run_is_attributed_to_the_caller(self, owner_client, sample_sbom, sample_user, enabled_plugin, mocker):  # noqa: F811
        """Without this the timeline cannot say who asked for the re-run."""
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        owner_client.post(_url(sample_sbom.id))

        kwargs = send.call_args.kwargs
        assert kwargs["run_reason"] == "manual"
        assert kwargs["triggered_by_user_id"] == sample_user.id


class TestRerunIsGated:
    def test_anonymous_is_rejected(self, sample_sbom, enabled_plugin, mocker):  # noqa: F811
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = Client().post(_url(sample_sbom.id))

        assert response.status_code in (401, 403)
        send.assert_not_called()

    def test_a_non_member_cannot_spend_the_queue(self, sample_sbom, enabled_plugin, django_user_model, mocker):  # noqa: F811
        outsider = django_user_model.objects.create_user(username="outsider", password="x")  # noqa: S106
        client = Client()
        client.force_login(outsider)
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = client.post(_url(sample_sbom.id))

        assert response.status_code == 403
        send.assert_not_called()

    def test_unknown_sbom_is_404(self, owner_client, enabled_plugin, mocker):
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = owner_client.post(_url("does-not-exist"))

        assert response.status_code == 404
        send.assert_not_called()

    def test_unregistered_plugin_is_404(self, owner_client, sample_sbom, mocker):  # noqa: F811
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = owner_client.post(_url(sample_sbom.id, "no-such-plugin"))

        assert response.status_code == 404
        send.assert_not_called()

    def test_globally_disabled_plugin_is_rejected(self, owner_client, sample_sbom, enabled_plugin, mocker):  # noqa: F811
        enabled_plugin.is_enabled = False
        enabled_plugin.save()
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = owner_client.post(_url(sample_sbom.id))

        assert response.status_code == 400
        send.assert_not_called()

    def test_a_workspace_with_no_settings_row_is_rejected(self, owner_client, sample_sbom, enabled_plugin, mocker):  # noqa: F811
        """A missing row means nothing is enabled, matching the task and signal
        paths, so it must not read as "everything allowed"."""
        TeamPluginSettings.objects.filter(team=sample_sbom.component.team).delete()
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = owner_client.post(_url(sample_sbom.id))

        assert response.status_code == 400
        send.assert_not_called()

    def test_a_plugin_the_workspace_turned_off_is_rejected(
        self, owner_client, sample_sbom, enabled_plugin, mocker
    ):  # noqa: F811
        """Otherwise a URL reaches past the workspace's own plugin settings and
        puts a result on a card it expects to stay empty."""
        TeamPluginSettings.objects.update_or_create(
            team=sample_sbom.component.team, defaults={"enabled_plugins": ["ntia-minimum-elements-2021"]}
        )
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = owner_client.post(_url(sample_sbom.id))

        assert response.status_code == 400
        send.assert_not_called()


def test_component_and_sbom_models_are_importable():
    """Guards the fixture imports above from silently drifting."""
    assert SBOM is not None and Component is not None and reverse is not None
