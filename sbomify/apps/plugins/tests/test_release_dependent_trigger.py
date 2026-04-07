"""Tests for the release-dependent plugin trigger split.

See spec: docs/superpowers/specs/2026-04-07-release-dependent-plugin-trigger-design.md
"""

from __future__ import annotations

import pytest

from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason
from sbomify.apps.plugins.sdk.results import PluginMetadata


class TestPluginMetadataRequiresRelease:
    def test_defaults_to_false(self):
        """Existing plugins remain release-independent by default."""
        meta = PluginMetadata(
            name="example",
            version="1.0.0",
            category=AssessmentCategory.COMPLIANCE,
        )
        assert meta.requires_release is False

    def test_can_be_set_true(self):
        meta = PluginMetadata(
            name="example",
            version="1.0.0",
            category=AssessmentCategory.SECURITY,
            requires_release=True,
        )
        assert meta.requires_release is True

    def test_to_dict_omits_when_false(self):
        """Keep serialization stable for existing plugins."""
        meta = PluginMetadata(
            name="example",
            version="1.0.0",
            category=AssessmentCategory.COMPLIANCE,
        )
        result = meta.to_dict()
        assert "requires_release" not in result

    def test_to_dict_includes_when_true(self):
        meta = PluginMetadata(
            name="example",
            version="1.0.0",
            category=AssessmentCategory.SECURITY,
            requires_release=True,
        )
        result = meta.to_dict()
        assert result["requires_release"] is True


class TestRunReasonEnum:
    def test_on_release_association_exists(self):
        assert RunReason.ON_RELEASE_ASSOCIATION.value == "on_release_association"


@pytest.mark.django_db
class TestRegisteredPluginRequiresRelease:
    def test_field_defaults_to_false(self):
        from sbomify.apps.plugins.models import RegisteredPlugin

        plugin = RegisteredPlugin.objects.create(
            name="test-plugin",
            display_name="Test Plugin",
            description="A test plugin",
            category="compliance",
            version="1.0.0",
            plugin_class_path="example.Plugin",
        )
        plugin.refresh_from_db()
        assert plugin.requires_release is False

    def test_field_can_be_set_true(self):
        from sbomify.apps.plugins.models import RegisteredPlugin

        plugin = RegisteredPlugin.objects.create(
            name="test-plugin-2",
            display_name="Test Plugin 2",
            description="A test plugin",
            category="security",
            version="1.0.0",
            plugin_class_path="example.Plugin",
            requires_release=True,
        )
        plugin.refresh_from_db()
        assert plugin.requires_release is True


class TestDependencyTrackPluginMetadata:
    def test_metadata_requires_release(self):
        """DT plugin metadata declares it as release-dependent."""
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        plugin = DependencyTrackPlugin()
        meta = plugin.get_metadata()
        assert meta.requires_release is True


@pytest.mark.django_db
class TestDependencyTrackRegisteredPluginReconciliation:
    def test_dependency_track_row_has_requires_release_true(self):
        """After app ready() runs, the DT registry row must have requires_release=True."""
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.models import RegisteredPlugin

        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable
        plugin = RegisteredPlugin.objects.get(name="dependency-track")
        assert plugin.requires_release is True


@pytest.mark.django_db
class TestDependencyTrackSkippedFinding:
    """When the DT plugin runs against an SBOM with no release, it should
    return a 'skipped' warning finding rather than a hard error. This branch
    is reachable from cron and manual triggers for SBOMs that have no
    release association — never from the upload path after Task 9 lands.
    """

    def test_no_release_returns_warning_not_error(self, tmp_path, sample_team_with_owner_member):
        from unittest.mock import patch

        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        sbom = SBOM.objects.create(
            name="lithium",
            component=component,
            format="cyclonedx",
            format_version="1.6",
        )

        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_text('{"bomFormat": "CycloneDX", "specVersion": "1.6"}')

        plugin = DependencyTrackPlugin()
        with patch.object(plugin, "_team_has_dt_enabled", return_value=True):
            result = plugin.assess(sbom_id=sbom.id, sbom_path=sbom_path)

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.status == "warning"
        assert finding.id == "dependency-track:no-release"
        assert "releaseartifact" in finding.description.lower()
        assert result.summary.error_count == 0
        assert result.summary.warning_count == 1

    def test_skipped_result_metadata_flag_is_explicit(self):
        """API consumers must be able to detect the skipped state via metadata."""
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        plugin = DependencyTrackPlugin()
        result = plugin._create_skipped_result(  # noqa: SLF001 — direct helper contract test
            finding_id="dependency-track:no-release",
            title="Skipped",
            description="No release",
        )
        assert result.metadata == {"skipped": True}
        assert result.summary.warning_count == 1
        assert result.summary.error_count == 0
        assert result.findings[0].status == "warning"
        assert result.findings[0].severity == "info"


@pytest.mark.django_db
class TestEnqueueAssessmentsForSbomFiltering:
    """The release_dependent_only parameter splits the plugin set."""

    def _enable_plugins(self, team, plugin_names):
        from sbomify.apps.plugins.models import TeamPluginSettings

        TeamPluginSettings.objects.create(team=team, enabled_plugins=list(plugin_names))

    def test_release_dependent_only_false_excludes_dt(self, sample_team_with_owner_member, monkeypatch):
        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        sbom = SBOM.objects.create(name="s", component=component)

        # Make sure the registry has the dependency-track row with requires_release=True
        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        self._enable_plugins(team, ["ntia-minimum-elements-2021", "dependency-track"])

        captured = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs["plugin_name"]),
        )

        enqueued = enqueue_assessments_for_sbom(
            sbom_id=sbom.id,
            team_id=str(team.id),
            run_reason=RunReason.ON_UPLOAD,
            release_dependent_only=False,
        )

        assert "dependency-track" not in enqueued
        assert "ntia-minimum-elements-2021" in enqueued
        assert "dependency-track" not in captured

    def test_release_dependent_only_true_includes_only_dt(self, sample_team_with_owner_member, monkeypatch):
        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        sbom = SBOM.objects.create(name="s", component=component)

        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        self._enable_plugins(team, ["ntia-minimum-elements-2021", "dependency-track"])

        captured = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs["plugin_name"]),
        )

        enqueued = enqueue_assessments_for_sbom(
            sbom_id=sbom.id,
            team_id=str(team.id),
            run_reason=RunReason.ON_RELEASE_ASSOCIATION,
            release_dependent_only=True,
        )

        assert enqueued == ["dependency-track"]
        assert captured == ["dependency-track"]

    def test_required_parameter_no_default(self):
        """Calling without release_dependent_only must raise TypeError."""
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom

        with pytest.raises(TypeError):
            enqueue_assessments_for_sbom(
                sbom_id="x",
                team_id="y",
                run_reason=RunReason.ON_UPLOAD,
            )

    def test_no_team_plugin_settings_returns_empty(self, sample_team_with_owner_member):
        """If a team has no TeamPluginSettings row, the function returns an empty list without error."""
        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        sbom = SBOM.objects.create(name="s", component=component)
        # Deliberately do NOT create TeamPluginSettings

        result = enqueue_assessments_for_sbom(
            sbom_id=sbom.id,
            team_id=str(team.id),
            run_reason=RunReason.ON_UPLOAD,
            release_dependent_only=False,
        )
        assert result == []

    def test_plugin_enabled_but_not_in_registry_is_skipped(self, sample_team_with_owner_member, monkeypatch):
        """If a plugin name is in TeamPluginSettings but not in RegisteredPlugin, it is skipped with a warning."""
        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.models import TeamPluginSettings
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom
        from sbomify.apps.sboms.models import SBOM

        # Ensure the registry has dependency-track
        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        sbom = SBOM.objects.create(name="s", component=component)

        # Enable a plugin that doesn't exist in the registry alongside a real one
        TeamPluginSettings.objects.create(
            team=team,
            enabled_plugins=["ntia-minimum-elements-2021", "this-plugin-does-not-exist"],
        )

        captured: list[str] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs["plugin_name"]),
        )

        enqueued = enqueue_assessments_for_sbom(
            sbom_id=sbom.id,
            team_id=str(team.id),
            run_reason=RunReason.ON_UPLOAD,
            release_dependent_only=False,
        )

        # NTIA should be enqueued; the missing plugin should be silently skipped
        assert "ntia-minimum-elements-2021" in enqueued
        assert "this-plugin-does-not-exist" not in enqueued
        assert "ntia-minimum-elements-2021" in captured


@pytest.mark.django_db
class TestReleaseArtifactSignalHandler:
    """The new post_save → ReleaseArtifact handler enqueues release-dependent
    plugin assessments only when an SBOM-bearing artifact is created."""

    def _make_release_with_artifact(self, sample_team_with_owner_member, sbom=None, document=None):
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        release = Release.objects.create(product=product, name="v1", version="1.0.0")
        if sbom is None and document is None:
            component = Component.objects.create(name="c", team=team)
            # Disconnect SBOM upload signal so only the ReleaseArtifact signal is captured
            post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
            try:
                sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
            finally:
                post_save.connect(trigger_plugin_assessments, sender=SBOM)
        artifact = ReleaseArtifact.objects.create(release=release, sbom=sbom, document=document)
        return artifact

    def test_handler_enqueues_release_dependent_plugins_on_create(self, sample_team_with_owner_member, monkeypatch):
        from sbomify.apps.plugins.sdk.enums import RunReason

        captured = []

        def fake_enqueue(**kwargs):
            captured.append(kwargs)
            return ["dependency-track"]

        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            fake_enqueue,
        )

        artifact = self._make_release_with_artifact(sample_team_with_owner_member)

        assert len(captured) == 1
        kwargs = captured[0]
        assert kwargs["sbom_id"] == artifact.sbom_id
        assert kwargs["release_dependent_only"] is True
        assert kwargs["run_reason"] == RunReason.ON_RELEASE_ASSOCIATION

    def test_handler_ignores_document_artifacts(self, sample_team_with_owner_member, monkeypatch):
        from sbomify.apps.core.models import Component
        from sbomify.apps.documents.models import Document

        captured = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured.append(kwargs) or [],
        )

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        document = Document.objects.create(name="d", component=component)
        self._make_release_with_artifact(sample_team_with_owner_member, document=document)

        assert captured == []

    def test_handler_ignores_updates(self, sample_team_with_owner_member, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured.append(kwargs) or [],
        )

        artifact = self._make_release_with_artifact(sample_team_with_owner_member)
        captured.clear()

        # Save again — should not re-enqueue
        artifact.save()
        assert captured == []

    def test_handler_ignores_latest_release(self, sample_team_with_owner_member, monkeypatch):
        """The 'latest' auto-release is skipped so DT only runs for named releases."""
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        captured = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured.append(kwargs) or [],
        )

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        latest_release = Release.get_or_create_latest_release(product)

        assert latest_release.is_latest is True, (
            "The fixture should produce an is_latest=True release so the guard we're testing is actually exercised"
        )

        # Disconnect the SBOM upload signal so only the ReleaseArtifact handler fires
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        ReleaseArtifact.objects.create(release=latest_release, sbom=sbom)
        assert captured == []

    def test_handler_ignores_when_release_info_is_none(self, sample_team_with_owner_member, monkeypatch):
        """Defensive: if the Release lookup returns None, the handler skips silently."""
        from sbomify.apps.core.models import Component
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_release_dependent_assessments

        # Create the SBOM before patching so the upload signal does not populate captured.
        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")

        captured: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured.append(kwargs) or [],
        )

        # Force the Release.filter(...).values_list(...).first() chain to return None
        class _EmptyQS:
            def values_list(self, *args, **kwargs):
                return self

            def first(self):
                return None

        monkeypatch.setattr(
            "sbomify.apps.core.models.Release.objects",
            type("_Mgr", (), {"filter": staticmethod(lambda **kwargs: _EmptyQS())})(),
        )

        class _FakeArtifact:
            pk = "fake-artifact-id"
            release_id = "nonexistent-release"
            sbom_id = sbom.id

        trigger_release_dependent_assessments(sender=None, instance=_FakeArtifact(), created=True)

        assert captured == []

    def test_handler_swallows_broker_failures(self, sample_team_with_owner_member, monkeypatch):
        """If enqueue_assessments_for_sbom raises (e.g., broker unavailable), the handler logs and continues."""
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        def _boom(**kwargs):
            raise RuntimeError("simulated broker outage")

        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            _boom,
        )

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        release = Release.objects.create(product=product, name="v1", version="1.0.0")

        # Disconnect the SBOM upload signal so only the ReleaseArtifact handler fires
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        # This must NOT raise — the handler catches the exception and logs
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
        # No assertion needed beyond reaching this line; the handler's try/except
        # in _enqueue() swallows the RuntimeError.


@pytest.mark.django_db
class TestEndToEndTriggerSplit:
    """End-to-end: SBOM upload then named-release association produces the
    expected sequence of plugin enqueue calls.

    No mocks above the dramatiq dispatcher — the real Django signals fire,
    the real enqueue_assessments_for_sbom runs, and we observe the final
    enqueue_assessment call shape.
    """

    def test_sbom_upload_then_release_association_enqueues_dt_only_after_link(
        self, sample_team_with_owner_member, monkeypatch
    ):
        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.models import TeamPluginSettings
        from sbomify.apps.sboms.models import SBOM

        # Reconcile the plugin registry so dependency-track has requires_release=True
        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        TeamPluginSettings.objects.create(
            team=team,
            enabled_plugins=["ntia-minimum-elements-2021", "dependency-track"],
        )

        # Patch the actual enqueue dispatcher (not enqueue_assessments_for_sbom)
        # so we observe what reaches the queue from BOTH signal handlers
        captured: list[str] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs["plugin_name"]),
        )

        component = Component.objects.create(name="c", team=team)
        product = Product.objects.create(name="p", team=team)
        named_release = Release.objects.create(product=product, name="v1", version="1.0.0")

        # Step 1: upload SBOM. Triggers post_save → SBOM. NTIA should fire,
        # dependency-track should NOT.
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        upload_captured = list(captured)
        assert "ntia-minimum-elements-2021" in upload_captured
        assert "dependency-track" not in upload_captured

        # Step 2: associate SBOM with the named release. Triggers
        # post_save → ReleaseArtifact on a non-latest release, which is the
        # new Task 9 handler's target. Now dependency-track should fire.
        ReleaseArtifact.objects.create(release=named_release, sbom=sbom)
        association_captured = [p for p in captured if p not in upload_captured]
        assert "dependency-track" in association_captured


class TestRunReasonFieldLength:
    """Guard: every RunReason enum value must fit within AssessmentRun.run_reason max_length."""

    def test_all_run_reason_values_fit_in_column(self):
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.plugins.sdk.enums import RunReason

        max_length = AssessmentRun._meta.get_field("run_reason").max_length
        longest = max(RunReason, key=lambda r: len(r.value))
        assert len(longest.value) <= max_length, (
            f"RunReason.{longest.name}={longest.value!r} ({len(longest.value)} chars) "
            f"exceeds AssessmentRun.run_reason.max_length={max_length}"
        )


@pytest.mark.django_db
class TestBulkBackfillFiltering:
    """The backfill task (used when a team enables a new plugin) must
    respect requires_release so DT is not enqueued for SBOMs without
    a release association.
    """

    def test_backfill_excludes_release_dependent_plugins(self, sample_team_with_owner_member, monkeypatch):
        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task
        from sbomify.apps.sboms.models import SBOM

        # Ensure registry has dependency-track with requires_release=True
        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        SBOM.objects.create(name="s", component=component, format="cyclonedx")

        captured: list[str] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs["plugin_name"]),
        )

        result = enqueue_assessments_for_existing_sboms_task(
            team_id=str(team.id),
            enabled_plugins=["ntia-minimum-elements-2021", "dependency-track"],
            cutoff_hours=24,
        )

        assert "dependency-track" not in captured
        # NTIA should still have been enqueued for the backfill
        assert "ntia-minimum-elements-2021" in captured
        # Task result should reflect what was actually enqueued (DT was skipped)
        assert result["assessments_enqueued"] >= 1
