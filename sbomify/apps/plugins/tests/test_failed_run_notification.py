"""The notification a failed run raises says what happened and what it means.

It used to read "Assessment 'dependency-track' failed for <name>": the plugin's
slug, no consequence and no next step, under a modal titled "Warning". The
reader could not tell whether their vulnerability list was wrong, or where to
look. These tests pin a message that names the scanner, says the results were
not updated, and links to the artifact page that shows the error.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin, RunStatus
from sbomify.apps.plugins.orchestrator import PluginOrchestrator
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason
from sbomify.apps.plugins.tasks import _failed_run_notification
from sbomify.apps.sboms.models import SBOM

SCANNERS = [
    ("dependency-track", "Dependency Track"),
    ("osv", "OSV Vulnerability Scanner"),
]


def _register(name: str, display_name: str, category: AssessmentCategory) -> None:
    RegisteredPlugin.objects.update_or_create(
        name=name,
        defaults={
            "display_name": display_name,
            "description": display_name,
            "category": category.value,
            "version": "1.0.0",
            "plugin_class_path": f"tests.{name}",
            "is_enabled": True,
        },
    )


def _failed_run(team, plugin_name: str, category: AssessmentCategory, version: str = "2.4.0") -> AssessmentRun:
    component = Component.objects.create(name="Frontend Stack", team=team)
    sbom = SBOM.objects.create(
        name="Frontend Stack", version=version, component=component, format="cyclonedx", sbom_filename="s.json"
    )
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin_name,
        plugin_version="1.0.0",
        category=category.value,
        run_reason=RunReason.ON_UPLOAD.value,
        status=RunStatus.FAILED.value,
        error_message="DT project Frontend Stack@2.4.0 not visible after upload",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(("plugin_name", "display_name"), SCANNERS)
def test_a_failed_vulnerability_scan_explains_the_consequence(sample_team, plugin_name, display_name) -> None:
    _register(plugin_name, display_name, AssessmentCategory.SECURITY)
    run = _failed_run(sample_team, plugin_name, AssessmentCategory.SECURITY)

    notification = _failed_run_notification(run)

    assert notification["title"] == "Vulnerability scan failed"
    assert notification["message"] == (
        f"{display_name} could not scan Frontend Stack 2.4.0. "
        "Its vulnerability results were not updated, so new vulnerabilities may be missing. "
        "Open the SBOM to see the error."
    )
    assert notification["action_label"] == "View SBOM"
    assert notification["action_url"] == reverse(
        "core:component_item", args=[run.sbom.component_id, "sboms", run.sbom.id]
    )
    assert plugin_name not in notification["message"]


@pytest.mark.django_db
def test_other_assessments_get_a_neutral_message(sample_team) -> None:
    _register("ntia", "NTIA Minimum Elements", AssessmentCategory.COMPLIANCE)
    run = _failed_run(sample_team, "ntia", AssessmentCategory.COMPLIANCE)

    notification = _failed_run_notification(run)

    assert notification["title"] == "Assessment failed"
    assert notification["message"] == (
        "NTIA Minimum Elements could not check Frontend Stack 2.4.0, so no new result was recorded. "
        "Open the artifact to see the error."
    )
    assert notification["action_label"] == "View artifact"


@pytest.mark.django_db
def test_an_unversioned_artifact_and_unregistered_plugin_still_read_cleanly(sample_team) -> None:
    run = _failed_run(sample_team, "unregistered-scanner", AssessmentCategory.SECURITY, version="")

    message = _failed_run_notification(run)["message"]

    assert message.startswith("unregistered-scanner could not scan Frontend Stack. ")


@pytest.mark.django_db
def test_the_task_pushes_the_explained_notification(sample_team, monkeypatch) -> None:
    from sbomify.apps.plugins import tasks

    _register("dependency-track", "Dependency Track", AssessmentCategory.SECURITY)
    run = _failed_run(sample_team, "dependency-track", AssessmentCategory.SECURITY)
    monkeypatch.setattr(PluginOrchestrator, "run_assessment_by_name", lambda *args, **kwargs: run)

    with (
        patch.object(tasks, "broadcast_to_workspace"),
        patch.object(tasks, "push_notification") as push,
    ):
        tasks.run_assessment_task.fn(sbom_id=run.sbom_id, plugin_name="dependency-track", run_reason="on_upload")

    push.assert_called_once()
    kwargs = push.call_args.kwargs
    assert kwargs["workspace_key"] == sample_team.key
    assert kwargs["severity"] == "warning"
    assert kwargs["title"] == "Vulnerability scan failed"
    assert kwargs["message"].startswith("Dependency Track could not scan Frontend Stack 2.4.0.")
