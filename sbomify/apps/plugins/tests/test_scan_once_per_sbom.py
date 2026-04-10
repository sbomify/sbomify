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

from unittest.mock import patch

import pytest

from sbomify.apps.core.models import Component, Product, Project, Release, ReleaseArtifact
from sbomify.apps.plugins.models import (
    AssessmentRun,
    AssessmentRunRelease,
    RegisteredPlugin,
    RunStatus,
    TeamPluginSettings,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, ScanMode
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
        # sbom_v1 auto-added to latest release by the upload signal
        sbom_v1 = SBOM.objects.create(name="v1", component=component, format="cyclonedx")
        # component_v2 is NOT in the project, so sbom_v2 won't auto-add to latest
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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


@pytest.mark.django_db
class TestOrchestratorPopulatesM2MAtCompletion:
    """Orchestrator populates AssessmentRun.releases from current ReleaseArtifact state."""

    def test_sync_run_releases_copies_from_release_artifact(self, sample_team_with_owner_member):
        """_sync_run_releases reads ReleaseArtifact and creates matching M2M rows."""
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")

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
class TestDependencyTrackPluginScanOnce:
    """The DT plugin uses one DT project version per SBOM, releases as tags."""

    def _make_env(self):
        """Build a team, product, component, SBOM linked to two named releases."""
        from sbomify.apps.teams.models import Team
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        team = Team.objects.create(name="DT Scan Once Team", key="dt-so", billing_plan="business")
        product = Product.objects.create(name="p", team=team)
        component = Component.objects.create(name="c", team=team)
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)

        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", sha256_hash="a" * 64)

        # Use auto-created latest + two named releases
        release_latest = Release.get_or_create_latest_release(product)
        release_v1 = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")
        release_v2 = Release.objects.create(product=product, name="v2.0.0", version="2.0.0")
        ReleaseArtifact.objects.get_or_create(release=release_latest, sbom=sbom)
        ReleaseArtifact.objects.create(release=release_v1, sbom=sbom)
        ReleaseArtifact.objects.create(release=release_v2, sbom=sbom)

        server = DependencyTrackServer.objects.create(
            name="Scan Once DT",
            url="https://dt-so.example.com",
            api_key="key",
            health_status="healthy",
        )
        return team, product, component, sbom, server, [release_latest.name, release_v1.name, release_v2.name]

    def test_first_scan_uploads_once_creates_version_row_sets_tags(self, sample_team_with_owner_member, tmp_path):
        """Plugin's first assess() call on a 3-release SBOM uploads ONCE,
        persists a SbomDependencyTrackProjectVersion row with sbom.id as the
        version, and sets the DT tag set to all 3 release names."""
        from unittest.mock import MagicMock

        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.plugins.sdk.base import RetryLaterError
        from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

        team, product, component, sbom, server, release_names = self._make_env()
        _make_dt_plugin()
        _enable_plugins(team, "dependency-track")

        captured_uploads: list[dict] = []
        captured_tag_sets: list[dict] = []

        def fake_upload(*, project_name, project_version, sbom_data, auto_create):
            captured_uploads.append({"project_name": project_name, "project_version": project_version})

        def fake_find_project(name, version):
            return {"uuid": "00000000-0000-0000-0000-000000000001"}

        def fake_set_tags(project_uuid, tag_names):
            captured_tag_sets.append({"uuid": project_uuid, "tag_names": tag_names})

        mock_client = MagicMock()
        mock_client.upload_sbom_with_project_creation.side_effect = fake_upload
        mock_client.find_project_by_name_version.side_effect = fake_find_project
        mock_client.set_project_tags.side_effect = fake_set_tags
        mock_client.get_project.return_value = {"uuid": "00000000-0000-0000-0000-000000000001", "name": "p-c"}

        plugin = DependencyTrackPlugin()

        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_bytes(b'{"bomFormat":"CycloneDX","specVersion":"1.6"}')

        with (
            patch(
                "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient",
                return_value=mock_client,
            ),
            patch.object(plugin, "_select_dt_server", return_value=server),
            patch.object(plugin, "_team_has_dt_enabled", return_value=True),
            patch(
                "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService._get_environment_prefix",
                return_value="dev",
            ),
        ):
            with pytest.raises(RetryLaterError):
                plugin.assess(sbom_id=sbom.id, sbom_path=sbom_path, context=None)

        # Exactly ONE upload call. project_version must be sbom.id (Q1=A).
        assert len(captured_uploads) == 1
        assert captured_uploads[0]["project_version"] == str(sbom.id)
        assert str(component.id) in captured_uploads[0]["project_name"]  # component ID is part of project_name

        # SbomDependencyTrackProjectVersion row was persisted
        row = SbomDependencyTrackProjectVersion.objects.get(sbom=sbom, dt_server=server)
        assert row.dt_project_version == str(sbom.id)
        assert str(row.dt_project_version_uuid) == "00000000-0000-0000-0000-000000000001"

        # Initial tag set was pushed to DT — contains all 3 release names (sorted/dedupe'd)
        assert len(captured_tag_sets) == 1
        assert set(captured_tag_sets[0]["tag_names"]) == set(release_names)

    def test_retry_uses_stored_version_uuid_no_reupload(self, sample_team_with_owner_member, tmp_path):
        """Retry after first upload polls using stored UUID — no second upload call."""
        from unittest.mock import MagicMock

        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

        team, product, component, sbom, server, release_names = self._make_env()
        _make_dt_plugin()
        _enable_plugins(team, "dependency-track")

        # Pre-create the version row as if first upload already happened
        SbomDependencyTrackProjectVersion.objects.create(
            sbom=sbom,
            dt_server=server,
            dt_project_version=str(sbom.id),
            dt_project_version_uuid="00000000-0000-0000-0000-000000000001",
        )

        captured_uploads: list[dict] = []

        def fake_upload(*, project_name, project_version, sbom_data, auto_create):
            captured_uploads.append({"project_name": project_name, "project_version": project_version})

        mock_client = MagicMock()
        mock_client.upload_sbom_with_project_creation.side_effect = fake_upload
        mock_client.get_project_metrics.return_value = {"components": 0, "vulnerabilities": 0}
        mock_client.get_project_vulnerabilities.return_value = {"content": []}

        plugin = DependencyTrackPlugin()

        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_bytes(b'{"bomFormat":"CycloneDX","specVersion":"1.6"}')

        with (
            patch(
                "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient",
                return_value=mock_client,
            ),
            patch.object(plugin, "_select_dt_server", return_value=server),
            patch.object(plugin, "_team_has_dt_enabled", return_value=True),
            patch(
                "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService._get_environment_prefix",
                return_value="dev",
            ),
        ):
            result = plugin.assess(sbom_id=sbom.id, sbom_path=sbom_path, context=None)

        assert captured_uploads == [], "Retry path must NOT re-upload the SBOM"
        assert result is not None
        assert result.summary.total_findings == 0
        # Result metadata should reflect the stored version UUID and canonical tag set
        assert result.metadata["dt_project_uuid"] == "00000000-0000-0000-0000-000000000001"
        assert result.metadata["dt_project_version"] == str(sbom.id)
        assert set(result.metadata["dt_project_release_tags"]) == set(release_names)

    def test_sync_release_tags_pushes_canonical_set_from_m2m(self, sample_team_with_owner_member):
        """Q2=B: sync_release_tags re-reads the full release set from AssessmentRun.releases
        M2M and PATCHes the DT tag list to match (idempotent, self-healing)."""
        from unittest.mock import MagicMock

        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.plugins.models import AssessmentRun, AssessmentRunRelease, RunStatus
        from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

        team, product, component, sbom, server, release_names = self._make_env()

        # Pre-create the version row
        SbomDependencyTrackProjectVersion.objects.create(
            sbom=sbom,
            dt_server=server,
            dt_project_version=str(sbom.id),
            dt_project_version_uuid="00000000-0000-0000-0000-000000000001",
        )

        # Completed run with M2M pointing at all 3 releases
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
        for r in Release.objects.filter(product=product):
            AssessmentRunRelease.objects.create(assessment_run=run, release=r)

        captured_tag_sets: list[dict] = []
        mock_client = MagicMock()
        mock_client.set_project_tags.side_effect = lambda uuid, names: captured_tag_sets.append(
            {"uuid": uuid, "names": names}
        )

        plugin = DependencyTrackPlugin()
        newly_attached_release = Release.objects.filter(product=product, name="v2.0.0").first()

        with patch(
            "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient",
            return_value=mock_client,
        ):
            plugin.sync_release_tags(sbom_id=str(sbom.id), run_id=str(run.id), release=newly_attached_release)

        assert len(captured_tag_sets) == 1
        # The tag set must match the canonical M2M content, NOT just the newly
        # attached release — that's the Q2=B invariant.
        assert set(captured_tag_sets[0]["names"]) == set(release_names)


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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
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
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        release = Release.objects.create(product=product, name="v1.0.0", version="1.0.0")

        result = detach_release_from_runs_task.fn(sbom_id=str(sbom.id), release_id=str(release.id))
        assert result == {"detached_runs": 0, "synced_plugins": []}
