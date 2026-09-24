"""A downgrade stops what the Community plan does not include.

Plan access used to be checked only when a workspace enabled a plugin, so a
workspace that fell to Community kept running Dependency Track, NTIA and FDA
checks on every upload and re-run, and its private products stayed private.
The downgrade now publishes products with the components and drops the plugins
the plan excludes; queueing and re-running refuse a plugin the plan excludes,
which also covers workspaces downgraded before this change.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.billing_helpers import downgrade_ended_subscription
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.plugins.tasks import enqueue_assessment
from sbomify.apps.sboms.models import SBOM, Component, Product
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db

DT = "dependency-track"
NTIA = "ntia-minimum-elements-2021"


def _sbom(team: Team) -> SBOM:
    component = Component.objects.create(name="app", team=team)
    return SBOM.objects.create(name="app", component=component, format="cyclonedx", format_version="1.6")


def _enable(team: Team, *plugins: str) -> None:
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": list(plugins)})


def test_downgrade_publishes_private_products(ensure_billing_plans, team_with_business_plan):
    product = Product.objects.create(name="private-product", team=team_with_business_plan, is_public=False)

    downgrade_ended_subscription(team_with_business_plan.pk)

    product.refresh_from_db()
    assert product.is_public


def test_downgrade_drops_plugins_the_community_plan_excludes(ensure_billing_plans, team_with_business_plan):
    _enable(team_with_business_plan, "osv", DT, NTIA)

    downgrade_ended_subscription(team_with_business_plan.pk)

    assert TeamPluginSettings.objects.get(team=team_with_business_plan).enabled_plugins == ["osv"]


def test_a_plugin_the_plan_excludes_is_not_queued(ensure_billing_plans, team_with_community_plan):
    # A Community workspace still holding a paid plugin, as one downgraded before this fix does.
    _enable(team_with_community_plan, DT)
    sbom = _sbom(team_with_community_plan)

    with patch("sbomify.apps.plugins.tasks.run_assessment_task") as task:
        queued = enqueue_assessment(sbom_id=sbom.id, plugin_name=DT, run_reason=RunReason.ON_UPLOAD)

    assert queued is False
    task.send_with_options.assert_not_called()


def test_a_plugin_the_plan_includes_is_queued(
    ensure_billing_plans, team_with_business_plan, django_capture_on_commit_callbacks
):
    _enable(team_with_business_plan, DT)
    sbom = _sbom(team_with_business_plan)

    with (
        patch("sbomify.apps.plugins.tasks.run_assessment_task") as task,
        django_capture_on_commit_callbacks(execute=True),
    ):
        queued = enqueue_assessment(sbom_id=sbom.id, plugin_name=DT, run_reason=RunReason.ON_UPLOAD)

    assert queued is True
    task.send_with_options.assert_called_once()


def test_rerun_refuses_a_plugin_the_plan_excludes(ensure_billing_plans, team_with_community_plan, sample_user):
    RegisteredPlugin.objects.update_or_create(
        name=DT,
        defaults={
            "display_name": "Dependency Track",
            "category": "security",
            "version": "1",
            "plugin_class_path": "sbomify.apps.plugins.builtins.dependency_track.DependencyTrackPlugin",
            "is_enabled": True,
        },
    )
    _enable(team_with_community_plan, DT)
    sbom = _sbom(team_with_community_plan)
    client = Client()
    setup_authenticated_client_session(client, team_with_community_plan, sample_user)

    with patch("sbomify.apps.plugins.apis.run_assessment_task") as task:
        response = client.post(
            reverse("api-1:rerun_assessment", kwargs={"sbom_id": sbom.id, "plugin_name": DT}),
        )

    assert response.status_code == 403
    task.send.assert_not_called()
