"""Tests for the dependency-completion signal handler.

When an upstream plugin (e.g. ``sbom-verification``) completes AFTER a
dependent plugin (e.g. ``bsi-tr03183-v2.1-compliance`` — depends on
``category=attestation``) has already evaluated, the dependent's stored
finding is stale. The signal handler in ``sbomify.apps.plugins.signals``
detects this case and re-enqueues the dependent so its verdict reflects
the now-completed upstream run.

The race the handler closes:

    T+0s   → SBOM uploaded, all 6 AssessmentRuns created (eager-pending fix).
    T+1s   → BSI runs. Sees zero completed attestation runs. Writes
             "No attestation plugin has been run" finding.
    T+120s → sbom-verification fires (after ATTESTATION_DELAY_MS).
    T+121s → sbom-verification completes → signal triggers BSI re-run.
    T+122s → BSI re-runs, sees the now-completed attestation, writes
             "Passing attestation(s): sbom-verification".
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Team


pytestmark = pytest.mark.django_db


@pytest.fixture
def test_team(db) -> Team:
    BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "max_products": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    team = Team.objects.create(name="Dep-Trigger Test Team", billing_plan="community")
    yield team
    team.delete()


@pytest.fixture
def test_component(test_team: Team):
    component = Component.objects.create(team=test_team, name="Dep-Trigger Test Component")
    yield component
    component.delete()


@pytest.fixture
def test_sbom(test_component):
    sbom = SBOM.objects.create(
        name="dep-trigger-test-sbom",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="test.json",
        component=test_component,
    )
    yield sbom
    sbom.delete()


@pytest.fixture
def team_settings_all_enabled(test_team, attestation_plugin, compliance_plugin_with_attestation_dep):
    """The team has both the upstream and the dependent enabled.

    Real-world enable/disable lives on ``TeamPluginSettings.enabled_plugins`` —
    not the global ``RegisteredPlugin.is_enabled`` switch — so most tests
    need this fixture to opt the team into the relevant plugins.
    """
    settings, _ = TeamPluginSettings.objects.get_or_create(
        team=test_team,
        defaults={
            "enabled_plugins": [attestation_plugin.name, compliance_plugin_with_attestation_dep.name],
            "plugin_configs": {},
        },
    )
    if not settings.enabled_plugins:
        settings.enabled_plugins = [attestation_plugin.name, compliance_plugin_with_attestation_dep.name]
        settings.save(update_fields=["enabled_plugins"])
    return settings


@pytest.fixture
def attestation_plugin(db):
    """A registered attestation-category plugin (mirrors sbom-verification)."""
    return RegisteredPlugin.objects.create(
        name="test-attestation",
        display_name="Test Attestation",
        description="Attestation source",
        category="attestation",
        version="2.0.0",
        plugin_class_path="tests.fake.AttestationPlugin",
        is_enabled=True,
        is_builtin=False,
    )


@pytest.fixture
def compliance_plugin_with_attestation_dep(db):
    """A compliance plugin that depends on the attestation category (mirrors BSI)."""
    return RegisteredPlugin.objects.create(
        name="test-bsi",
        display_name="Test BSI",
        description="Compliance with attestation requirement",
        category="compliance",
        version="1.0.0",
        plugin_class_path="tests.fake.BSIPlugin",
        is_enabled=True,
        is_builtin=False,
        dependencies={"requires_one_of": [{"type": "category", "value": "attestation"}]},
    )


@pytest.fixture
def unrelated_plugin(db):
    """A plugin with no dependency on attestation — must NOT be re-fired."""
    return RegisteredPlugin.objects.create(
        name="test-unrelated",
        display_name="Test Unrelated",
        description="No deps",
        category="security",
        version="1.0.0",
        plugin_class_path="tests.fake.UnrelatedPlugin",
        is_enabled=True,
        is_builtin=False,
    )


def _make_run(sbom, plugin_name: str, category: str, status: str, completed_at=None) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom_id=sbom.id,
        plugin_name=plugin_name,
        plugin_version="1.0.0",
        plugin_config_hash="",
        category=category,
        run_reason="on_upload",
        status=status,
        completed_at=completed_at,
    )


class TestDependencyCompletionTrigger:
    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_completing_upstream_refires_stale_dependent(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        team_settings_all_enabled,
    ):
        """When sbom-verification completes after BSI did, BSI is re-enqueued."""
        # Stale BSI run: completed BEFORE attestation upstream finishes.
        old_time = timezone.now() - timedelta(minutes=5)
        bsi_run = _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )
        assert bsi_run.completed_at == old_time

        # Now the upstream completes (this triggers the signal).
        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            _make_run(
                test_sbom,
                plugin_name=attestation_plugin.name,
                category=attestation_plugin.category,
                status=RunStatus.COMPLETED.value,
                completed_at=timezone.now(),
            )

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args.kwargs
        assert call_kwargs["plugin_name"] == compliance_plugin_with_attestation_dep.name
        assert call_kwargs["sbom_id"] == str(test_sbom.id)
        assert call_kwargs["run_reason"] == RunReason.DEPENDENCY_CHANGED

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_no_refire_when_dependent_has_no_prior_run(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        team_settings_all_enabled,
    ):
        """A dependent that has never been queued gets its own ON_UPLOAD enqueue.

        The signal must not compete with that — refire is a *refresh*
        for stale verdicts, not a substitute for the initial run.
        """
        # No BSI run exists for this SBOM at all.
        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            _make_run(
                test_sbom,
                plugin_name=attestation_plugin.name,
                category=attestation_plugin.category,
                status=RunStatus.COMPLETED.value,
                completed_at=timezone.now(),
            )

        mock_enqueue.assert_not_called()

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_no_refire_when_dependent_already_newer(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        team_settings_all_enabled,
    ):
        """If the dependent already ran AFTER the upstream, no refire needed.

        Without this guard, a dependent's own completion would re-trigger
        the signal in a ping-pong loop.
        """
        now = timezone.now()
        future = now + timedelta(seconds=10)

        # Dependent already saw a completed snapshot more recent than the
        # upstream we're about to complete.
        _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=future,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            _make_run(
                test_sbom,
                plugin_name=attestation_plugin.name,
                category=attestation_plugin.category,
                status=RunStatus.COMPLETED.value,
                completed_at=now,
            )

        mock_enqueue.assert_not_called()

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_no_refire_when_dependent_has_inflight_run(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        team_settings_all_enabled,
    ):
        """A pending/running dependent already covers the refresh — don't double-queue.

        Without this guard, a sequence of upstream completions (e.g. two
        attestation sources finishing back to back) would queue
        duplicate refresh tasks while the first one is still pending.
        """
        old_time = timezone.now() - timedelta(minutes=5)
        # Earlier completed run — would normally trigger a refire …
        _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )
        # … but a refresh is already queued/running.
        _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.PENDING.value,
            completed_at=None,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            _make_run(
                test_sbom,
                plugin_name=attestation_plugin.name,
                category=attestation_plugin.category,
                status=RunStatus.COMPLETED.value,
                completed_at=timezone.now(),
            )

        mock_enqueue.assert_not_called()

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_unrelated_plugins_not_refired(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        unrelated_plugin,
        test_team,
    ):
        """A plugin with no dependency on this upstream is left alone."""
        # Team has all three opted in.
        TeamPluginSettings.objects.update_or_create(
            team=test_team,
            defaults={
                "enabled_plugins": [
                    attestation_plugin.name,
                    compliance_plugin_with_attestation_dep.name,
                    unrelated_plugin.name,
                ],
                "plugin_configs": {},
            },
        )
        old_time = timezone.now() - timedelta(minutes=5)
        _make_run(
            test_sbom,
            plugin_name=unrelated_plugin.name,
            category=unrelated_plugin.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )
        # Also create a stale BSI to confirm only-dependents-fire.
        _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            _make_run(
                test_sbom,
                plugin_name=attestation_plugin.name,
                category=attestation_plugin.category,
                status=RunStatus.COMPLETED.value,
                completed_at=timezone.now(),
            )

        # Only BSI fires; the unrelated plugin doesn't.
        called_plugins = {c.kwargs["plugin_name"] for c in mock_enqueue.call_args_list}
        assert called_plugins == {compliance_plugin_with_attestation_dep.name}

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_non_completed_status_does_not_trigger(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        team_settings_all_enabled,
    ):
        """Pending/running/failed runs do NOT cascade to dependents."""
        old_time = timezone.now() - timedelta(minutes=5)
        _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            for status in (RunStatus.PENDING.value, RunStatus.RUNNING.value, RunStatus.FAILED.value):
                _make_run(
                    test_sbom,
                    plugin_name=attestation_plugin.name,
                    category=attestation_plugin.category,
                    status=status,
                    completed_at=None,
                )

        mock_enqueue.assert_not_called()

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_team_disabled_dependent_not_refired(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        test_team,
    ):
        """If the SBOM's TEAM has not opted into the dependent, don't fire it.

        Real-world enable/disable lives on ``TeamPluginSettings.enabled_plugins``,
        not the global ``RegisteredPlugin.is_enabled`` flag — the signal
        must respect that gate.
        """
        # Team has only the upstream enabled, NOT the dependent.
        TeamPluginSettings.objects.update_or_create(
            team=test_team,
            defaults={"enabled_plugins": [attestation_plugin.name], "plugin_configs": {}},
        )

        old_time = timezone.now() - timedelta(minutes=5)
        _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            _make_run(
                test_sbom,
                plugin_name=attestation_plugin.name,
                category=attestation_plugin.category,
                status=RunStatus.COMPLETED.value,
                completed_at=timezone.now(),
            )

        mock_enqueue.assert_not_called()

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_team_plugin_config_passed_to_refire(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        test_team,
    ):
        """Re-enqueued dependent runs with the team's stored plugin_config.

        Without this, a refresh would silently use defaults and could
        produce different verdicts than the team's normal scan would.
        """
        TeamPluginSettings.objects.update_or_create(
            team=test_team,
            defaults={
                "enabled_plugins": [
                    attestation_plugin.name,
                    compliance_plugin_with_attestation_dep.name,
                ],
                "plugin_configs": {
                    compliance_plugin_with_attestation_dep.name: {"strict_mode": True},
                },
            },
        )

        old_time = timezone.now() - timedelta(minutes=5)
        _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            _make_run(
                test_sbom,
                plugin_name=attestation_plugin.name,
                category=attestation_plugin.category,
                status=RunStatus.COMPLETED.value,
                completed_at=timezone.now(),
            )

        mock_enqueue.assert_called_once()
        assert mock_enqueue.call_args.kwargs["config"] == {"strict_mode": True}

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_plugin_name_dependency_also_triggers(
        self,
        test_sbom,
        attestation_plugin,
        test_team,
    ):
        """A dependent that targets a specific plugin by name (not category) also fires."""
        named_dep = RegisteredPlugin.objects.create(
            name="test-named-dep",
            display_name="Test Named Dep",
            description="Depends specifically on test-attestation",
            category="compliance",
            version="1.0.0",
            plugin_class_path="tests.fake.NamedDep",
            is_enabled=True,
            is_builtin=False,
            dependencies={"requires_one_of": [{"type": "plugin", "value": "test-attestation"}]},
        )
        TeamPluginSettings.objects.update_or_create(
            team=test_team,
            defaults={
                "enabled_plugins": [attestation_plugin.name, named_dep.name],
                "plugin_configs": {},
            },
        )

        old_time = timezone.now() - timedelta(minutes=5)
        _make_run(
            test_sbom,
            plugin_name=named_dep.name,
            category=named_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            _make_run(
                test_sbom,
                plugin_name=attestation_plugin.name,
                category=attestation_plugin.category,
                status=RunStatus.COMPLETED.value,
                completed_at=timezone.now(),
            )

        mock_enqueue.assert_called_once()
        assert mock_enqueue.call_args.kwargs["plugin_name"] == named_dep.name


class TestQuerySetUpdateBypassesPostSave:
    """``finalize_retry_exhausted`` writes COMPLETED via ``QuerySet.update()``,
    which bypasses Django's ``post_save`` signals. The orchestrator must
    invoke the dependent-trigger helper directly so that the BSI/sbom-verification
    cascade still runs after a retry-exhausted completion."""

    @patch("sbomify.apps.plugins.signals.run_on_commit", new=lambda f: f())
    def test_finalize_retry_exhausted_cascades_dependents(
        self,
        test_sbom,
        attestation_plugin,
        compliance_plugin_with_attestation_dep,
        team_settings_all_enabled,
    ):
        """A retry-exhausted finalisation re-fires stale dependents."""
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator

        # Stale BSI run.
        old_time = timezone.now() - timedelta(minutes=5)
        _make_run(
            test_sbom,
            plugin_name=compliance_plugin_with_attestation_dep.name,
            category=compliance_plugin_with_attestation_dep.category,
            status=RunStatus.COMPLETED.value,
            completed_at=old_time,
        )

        # Pending sbom-verification that we'll finalise via the orchestrator.
        sv_run = _make_run(
            test_sbom,
            plugin_name=attestation_plugin.name,
            category=attestation_plugin.category,
            status=RunStatus.PENDING.value,
            completed_at=None,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            PluginOrchestrator().finalize_retry_exhausted(str(sv_run.id), "GitHub returned 404")

        # Even though finalize uses ``.update()``, the dependent-trigger
        # cascade must still fire BSI.
        mock_enqueue.assert_called_once()
        assert mock_enqueue.call_args.kwargs["plugin_name"] == compliance_plugin_with_attestation_dep.name
        assert mock_enqueue.call_args.kwargs["run_reason"] == RunReason.DEPENDENCY_CHANGED
