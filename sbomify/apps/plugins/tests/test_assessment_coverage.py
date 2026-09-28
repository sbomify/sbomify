"""The assessments card shows what did not run and what ran on older code.

The card used to list stored runs only. A plugin turned on after an upload had
no row, so no Run button, and a workspace with nothing turned on was told its
results would appear once processing completed, when nothing was scheduled.
A result from an older plugin version looked as current as a fresh one.
"""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin, TeamPluginSettings
from sbomify.apps.plugins.services.coverage import get_assessment_coverage
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db

NTIA = "ntia-minimum-elements-2021"
PQC = "pqc-readiness"


@pytest.fixture(autouse=True)
def billing_off(settings):
    """NTIA is plan-gated. The plan case turns billing back on for itself."""
    settings.BILLING = False


@pytest.fixture
def plugins():
    """Two registry rows: one that checks any SBOM, one gated on crypto assets."""
    ntia, _ = RegisteredPlugin.objects.update_or_create(
        name=NTIA,
        defaults={
            "display_name": "NTIA Minimum Elements (2021)",
            "category": "compliance",
            "version": "1.1.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
            "is_enabled": True,
        },
    )
    RegisteredPlugin.objects.update_or_create(
        name=PQC,
        defaults={
            "display_name": "PQC Readiness",
            "category": "compliance",
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.pqc.PqcReadinessPlugin",
            "is_enabled": True,
        },
    )
    return ntia


def _enable(team, *names: str) -> None:
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": list(names)})


def _run(sbom: SBOM, version: str, status: str = "completed") -> dict:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=NTIA,
        plugin_version=version,
        category="compliance",
        status=status,
        result={"summary": {"total_findings": 1, "pass_count": 1}, "findings": []},
    )
    return {"plugin_name": run.plugin_name, "plugin_version": run.plugin_version, "status": run.status}


def _coverage(sbom: SBOM, runs: list[dict] | None = None):
    result = get_assessment_coverage(sbom.id, sbom.component.team, runs or [])
    assert result.ok
    return result.value


class TestCoverage:
    def test_nothing_turned_on(self, sample_sbom, plugins):
        coverage = _coverage(sample_sbom)

        assert coverage.plugins_enabled is False
        assert coverage.unassessed == []

    def test_an_enabled_plugin_with_no_run_is_unassessed(self, sample_sbom, plugins):
        _enable(sample_sbom.component.team, NTIA)

        coverage = _coverage(sample_sbom)

        assert coverage.plugins_enabled is True
        assert coverage.unassessed == [{"plugin_name": NTIA, "plugin_display_name": "NTIA Minimum Elements (2021)"}]

    def test_a_plugin_that_ran_is_not_unassessed(self, sample_sbom, plugins):
        _enable(sample_sbom.component.team, NTIA)

        coverage = _coverage(sample_sbom, [_run(sample_sbom, "1.1.0")])

        assert coverage.unassessed == []
        assert coverage.outdated == {}

    def test_a_plugin_that_would_skip_this_artifact_is_not_offered(self, sample_sbom, plugins):
        """Run would queue nothing and the row would never clear."""
        sample_sbom.has_crypto_assets = False
        sample_sbom.save(update_fields=["has_crypto_assets"])
        _enable(sample_sbom.component.team, PQC)

        coverage = _coverage(sample_sbom)

        assert coverage.plugins_enabled is True
        assert coverage.unassessed == []

    def test_a_plugin_outside_the_plan_is_not_offered(self, sample_sbom, plugins, settings):
        settings.BILLING = True
        team = sample_sbom.component.team
        team.billing_plan = None
        team.save(update_fields=["billing_plan"])
        _enable(team, NTIA)

        coverage = _coverage(sample_sbom)

        assert coverage.plugins_enabled is False
        assert coverage.unassessed == []

    def test_a_result_from_an_older_version_is_outdated(self, sample_sbom, plugins):
        _enable(sample_sbom.component.team, NTIA)

        coverage = _coverage(sample_sbom, [_run(sample_sbom, "1.0.0")])

        assert coverage.outdated == {NTIA: "1.1.0"}

    def test_a_run_still_in_flight_is_not_outdated(self, sample_sbom, plugins):
        _enable(sample_sbom.component.team, NTIA)

        coverage = _coverage(sample_sbom, [_run(sample_sbom, "1.0.0", status="pending")])

        assert coverage.outdated == {}


class TestRegistryVersionMatchesTheClass:
    def test_every_builtin_registers_its_class_version(self):
        """A run records the class's VERSION. A registry row that disagrees would
        mark every result from that plugin as out of date, or none of them."""
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.orchestrator import load_plugin_class

        PluginsConfig._register_builtin_plugins(None)  # type: ignore[arg-type]

        for plugin in RegisteredPlugin.objects.filter(is_builtin=True, is_enabled=True):
            assert plugin.version == load_plugin_class(plugin.plugin_class_path).VERSION, plugin.name


def _page(client: Client, sbom: SBOM) -> str:
    response = client.get(reverse("core:component_item", args=[sbom.component_id, "sboms", sbom.id]))
    assert response.status_code == 200
    return response.content.decode()


def _client_as(sbom: SBOM, user, role: str) -> Client:
    team = sbom.component.team
    Member.objects.update_or_create(user=user, team=team, defaults={"role": role})
    client = Client()
    client.force_login(user)
    setup_test_session(client, team, user)
    return client


class TestArtifactPage:
    def test_no_plugins_says_so_and_links_admins_to_settings(self, sample_sbom, sample_user, plugins):
        html = _page(_client_as(sample_sbom, sample_user, "owner"), sample_sbom)

        assert "No assessments turned on" in html
        switch = reverse("teams:switch_team", args=[sample_sbom.component.team.key])
        assert f'href="{switch}?next={reverse("plugins:plugins_page")}"' in html
        assert "processing completes" not in html

    def test_no_plugins_offers_a_member_no_settings_link(self, sample_sbom, sample_user, plugins, django_user_model):
        member = django_user_model.objects.create_user(username="member", password="x")  # noqa: S106
        html = _page(_client_as(sample_sbom, member, "member"), sample_sbom)

        assert "No assessments turned on" in html
        assert reverse("plugins:plugins_page") not in html

    def test_an_unassessed_plugin_gets_a_row_and_a_run_button(self, sample_sbom, sample_user, plugins):
        _enable(sample_sbom.component.team, NTIA)

        html = _page(_client_as(sample_sbom, sample_user, "owner"), sample_sbom)

        assert "Not assessed" in html
        assert f"/api/v1/plugins/assessments/{sample_sbom.id}/" in html
        assert "done ? 'Queued' : 'Run'" in html
        assert "No assessments turned on" not in html

    def test_an_outdated_result_is_marked(self, sample_sbom, sample_user, plugins):
        _enable(sample_sbom.component.team, NTIA)
        _run(sample_sbom, "1.0.0")

        html = _page(_client_as(sample_sbom, sample_user, "owner"), sample_sbom)

        assert "Out of date" in html
        assert "Latest v1.1.0" in html

    def test_a_current_result_is_not_marked(self, sample_sbom, sample_user, plugins):
        _enable(sample_sbom.component.team, NTIA)
        _run(sample_sbom, "1.1.0")

        html = _page(_client_as(sample_sbom, sample_user, "owner"), sample_sbom)

        assert "Out of date" not in html
        assert "Not assessed" not in html


def test_the_row_offers_no_run_to_a_reader_who_cannot_run_it():
    html = render_to_string(
        "plugins/components/_unassessed_plugin_item.html.j2",
        {"plugin": {"plugin_name": NTIA, "plugin_display_name": "NTIA"}, "sbom_id": "abc", "can_rerun": False},
    )

    assert "Not assessed" in html
    assert "/rerun" not in html


class TestRunningANeverRunPlugin:
    """The Run button posts to the re-run endpoint, so its gate is that one."""

    def _post(self, client: Client, sbom: SBOM):
        return client.post(f"/api/v1/plugins/assessments/{sbom.id}/{NTIA}/rerun")

    def test_a_member_can_run_it(self, sample_sbom, plugins, django_user_model, mocker):
        _enable(sample_sbom.component.team, NTIA)
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")
        member = django_user_model.objects.create_user(username="member", password="x")  # noqa: S106

        response = self._post(_client_as(sample_sbom, member, "member"), sample_sbom)

        assert response.status_code == 202
        send.assert_called_once()

    def test_a_guest_cannot(self, sample_sbom, plugins, django_user_model, mocker):
        _enable(sample_sbom.component.team, NTIA)
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")
        guest = django_user_model.objects.create_user(username="guest", password="x")  # noqa: S106

        response = self._post(_client_as(sample_sbom, guest, "guest"), sample_sbom)

        assert response.status_code == 403
        send.assert_not_called()


class TestRunningNeedsThePlan:
    """A downgrade leaves a plugin in the enabled list; the endpoint still refuses it."""

    @pytest.fixture
    def on_plan(self, sample_sbom, settings):
        from sbomify.apps.billing.models import BillingPlan

        def _set(key: str):
            settings.BILLING = True
            BillingPlan.objects.get_or_create(
                key=key, defaults={"name": key.title(), "max_products": 1, "max_components": 5, "max_users": 2}
            )
            team = sample_sbom.component.team
            team.billing_plan = key
            team.save(update_fields=["billing_plan"])
            _enable(team, NTIA)

        return _set

    def test_a_plugin_outside_the_plan_is_refused(self, sample_sbom, sample_user, plugins, on_plan, mocker):
        on_plan("community")
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = _client_as(sample_sbom, sample_user, "owner").post(
            f"/api/v1/plugins/assessments/{sample_sbom.id}/{NTIA}/rerun"
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Your plan does not include NTIA Minimum Elements (2021)."
        send.assert_not_called()

    def test_a_plugin_on_the_plan_still_runs(self, sample_sbom, sample_user, plugins, on_plan, mocker):
        on_plan("business")
        send = mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")

        response = _client_as(sample_sbom, sample_user, "owner").post(
            f"/api/v1/plugins/assessments/{sample_sbom.id}/{NTIA}/rerun"
        )

        assert response.status_code == 202
        send.assert_called_once()


class TestRerunHiddenWhenRefused:
    def test_no_rerun_on_a_run_the_plan_excludes(self, sample_sbom, sample_user, plugins, settings):
        """The endpoint refuses it, so the card must not offer it."""
        settings.BILLING = True
        team = sample_sbom.component.team
        team.billing_plan = None
        team.save(update_fields=["billing_plan"])
        _enable(team, NTIA)
        _run(sample_sbom, "1.1.0")

        html = _page(_client_as(sample_sbom, sample_user, "owner"), sample_sbom)

        assert f"/api/v1/plugins/assessments/{sample_sbom.id}/" not in html

    def test_rerun_offered_on_a_run_the_workspace_runs(self, sample_sbom, sample_user, plugins):
        _enable(sample_sbom.component.team, NTIA)
        _run(sample_sbom, "1.1.0")

        html = _page(_client_as(sample_sbom, sample_user, "owner"), sample_sbom)

        assert f"/api/v1/plugins/assessments/{sample_sbom.id}/" in html


@pytest.mark.parametrize(("failing", "label"), [(1, "Issue"), (2, "Issues"), (0, "Issues")])
def test_the_issue_chip_agrees_with_its_count(failing: int, label: str):
    import re

    from django.utils.html import strip_tags

    status = {
        "overall_status": "has_failures" if failing else "all_pass",
        "total_assessments": 2,
        "passing_count": 2 - failing,
        "failing_count": failing,
        "pending_count": 0,
        "in_progress_count": 0,
        "skipped_count": 0,
    }
    html = render_to_string(
        "plugins/components/assessment_results_card.html.j2",
        {"assessment_runs": {"status_summary": status, "latest_runs": []}, "sbom_id": "abc"},
    )

    text = " ".join(strip_tags(html).split())
    assert re.search(rf"\b{failing} {label}\b", text), text
