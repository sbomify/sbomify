"""Every way an assessment run ends repaints the pages watching it."""

from __future__ import annotations

import pytest

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.announce import announce_assessment_settled
from sbomify.apps.plugins.orchestrator import PluginOrchestratorError
from sbomify.apps.plugins.tasks import run_assessment_task
from sbomify.apps.sboms.models import SBOM

pytestmark = pytest.mark.django_db


@pytest.fixture
def sbom(sample_team_with_owner_member) -> SBOM:
    component = Component.objects.create(name="c", team=sample_team_with_owner_member.team)
    return SBOM.objects.create(
        component=component, name="s", version="1.0", format="cyclonedx", format_version="1.6", sbom_filename="s.json"
    )


def test_it_names_the_component_so_a_table_can_scope_to_it(sbom, mocker) -> None:
    broadcast = mocker.patch("sbomify.apps.plugins.announce.broadcast_to_workspace")

    announce_assessment_settled(sbom.id, "osv", "failed")

    broadcast.assert_called_once_with(
        workspace_key=sbom.component.team.key,
        message_type="assessment_complete",
        data={"sbom_id": sbom.id, "component_id": sbom.component_id, "plugin_name": "osv", "status": "failed"},
    )


def test_an_sbom_already_gone_is_not_announced(mocker) -> None:
    broadcast = mocker.patch("sbomify.apps.plugins.announce.broadcast_to_workspace")

    announce_assessment_settled("missing", "osv", "failed")

    broadcast.assert_not_called()


def test_a_broker_failure_never_escapes(sbom, mocker) -> None:
    mocker.patch("sbomify.apps.plugins.announce.broadcast_to_workspace", side_effect=RuntimeError("down"))

    announce_assessment_settled(sbom.id, "osv", "failed")


def test_an_orchestrator_failure_is_announced(sbom, mocker) -> None:
    mocker.patch(
        "sbomify.apps.plugins.tasks.PluginOrchestrator.run_assessment",
        side_effect=PluginOrchestratorError("nope"),
    )
    announce = mocker.patch("sbomify.apps.plugins.tasks.announce_assessment_settled")

    run_assessment_task.fn(sbom_id=sbom.id, plugin_name="osv", run_reason="on_upload")

    announce.assert_called_once_with(sbom.id, "osv", "failed")
