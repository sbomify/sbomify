"""Tests for the scan-once-per-SBOM model (sbomify/sbomify#881, #873).

Under the new model:
  - SBOM upload triggers ONE run per (SBOM, plugin), regardless of how many
    releases the SBOM is linked to.
  - The orchestrator populates AssessmentRun.releases M2M at run completion
    from the current ReleaseArtifact state.
  - ReleaseArtifact creation does NOT trigger a new scan — it enqueues a
    lightweight attach_release_to_runs_task that adds the release to the
    existing run's M2M and asks plugins to sync downstream state.
  - Cron iterates unique SBOM ids, not (sbom, release) pairs.

These tests replace the earlier per-release trigger tests that assumed one
run per (SBOM, release, plugin). See test_release_dependent_trigger.py for
the remaining cross-cutting safety checks (cross-team, suppression context,
document-artifact guards) that still apply in the new model.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.plugins.models import (
    AssessmentRun,
    AssessmentRunRelease,
    RegisteredPlugin,
    RunStatus,
    TeamPluginSettings,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, ScanMode
from sbomify.apps.plugins.sdk.results import PluginMetadata
from sbomify.apps.plugins.tasks import (
    attach_release_to_runs_task,
    detach_release_from_runs_task,
)
from sbomify.apps.sboms.models import SBOM


def _make_dt_plugin() -> None:
    RegisteredPlugin.objects.get_or_create(
        name="dependency-track",
        defaults={
            "display_name": "Dependency Track",
            "description": "DT",
            "category": AssessmentCategory.SECURITY.value,
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.dependency_track.DependencyTrackPlugin",
            "is_enabled": True,
        },
    )


def _make_ntia_plugin() -> None:
    RegisteredPlugin.objects.get_or_create(
        name="ntia-minimum-elements-2021",
        defaults={
            "display_name": "NTIA Minimum Elements (2021)",
            "description": "NTIA",
            "category": AssessmentCategory.COMPLIANCE.value,
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NtiaPlugin",
            "is_enabled": True,
        },
    )


def _enable_plugins(team, *names: str) -> TeamPluginSettings:
    settings, _ = TeamPluginSettings.objects.get_or_create(team=team)
    settings.enabled_plugins = list(set(settings.enabled_plugins or []) | set(names))
    settings.save()
    return settings


@pytest.mark.django_db
class TestUploadSignalEnqueuesOncePerSbom:
    """Upload signal fires one enqueue per plugin, no per-release loop."""

    def test_single_call_covers_all_enabled_plugins(self, sample_team_with_owner_member, monkeypatch):
        """The upload signal calls enqueue_assessments_for_sbom ONCE with no
        category filter and no release_id, regardless of how many releases
        the SBOM ends up linked to."""
        team = sample_team_with_owner_member.team
        _make_dt_plugin()
        _make_ntia_plugin()
        _enable_plugins(team, "dependency-track", "ntia-minimum-elements-2021")

        captured: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured.append(kwargs) or [],
        )
        monkeypatch.setattr(
            "sbomify.apps.core.services.transactions.run_on_commit",
            lambda fn: fn(),
        )

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        SBOM.objects.create(name="s", component=component, format="cyclonedx")

        # Exactly one call — no category filter, no release_id kwarg
        assert len(captured) == 1, f"Expected 1 enqueue call, got {len(captured)}"
        assert captured[0].get("only_categories") is None, (
            "Upload signal must not filter by category — enqueues all enabled plugins in one call"
        )
        assert "release_id" not in captured[0] or captured[0].get("release_id") is None, (
            "Upload signal must not thread a release_id — scan is per-SBOM, releases resolved at completion"
        )


@pytest.mark.django_db
class TestReleaseAssociationAttachesToExistingRun:
    """ReleaseArtifact create → attach to existing run, no rescan."""

    def test_signal_enqueues_attach_task_not_rescan(self, sample_team_with_owner_member, monkeypatch):
        """The ReleaseArtifact post_save handler enqueues an attach_release_to_runs_task
        dramatiq message — it does NOT call enqueue_assessments_for_sbom."""
        team = sample_team_with_owner_member.team
        _make_dt_plugin()
        _enable_plugins(team, "dependency-track")

        captured_enqueue_sbom: list[dict] = []
        captured_attach_calls: list[dict] = []

        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured_enqueue_sbom.append(kwargs) or [],
        )
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.attach_release_to_runs_task.send",
            lambda **kwargs: captured_attach_calls.append(kwargs),
        )
        monkeypatch.setattr(
            "sbomify.apps.core.services.transactions.run_on_commit",
            lambda fn: fn(),
        )

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")

        named_release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")
        captured_enqueue_sbom.clear()  # ignore the upload-time call
        captured_attach_calls.clear()

        ReleaseArtifact.objects.create(release=named_release, sbom=sbom)

        assert len(captured_enqueue_sbom) == 0, (
            "ReleaseArtifact create must NOT trigger a rescan — no enqueue_assessments_for_sbom calls expected"
        )
        assert len(captured_attach_calls) == 1, (
            f"Expected exactly one attach_release_to_runs_task.send call, got {len(captured_attach_calls)}"
        )
        assert captured_attach_calls[0]["sbom_id"] == sbom.id
        assert captured_attach_calls[0]["release_id"] == named_release.id

    def test_attach_fires_during_refresh_latest_artifacts(self, sample_team_with_owner_member, monkeypatch):
        """When refresh_latest_artifacts moves the latest pointer (under
        _suppress_collection_signals), the attach handler must still fire
        so the new SBOM gets the 'latest' tag in DT. Regression test for
        Viktor review #2."""
        team = sample_team_with_owner_member.team
        _make_dt_plugin()
        _enable_plugins(team, "dependency-track")

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        # sbom_v1 auto-added to latest release by the upload signal
        sbom_v1 = SBOM.objects.create(name="v1", component=component, format="cyclonedx")
        # component_v2 is NOT attached to the product, so sbom_v2 won't auto-add to latest
        component_v2 = Component.objects.create(name="c2", team=team)
        sbom_v2 = SBOM.objects.create(name="v2", component=component_v2, format="cyclonedx")

        captured_attach_calls: list[dict] = []

        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.attach_release_to_runs_task.send",
            lambda **kwargs: captured_attach_calls.append(kwargs),
        )
        monkeypatch.setattr(
            "sbomify.apps.core.services.transactions.run_on_commit",
            lambda fn: fn(),
        )

        from sbomify.apps.core.models import _suppress_collection_signals

        latest_release = Release.get_or_create_latest_release(product)
        captured_attach_calls.clear()

        # Simulate what refresh_latest_artifacts does when moving the latest
        # pointer: create a new ReleaseArtifact under suppression context.
        token = _suppress_collection_signals.set(True)
        try:
            ReleaseArtifact.objects.create(release=latest_release, sbom=sbom_v2)
        finally:
            _suppress_collection_signals.reset(token)

        # The attach task MUST fire even under suppression — otherwise sbom_v2
        # wouldn't get the "latest" tag until the next cron re-scan.
        attach_sbom_ids = [str(c.get("sbom_id")) for c in captured_attach_calls]
        assert str(sbom_v2.id) in attach_sbom_ids, (
            f"Attach handler must fire during refresh_latest_artifacts "
            f"(must NOT honor _suppress_collection_signals). Got: {attach_sbom_ids}"
        )


@pytest.mark.django_db
class TestAttachReleaseToRunsTask:
    """attach_release_to_runs_task adds the release to the M2M + syncs plugin hooks."""

    def test_adds_release_to_latest_completed_run_m2m(self, sample_team_with_owner_member):
        """Given a completed AssessmentRun for an SBOM and a new release
        linked to that SBOM, the task adds the release to the run's M2M."""
        team = sample_team_with_owner_member.team
        _make_ntia_plugin()

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")

        run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"pass_count": 5, "fail_count": 0}},
        )
        assert AssessmentRunRelease.objects.filter(assessment_run=run).count() == 0

        attach_release_to_runs_task.fn(sbom_id=str(sbom.id), release_id=str(release.id))

        assert AssessmentRunRelease.objects.filter(assessment_run=run, release=release).exists(), (
            "Task must add the release to the completed run's M2M"
        )

    def test_noop_when_no_completed_runs_yet(self, sample_team_with_owner_member):
        """If no completed runs exist for the SBOM (scan still in-flight),
        the task no-ops. The orchestrator picks up the release at completion."""
        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")

        result = attach_release_to_runs_task.fn(sbom_id=str(sbom.id), release_id=str(release.id))

        assert result == {"attached_runs": 0, "synced_plugins": []}

    def test_calls_sync_release_tags_when_plugin_implements_it(self, sample_team_with_owner_member, monkeypatch):
        """Plugins exposing a sync_release_tags hook (e.g. DT) get called
        with the new release so they can update downstream tag state."""
        team = sample_team_with_owner_member.team
        _make_dt_plugin()

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")

        run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="dependency-track",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.SECURITY.value,
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"total_findings": 0}},
        )

        sync_calls: list[dict] = []

        class FakeDT:
            def get_metadata(self):
                return PluginMetadata(
                    name="dependency-track",
                    version="1.0.0",
                    category=AssessmentCategory.SECURITY,
                    scan_mode=ScanMode.CONTINUOUS,
                )

            def sync_release_tags(self, *, sbom_id, run_id, release):
                sync_calls.append({"sbom_id": sbom_id, "run_id": run_id, "release": release})

        monkeypatch.setattr("sbomify.apps.plugins.tasks._load_plugin_by_name", lambda name: FakeDT())

        attach_release_to_runs_task.fn(sbom_id=str(sbom.id), release_id=str(release.id))

        assert len(sync_calls) == 1
        assert sync_calls[0]["sbom_id"] == str(sbom.id)
        assert sync_calls[0]["run_id"] == str(run.id)
        assert sync_calls[0]["release"].id == release.id

    def test_attaches_to_failed_run_without_tag_sync(self, sample_team_with_owner_member, monkeypatch):
        """FAILED runs get the M2M row (so next successful scan picks it up)
        but sync_release_tags is NOT called (no DT project to tag)."""
        team = sample_team_with_owner_member.team
        _make_dt_plugin()

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")

        failed_run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="dependency-track",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.SECURITY.value,
            run_reason="on_upload",
            status=RunStatus.FAILED.value,
            error_message="DT server unreachable",
        )

        sync_calls: list[dict] = []

        class FakeDT:
            def get_metadata(self):
                return PluginMetadata(
                    name="dependency-track",
                    version="1.0.0",
                    category=AssessmentCategory.SECURITY,
                    scan_mode=ScanMode.CONTINUOUS,
                )

            def sync_release_tags(self, *, sbom_id, run_id, release):
                sync_calls.append({"sbom_id": sbom_id})

        monkeypatch.setattr("sbomify.apps.plugins.tasks._load_plugin_by_name", lambda name: FakeDT())

        result = attach_release_to_runs_task.fn(sbom_id=str(sbom.id), release_id=str(release.id))

        # M2M row IS created (so next cron re-scan picks up the release)
        assert result["attached_runs"] == 1
        assert AssessmentRunRelease.objects.filter(assessment_run=failed_run, release=release).exists()

        # sync_release_tags is NOT called (failed run has no DT project)
        assert len(sync_calls) == 0
        assert result["synced_plugins"] == []

    @pytest.mark.parametrize(
        ("skip", "shipped", "rescan_started", "scans"),
        [
            pytest.param("dependency-track:not-tracked", True, False, True, id="skipped-as-not-monitored"),
            pytest.param("dependency-track:not-tracked", False, False, False, id="still-not-monitored"),
            pytest.param("dependency-track:not-enabled", True, False, False, id="skipped-for-another-reason"),
            pytest.param("dependency-track:not-tracked", True, True, False, id="scan-already-started"),
        ],
    )
    def test_scans_an_sbom_skipped_as_not_monitored_once_a_release_ships_it(
        self, sample_team_with_owner_member, monkeypatch, skip, shipped, rescan_started, scans
    ):
        """Its upload scan ran after a newer SBOM arrived and before the release shipped it,
        so the run is a skip and no scheduled scan is due to come back to it."""
        team = sample_team_with_owner_member.team
        _make_dt_plugin()
        settings = _enable_plugins(team, "dependency-track")
        settings.plugin_configs = {"dependency-track": {"dt_server_id": "pinned"}}
        settings.save()

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        sbom = SBOM.objects.create(name="s", version="1.0", component=component, format="cyclonedx")
        SBOM.objects.create(name="s", version="1.1", component=component, format="cyclonedx")
        release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")
        if shipped:
            ReleaseArtifact.objects.create(release=release, sbom=sbom)
        run = {
            "sbom": sbom,
            "plugin_name": "dependency-track",
            "plugin_version": "1.0.0",
            "plugin_config_hash": "abc",
            "category": AssessmentCategory.SECURITY.value,
            "run_reason": "on_upload",
        }
        AssessmentRun.objects.create(
            **run,
            status=RunStatus.COMPLETED.value,
            result={"findings": [{"id": skip}], "metadata": {"skipped": True}},
        )
        if rescan_started:
            AssessmentRun.objects.create(**run, status=RunStatus.PENDING.value)
        enqueued: list[dict] = []
        monkeypatch.setattr("sbomify.apps.plugins.tasks.enqueue_assessment", lambda **kwargs: enqueued.append(kwargs))

        attach_release_to_runs_task.fn(sbom_id=str(sbom.id), release_id=str(release.id))

        scan = {
            "sbom_id": str(sbom.id),
            "plugin_name": "dependency-track",
            "run_reason": RunReason.ON_RELEASE_ASSOCIATION,
            "config": {"dt_server_id": "pinned"},
            "release_id": str(release.id),
        }
        assert enqueued == ([scan] if scans else [])


@pytest.mark.django_db
class TestOrchestratorPopulatesM2MAtCompletion:
    """Orchestrator populates AssessmentRun.releases from current ReleaseArtifact state."""

    def test_sync_run_releases_copies_from_release_artifact(self, sample_team_with_owner_member):
        """_sync_run_releases reads ReleaseArtifact and creates matching M2M rows."""
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")

        # The SBOM upload auto-creates the 'latest' release and a ReleaseArtifact
        # linking the SBOM to it (via update_latest_release_on_sbom_created).
        release_latest = Release.get_or_create_latest_release(product)
        release_v1 = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")
        release_stable = Release.objects.create(product=product, name="stable/0.1")

        ReleaseArtifact.objects.get_or_create(release=release_latest, sbom=sbom)
        ReleaseArtifact.objects.create(release=release_v1, sbom=sbom)
        ReleaseArtifact.objects.create(release=release_stable, sbom=sbom)

        run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason="on_upload",
            status=RunStatus.RUNNING.value,
        )

        orchestrator = PluginOrchestrator()
        orchestrator._sync_run_releases(run, str(sbom.id))  # noqa: SLF001

        m2m_release_ids = set(run.releases.values_list("id", flat=True))
        assert m2m_release_ids == {release_latest.id, release_v1.id, release_stable.id}, (
            f"Expected all 3 releases in M2M, got {m2m_release_ids}"
        )

    def test_sync_run_releases_idempotent(self, sample_team_with_owner_member):
        """Running _sync_run_releases twice doesn't create duplicate M2M rows."""
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason="on_upload",
            status=RunStatus.RUNNING.value,
        )

        orchestrator = PluginOrchestrator()
        orchestrator._sync_run_releases(run, str(sbom.id))  # noqa: SLF001
        orchestrator._sync_run_releases(run, str(sbom.id))  # noqa: SLF001

        assert AssessmentRunRelease.objects.filter(assessment_run=run, release=release).count() == 1


@pytest.mark.django_db
class TestCronIteratesUniqueSboms:
    """Cron iterates unique SBOM ids (not release pairs) under the new model."""

    def test_cron_enqueues_once_per_sbom_not_per_release(self, sample_team_with_owner_member, monkeypatch):
        """A single SBOM linked to N releases → cron enqueues ONE scan, not N."""
        from sbomify.apps.plugins.tasks import _is_paid_team, _run_scheduled_security_scans

        team = sample_team_with_owner_member.team
        team.billing_plan = "business"
        team.save()

        _make_dt_plugin()
        _enable_plugins(team, "dependency-track")

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", sbom_filename="s.json")

        # Use the auto-created latest release (made by update_latest_release_on_sbom_created).
        r1 = Release.get_or_create_latest_release(product)
        r2 = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")
        r3 = Release.objects.create(product=product, name="stable/0.1")
        ReleaseArtifact.objects.get_or_create(release=r1, sbom=sbom)
        ReleaseArtifact.objects.create(release=r2, sbom=sbom)
        ReleaseArtifact.objects.create(release=r3, sbom=sbom)

        captured_enqueue_calls: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured_enqueue_calls.append(kwargs),
        )

        stats = _run_scheduled_security_scans(
            plugin_name="dependency-track",
            plan_filter=_is_paid_team,
            skip_hours=1,
            task_name="test_hourly_dt_scan",
            only_cyclonedx=True,
        )

        assert stats["assessments_enqueued"] == 1, (
            f"Expected exactly 1 enqueue per SBOM (not per release); got {stats['assessments_enqueued']}"
        )
        assert len(captured_enqueue_calls) == 1
        assert captured_enqueue_calls[0]["sbom_id"] == str(sbom.id)


@pytest.mark.django_db
class TestDetachReleaseFromRunsTask:
    """Stage 5 Issue A: detach_release_from_runs_task removes the M2M row
    and asks plugins to re-sync downstream tag state."""

    def test_removes_release_from_m2m_and_syncs_plugins(self, sample_team_with_owner_member, monkeypatch):
        """When a ReleaseArtifact is removed, the detach task drops the M2M row
        and triggers a tag re-sync from the remaining canonical set."""
        team = sample_team_with_owner_member.team
        _make_ntia_plugin()
        _make_dt_plugin()

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")

        release_to_remove = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")
        release_keep = Release.objects.create(product=product, name="v2.0.0", version="2.0.0")

        run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="dependency-track",
            plugin_version="1.1.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.SECURITY.value,
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"total_findings": 0}},
        )
        AssessmentRunRelease.objects.create(assessment_run=run, release=release_to_remove)
        AssessmentRunRelease.objects.create(assessment_run=run, release=release_keep)

        sync_calls: list[dict] = []

        class FakeDT:
            def get_metadata(self):
                return PluginMetadata(
                    name="dependency-track",
                    version="1.1.0",
                    category=AssessmentCategory.SECURITY,
                    scan_mode=ScanMode.CONTINUOUS,
                )

            def sync_release_tags(self, *, sbom_id, run_id, release):
                sync_calls.append({"sbom_id": sbom_id, "run_id": run_id, "release": release})

        class FakeOneShot:
            def get_metadata(self):
                return PluginMetadata(
                    name="other",
                    version="1.0.0",
                    category=AssessmentCategory.COMPLIANCE,
                )

        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks._load_plugin_by_name",
            lambda name: FakeDT() if name == "dependency-track" else FakeOneShot(),
        )

        result = detach_release_from_runs_task.fn(sbom_id=str(sbom.id), release_id=str(release_to_remove.id))

        # M2M row for the removed release is gone; the other one remains
        assert not AssessmentRunRelease.objects.filter(assessment_run=run, release=release_to_remove).exists()
        assert AssessmentRunRelease.objects.filter(assessment_run=run, release=release_keep).exists()

        # Plugin was asked to sync — hook was called with the existing run id
        assert len(sync_calls) == 1
        assert sync_calls[0]["sbom_id"] == str(sbom.id)
        assert sync_calls[0]["run_id"] == str(run.id)

        assert result["detached_runs"] == 1
        assert "dependency-track" in result["synced_plugins"]

    def test_noop_when_no_matching_m2m_row(self, sample_team_with_owner_member):
        """If there's nothing to detach (e.g. release was already removed via CASCADE),
        the task returns cleanly without error."""
        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")

        result = detach_release_from_runs_task.fn(sbom_id=str(sbom.id), release_id=str(release.id))
        assert result == {"detached_runs": 0, "synced_plugins": []}


@pytest.mark.django_db
class TestCronSkipsUnassessableSboms:
    """An SBOM row with no stored artifact can never be scanned; the cron must
    not re-enqueue it every sweep (failed runs do not count as recent, so such
    a row would otherwise fail forever)."""

    def test_cron_skips_sbom_without_stored_file(self, sample_team_with_owner_member, monkeypatch):
        from sbomify.apps.plugins.tasks import _is_paid_team, _run_scheduled_security_scans

        team = sample_team_with_owner_member.team
        team.billing_plan = "business"
        team.save()

        _make_dt_plugin()
        _enable_plugins(team, "dependency-track")

        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        product.components.add(component)
        orphan = SBOM.objects.create(name="orphan", component=component, format="cyclonedx", sbom_filename="")
        release = Release.get_or_create_latest_release(product)
        ReleaseArtifact.objects.get_or_create(release=release, sbom=orphan)

        captured: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs),
        )

        stats = _run_scheduled_security_scans(
            plugin_name="dependency-track",
            plan_filter=_is_paid_team,
            skip_hours=1,
            task_name="test_hourly_dt_scan",
            only_cyclonedx=True,
        )

        assert stats["assessments_enqueued"] == 0
        assert captured == []
