"""Tests for the release-dependent plugin trigger split.

Covers PluginMetadata/RegisteredPlugin ``requires_release`` semantics, the
``release_dependent_only`` filter on ``enqueue_assessments_for_sbom``, the
``ReleaseArtifact`` post_save signal handler, the Dependency Track plugin's
``_find_release_for_sbom`` ordering contract, and the end-to-end trigger
split scenarios (upload path vs. named-release-association path). See
sbomify/sbomify#873 for the design rationale.
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

    def test_all_builtin_plugins_have_explicit_requires_release(self):
        """Every builtin plugin must declare requires_release explicitly so
        reconciliation cannot drift if an admin toggles the DB field.
        """
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.models import RegisteredPlugin

        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        builtins = RegisteredPlugin.objects.filter(is_builtin=True)
        assert builtins.exists(), "reconciliation should produce at least one builtin"

        expected_release_dependent = {"dependency-track"}
        for plugin in builtins:
            expected = plugin.name in expected_release_dependent
            assert plugin.requires_release is expected, (
                f"Plugin {plugin.name!r} has requires_release={plugin.requires_release} but expected {expected}"
            )


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

    def test_handler_skips_cross_team_release_artifact(self, sample_team_with_owner_member, monkeypatch):
        """Defense-in-depth: if a ReleaseArtifact somehow links a cross-team
        SBOM and release (e.g., via direct ORM bypass of add_artifact_to_release),
        the handler must skip rather than enqueue plugin work under the wrong team.
        """
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments
        from sbomify.apps.teams.models import Team

        captured: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured.append(kwargs) or [],
        )

        team_a = sample_team_with_owner_member.team
        team_b = Team.objects.create(name="other-team")

        # Product/release owned by team A
        product_a = Product.objects.create(name="product-a", team=team_a)
        release_a = Release.objects.create(product=product_a, name="v1", version="1.0.0")

        # Component/SBOM owned by team B (cross-team)
        component_b = Component.objects.create(name="component-b", team=team_b)

        # Disconnect the SBOM upload signal so only the ReleaseArtifact handler fires
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            sbom_b = SBOM.objects.create(name="sbom-b", component=component_b, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        # Direct ORM create bypasses the add_artifact_to_release team check.
        # The signal handler should still refuse to enqueue.
        ReleaseArtifact.objects.create(release=release_a, sbom=sbom_b)

        assert captured == [], "cross-team ReleaseArtifact must not trigger plugin enqueue"


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

    def test_dt_resolves_named_release_when_both_latest_and_named_exist(
        self, sample_team_with_owner_member, monkeypatch
    ):
        """Full pipeline: upload SBOM (auto-adds to latest), then associate
        with a named release. DT should be triggered once and must resolve
        the named release, not the latest.
        """
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.plugins.models import TeamPluginSettings
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        # Reconcile the plugin registry so dependency-track has requires_release=True
        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        TeamPluginSettings.objects.create(team=team, enabled_plugins=["dependency-track"])

        # Patch enqueue_assessment so DT is not actually dispatched to Dramatiq
        dt_calls: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: dt_calls.append(kwargs) if kwargs["plugin_name"] == "dependency-track" else None,
        )

        product = Product.objects.create(name="lithium", team=team)
        latest_release = Release.get_or_create_latest_release(product)
        component = Component.objects.create(name="backend", team=team)

        # Create the SBOM. Disconnect SBOM upload signal to avoid NTIA noise,
        # then manually create the latest ReleaseArtifact to simulate the
        # auto-latest mechanism without relying on signal chain complexity.
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        # Manually link SBOM to latest release (simulating update_latest_release_on_sbom_created)
        ReleaseArtifact.objects.create(release=latest_release, sbom=sbom)

        assert dt_calls == [], "DT should not be enqueued for latest-release auto-creation"

        # Now associate the SBOM with a named release. The ReleaseArtifact
        # post_save signal fires; the is_latest guard lets this through.
        named_release = Release.objects.create(product=product, name="v1", version="1.0.0")
        ReleaseArtifact.objects.create(release=named_release, sbom=sbom)

        # DT should have been enqueued exactly once now.
        assert len(dt_calls) == 1, f"Expected exactly one DT enqueue; got {len(dt_calls)}"

        # And when the DT plugin resolves the release for this SBOM, it must
        # pick the named release, not the latest.
        plugin = DependencyTrackPlugin()
        resolved = plugin._find_release_for_sbom(sbom.id)  # noqa: SLF001 — contract verification
        assert resolved is not None
        assert resolved.is_latest is False
        assert resolved.pk == named_release.pk


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


@pytest.mark.django_db
class TestDependencyTrackFindReleaseOrdering:
    """_find_release_for_sbom must deterministically prefer the newest
    non-"latest" release when an SBOM is linked to multiple releases.
    """

    def _make_sbom(self, team):
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        component = Component.objects.create(name="c", team=team)
        # Isolate from upload signal so we control ReleaseArtifact creation
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)
        return sbom

    def test_prefers_named_release_over_latest(self, sample_team_with_owner_member):
        """When an SBOM is in both the 'latest' release and a named release, DT targets the named release."""
        from sbomify.apps.core.models import Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        latest_release = Release.get_or_create_latest_release(product)
        named_release = Release.objects.create(product=product, name="v1", version="1.0.0")

        sbom = self._make_sbom(team)
        ReleaseArtifact.objects.create(release=latest_release, sbom=sbom)
        ReleaseArtifact.objects.create(release=named_release, sbom=sbom)

        plugin = DependencyTrackPlugin()
        resolved = plugin._find_release_for_sbom(sbom.id)  # noqa: SLF001 — direct contract test

        assert resolved is not None
        assert resolved.is_latest is False
        assert resolved.pk == named_release.pk

    def test_prefers_newest_named_release_when_multiple_exist(self, sample_team_with_owner_member):
        """If an SBOM is in multiple named releases, pick the most recently associated one."""
        from sbomify.apps.core.models import Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        release_a = Release.objects.create(product=product, name="v1", version="1.0.0")
        release_b = Release.objects.create(product=product, name="v2", version="2.0.0")

        sbom = self._make_sbom(team)
        ReleaseArtifact.objects.create(release=release_a, sbom=sbom)
        ReleaseArtifact.objects.create(release=release_b, sbom=sbom)  # created later

        plugin = DependencyTrackPlugin()
        resolved = plugin._find_release_for_sbom(sbom.id)  # noqa: SLF001 — direct contract test

        assert resolved is not None
        assert resolved.pk == release_b.pk

    def test_falls_back_to_latest_when_only_latest_exists(self, sample_team_with_owner_member):
        """Cron / manual triggers on an SBOM that only exists in 'latest' still get a result."""
        from sbomify.apps.core.models import Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        latest_release = Release.get_or_create_latest_release(product)

        sbom = self._make_sbom(team)
        ReleaseArtifact.objects.create(release=latest_release, sbom=sbom)

        plugin = DependencyTrackPlugin()
        resolved = plugin._find_release_for_sbom(sbom.id)  # noqa: SLF001 — direct contract test

        assert resolved is not None
        assert resolved.is_latest is True
        assert resolved.pk == latest_release.pk


@pytest.mark.django_db
class TestDependencyTrackReleaseContextResolution:
    """When SBOMContext.release_id is set, the DT plugin MUST use it and
    MUST NOT fall back to _find_release_for_sbom. This is the core fix for
    the multi-release case where a single SBOM is linked to both v1 and
    v1.1 of a product and each release has its own DT project.
    """

    def test_plugin_uses_release_id_from_context(self, sample_team_with_owner_member):
        """assess() resolves the Release from context.release_id, not from
        _find_release_for_sbom, when both are available and disagree."""
        from pathlib import Path
        from unittest.mock import patch

        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.plugins.sdk.base import SBOMContext
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)

        # Create two non-latest releases for the same SBOM
        release_v1 = Release.objects.create(product=product, name="v1", version="1.0.0")
        release_v1_1 = Release.objects.create(product=product, name="v1.1", version="1.1.0")

        component = Component.objects.create(name="c", team=team)
        # Disconnect SBOM upload signal so it doesn't call DT
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        # Link the SBOM to BOTH releases
        ReleaseArtifact.objects.create(release=release_v1, sbom=sbom)
        ReleaseArtifact.objects.create(release=release_v1_1, sbom=sbom)

        # Without context, _find_release_for_sbom would pick v1.1 (newest non-latest)
        plugin = DependencyTrackPlugin()
        fallback_resolved = plugin._find_release_for_sbom(sbom.id)  # noqa: SLF001 — contract test
        assert fallback_resolved.pk == release_v1_1.pk, "fallback should prefer newest"

        # But when context pins release_id=v1, the plugin MUST scan v1
        context = SBOMContext(release_id=release_v1.pk)

        # Capture what project name DT would use, without actually talking to DT
        captured_release_names: list[str] = []

        def fake_get_or_create_mapping_and_upload(release, sbom_bytes, dt_server, existing_mapping):
            captured_release_names.append(release.name)
            raise RuntimeError("stop before network")

        with (
            patch.object(plugin, "_team_has_dt_enabled", return_value=True),
            patch.object(plugin, "_select_dt_server", return_value=object()),
            patch.object(
                plugin,
                "_get_or_create_mapping_and_upload",
                side_effect=fake_get_or_create_mapping_and_upload,
            ),
        ):
            sbom_path = Path("/dev/null")  # content is never read in this test path
            # Patch file read to return minimal CycloneDX bytes
            with patch.object(Path, "read_bytes", return_value=b'{"bomFormat": "CycloneDX", "specVersion": "1.6"}'):
                plugin.assess(sbom_id=sbom.id, sbom_path=sbom_path, context=context)

        assert captured_release_names == ["v1"], (
            f"DT should have scanned v1 (from context.release_id), got {captured_release_names}"
        )

    def test_plugin_falls_back_when_context_release_id_missing(self, sample_team_with_owner_member):
        """When context.release_id is None, plugin falls back to _find_release_for_sbom."""
        from pathlib import Path
        from unittest.mock import patch

        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.plugins.sdk.base import SBOMContext
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        release = Release.objects.create(product=product, name="v1", version="1.0.0")

        component = Component.objects.create(name="c", team=team)
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        plugin = DependencyTrackPlugin()
        context = SBOMContext(release_id=None)  # legacy / no-context path

        captured_release_names: list[str] = []

        def fake_upload(release, sbom_bytes, dt_server, existing_mapping):
            captured_release_names.append(release.name)
            raise RuntimeError("stop before network")

        with (
            patch.object(plugin, "_team_has_dt_enabled", return_value=True),
            patch.object(plugin, "_select_dt_server", return_value=object()),
            patch.object(plugin, "_get_or_create_mapping_and_upload", side_effect=fake_upload),
            patch.object(Path, "read_bytes", return_value=b'{"bomFormat": "CycloneDX", "specVersion": "1.6"}'),
        ):
            plugin.assess(sbom_id=sbom.id, sbom_path=Path("/dev/null"), context=context)

        assert captured_release_names == ["v1"]

    def test_plugin_returns_skipped_when_release_id_points_to_deleted_release(self, sample_team_with_owner_member):
        """TOCTOU: if context.release_id references a Release that was deleted
        between trigger and task execution, the plugin returns a skipped
        finding with id 'dependency-track:release-deleted' rather than
        falling back to _find_release_for_sbom. This is safer than silently
        scanning a different release than the one that triggered the run.
        """
        from pathlib import Path
        from unittest.mock import patch

        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.plugins.sdk.base import SBOMContext
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        release = Release.objects.create(product=product, name="v1", version="1.0.0")
        deleted_release_pk = release.pk

        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        # Simulate the TOCTOU: release is deleted between signal fire and task execution.
        # Note: deleting the release will also cascade-delete any ReleaseArtifact rows,
        # but the DT plugin only uses context.release_id to look up the release — not
        # the ReleaseArtifact — so this is the correct test setup.
        Release.objects.filter(pk=deleted_release_pk).delete()

        plugin = DependencyTrackPlugin()
        context = SBOMContext(release_id=deleted_release_pk)

        with (
            patch.object(plugin, "_team_has_dt_enabled", return_value=True),
            patch.object(Path, "read_bytes", return_value=b'{"bomFormat": "CycloneDX", "specVersion": "1.6"}'),
        ):
            result = plugin.assess(sbom_id=sbom.id, sbom_path=Path("/dev/null"), context=context)

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.id == "dependency-track:release-deleted", (
            f"Expected finding id 'dependency-track:release-deleted', got {finding.id!r}"
        )
        assert finding.status == "warning"
        assert "deleted" in finding.description.lower()
        # The skipped result should mark it as skipped, not as an error
        assert result.metadata.get("skipped") is True
        assert result.summary.error_count == 0

    def test_plugin_rejects_cross_team_release_id_in_context(self, sample_team_with_owner_member):
        """Defense-in-depth: if context.release_id points to a Release whose
        product belongs to a different team than the SBOM, the plugin must
        refuse to scan rather than invoke DT under the wrong team's credentials.
        """
        from pathlib import Path
        from unittest.mock import patch

        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.plugins.sdk.base import SBOMContext
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments
        from sbomify.apps.teams.models import Team

        team_a = sample_team_with_owner_member.team
        team_b = Team.objects.create(name="other-team")

        # Product/release owned by team B
        product_b = Product.objects.create(name="product-b", team=team_b)
        release_b = Release.objects.create(product=product_b, name="v1", version="1.0.0")

        # SBOM owned by team A
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component_a = Component.objects.create(name="component-a", team=team_a)
            sbom_a = SBOM.objects.create(name="sbom-a", component=component_a, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        plugin = DependencyTrackPlugin()
        context = SBOMContext(release_id=release_b.pk)

        with (
            patch.object(plugin, "_team_has_dt_enabled", return_value=True),
            patch.object(Path, "read_bytes", return_value=b'{"bomFormat": "CycloneDX", "specVersion": "1.6"}'),
        ):
            result = plugin.assess(sbom_id=sbom_a.id, sbom_path=Path("/dev/null"), context=context)

        # Should be an error result, not a pass or skip — the plugin refused to scan
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.status == "error", f"Expected error status for cross-team refusal, got {finding.status!r}"
        assert "cross-team" in finding.description.lower()
        assert result.summary.error_count == 1


@pytest.mark.django_db
class TestEnqueueAssessmentThreadsReleaseId:
    """enqueue_assessment and enqueue_assessments_for_sbom must thread
    release_id into the Dramatiq task kwargs."""

    def test_enqueue_assessment_puts_release_id_in_task_kwargs(self, sample_team_with_owner_member, monkeypatch):
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessment, run_assessment_task

        # enqueue_assessment defers dispatch via transaction.on_commit, which
        # does not fire inside pytest-django's rolled-back test transactions.
        # Patch it to execute callbacks immediately so we can observe the
        # task kwargs.
        monkeypatch.setattr("sbomify.apps.plugins.tasks.transaction.on_commit", lambda fn: fn())

        captured: list[dict] = []
        monkeypatch.setattr(
            run_assessment_task,
            "send_with_options",
            lambda *args, **kwargs: captured.append(kwargs["kwargs"]),
        )

        enqueue_assessment(
            sbom_id="sbom-x",
            plugin_name="dependency-track",
            run_reason=RunReason.ON_RELEASE_ASSOCIATION,
            release_id="rel-y",
        )

        assert len(captured) == 1
        assert captured[0]["release_id"] == "rel-y"
        assert captured[0]["sbom_id"] == "sbom-x"

    def test_enqueue_assessments_for_sbom_threads_release_id(self, sample_team_with_owner_member, monkeypatch):
        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.models import TeamPluginSettings
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom
        from sbomify.apps.sboms.models import SBOM

        # Reconcile the plugin registry so dependency-track has requires_release=True
        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        sbom = SBOM.objects.create(name="s", component=component)
        TeamPluginSettings.objects.create(team=team, enabled_plugins=["dependency-track"])

        captured_kwargs: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured_kwargs.append(kwargs),
        )

        enqueue_assessments_for_sbom(
            sbom_id=sbom.id,
            team_id=str(team.id),
            run_reason=RunReason.ON_RELEASE_ASSOCIATION,
            release_dependent_only=True,
            release_id="rel-z",
        )

        assert len(captured_kwargs) == 1
        assert captured_kwargs[0]["release_id"] == "rel-z"
        assert captured_kwargs[0]["plugin_name"] == "dependency-track"


@pytest.mark.django_db
class TestReleaseArtifactSignalPassesReleaseId:
    """The ReleaseArtifact signal handler must pass release_id when
    enqueueing release-dependent plugin assessments."""

    def test_signal_threads_release_id_into_enqueue(self, sample_team_with_owner_member, monkeypatch):
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        captured_kwargs: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured_kwargs.append(kwargs) or [],
        )

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        release = Release.objects.create(product=product, name="v1", version="1.0.0")

        # Disconnect SBOM upload signal so only the ReleaseArtifact handler fires
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        artifact = ReleaseArtifact.objects.create(release=release, sbom=sbom)

        assert len(captured_kwargs) == 1
        assert captured_kwargs[0]["release_id"] == str(release.pk)
        assert captured_kwargs[0]["sbom_id"] == sbom.id
        assert captured_kwargs[0]["release_dependent_only"] is True
        # Sanity check: the release matches the artifact's release
        assert str(artifact.release_id) == captured_kwargs[0]["release_id"]


@pytest.mark.django_db
class TestHourlyDtScanPerReleasePair:
    """The hourly DT cron task must iterate per (SBOM, Release) pair, not
    dedupe by sbom_id. This is the fix for Case 2: same SBOM in two
    actively-maintained releases must have BOTH DT projects kept current.
    """

    def _setup_dt_team(self, team):
        """Put a team on a business plan and enable DT."""
        from sbomify.apps.plugins.models import TeamPluginSettings
        from sbomify.apps.teams.models import Team

        Team.objects.filter(pk=team.pk).update(billing_plan="business")
        team.refresh_from_db()
        TeamPluginSettings.objects.create(team=team, enabled_plugins=["dependency-track"])

    def test_cron_enqueues_per_release_pair(self, sample_team_with_owner_member, monkeypatch):
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.tasks import hourly_dt_scan_task
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        self._setup_dt_team(team)

        product = Product.objects.create(name="p", team=team)
        release_v1 = Release.objects.create(product=product, name="v1", version="1.0.0")
        release_v1_1 = Release.objects.create(product=product, name="v1.1", version="1.1.0")

        # Single SBOM shared between two named releases (security patch in a
        # different component triggered a new release but this component's
        # SBOM is unchanged)
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        ReleaseArtifact.objects.create(release=release_v1, sbom=sbom)
        ReleaseArtifact.objects.create(release=release_v1_1, sbom=sbom)

        captured: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs),
        )

        stats = hourly_dt_scan_task()

        # Both releases should produce their own enqueue call
        assert stats["assessments_enqueued"] == 2
        assert len(captured) == 2
        enqueued_release_ids = {c["release_id"] for c in captured}
        assert enqueued_release_ids == {str(release_v1.pk), str(release_v1_1.pk)}
        # Both calls are for the same SBOM
        assert all(c["sbom_id"] == str(sbom.id) for c in captured)

    def test_cron_dedupes_per_pair_not_per_sbom(self, sample_team_with_owner_member, monkeypatch):
        """If there's a recent AssessmentRun for (sbom, v1), cron still runs
        (sbom, v1.1) in the same hour."""
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.plugins.tasks import hourly_dt_scan_task
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        self._setup_dt_team(team)

        product = Product.objects.create(name="p", team=team)
        release_v1 = Release.objects.create(product=product, name="v1", version="1.0.0")
        release_v1_1 = Release.objects.create(product=product, name="v1.1", version="1.1.0")

        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        ReleaseArtifact.objects.create(release=release_v1, sbom=sbom)
        ReleaseArtifact.objects.create(release=release_v1_1, sbom=sbom)

        # Seed a recent AssessmentRun for (sbom, v1) only — v1.1 should still be scanned
        AssessmentRun.objects.create(
            sbom=sbom,
            release=release_v1,
            plugin_name="dependency-track",
            plugin_version="1.1.0",
            plugin_config_hash="abc",
            category="security",
            run_reason="scheduled_refresh",
            status="completed",
        )

        captured: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs),
        )

        stats = hourly_dt_scan_task()

        # Only v1.1 should be enqueued; v1 was scanned recently
        assert stats["assessments_enqueued"] == 1
        assert stats["skipped_recent"] == 1
        assert captured[0]["release_id"] == str(release_v1_1.pk)

    def test_cron_skips_latest_releases(self, sample_team_with_owner_member, monkeypatch):
        """Latest releases are rolling pointers and should be skipped by cron."""
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.tasks import hourly_dt_scan_task
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        self._setup_dt_team(team)

        product = Product.objects.create(name="p", team=team)
        latest_release = Release.get_or_create_latest_release(product)

        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        ReleaseArtifact.objects.create(release=latest_release, sbom=sbom)

        captured: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessment",
            lambda **kwargs: captured.append(kwargs),
        )

        stats = hourly_dt_scan_task()

        assert stats["skipped_latest"] == 1
        assert stats["assessments_enqueued"] == 0
        assert captured == []


@pytest.mark.django_db
class TestOrchestratorPersistsReleaseId:
    """The central correctness claim of the release_id threading change is
    that PluginOrchestrator.run_assessment stores release_id on the
    AssessmentRun row. A regression that drops the release_id kwarg from
    AssessmentRun.objects.create(...) would break the per-release scan
    history and go undetected by every other test in this file.
    """

    def test_run_assessment_persists_release_id_on_assessment_run(self, sample_team_with_owner_member, monkeypatch):
        from unittest.mock import MagicMock

        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator
        from sbomify.apps.plugins.sdk.base import AssessmentPlugin
        from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason
        from sbomify.apps.plugins.sdk.results import AssessmentResult, AssessmentSummary, PluginMetadata
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="p", team=team)
        release = Release.objects.create(product=product, name="v1", version="1.0.0")

        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", sha256_hash="a" * 64)
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        # Build a minimal fake plugin that reports success without doing real work
        class FakePlugin(AssessmentPlugin):
            VERSION = "0.0.1"

            def get_metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="fake-plugin",
                    version=self.VERSION,
                    category=AssessmentCategory.COMPLIANCE,
                    requires_release=True,
                )

            def assess(self, sbom_id, sbom_path, dependency_status=None, context=None):
                return AssessmentResult(
                    plugin_name="fake-plugin",
                    plugin_version=self.VERSION,
                    category=AssessmentCategory.COMPLIANCE.value,
                    assessed_at="2026-04-08T00:00:00Z",
                    summary=AssessmentSummary(
                        total_findings=0, pass_count=0, fail_count=0, warning_count=0, error_count=0
                    ),
                    findings=[],
                )

        # Stub get_sbom_data_bytes to avoid an S3 fetch
        sbom_instance_mock = MagicMock()
        sbom_instance_mock.sha256_hash = "a" * 64
        sbom_instance_mock.format = "cyclonedx"
        sbom_instance_mock.format_version = "1.6"
        sbom_instance_mock.name = "s"
        sbom_instance_mock.version = ""
        sbom_instance_mock.component_id = component.id
        sbom_instance_mock.component = component
        sbom_instance_mock.bom_type = "sbom"
        monkeypatch.setattr(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            lambda sid: (sbom_instance_mock, b'{"bomFormat":"CycloneDX","specVersion":"1.6"}'),
        )

        plugin = FakePlugin()
        orchestrator = PluginOrchestrator()
        result_run = orchestrator.run_assessment(
            sbom_id=sbom.id,
            plugin=plugin,
            run_reason=RunReason.ON_RELEASE_ASSOCIATION,
            release_id=str(release.pk),
        )

        assert result_run is not None
        result_run.refresh_from_db()
        assert result_run.release_id == release.pk, (
            f"Expected AssessmentRun.release_id={release.pk}, got {result_run.release_id}"
        )
        assert result_run.release == release

    def test_run_assessment_without_release_id_stores_null(self, sample_team_with_owner_member, monkeypatch):
        """Sanity check the None path: run_assessment without release_id stores NULL."""
        from unittest.mock import MagicMock

        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator
        from sbomify.apps.plugins.sdk.base import AssessmentPlugin
        from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason
        from sbomify.apps.plugins.sdk.results import AssessmentResult, AssessmentSummary, PluginMetadata
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        team = sample_team_with_owner_member.team

        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", sha256_hash="b" * 64)
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        class FakePlugin(AssessmentPlugin):
            VERSION = "0.0.1"

            def get_metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="fake-upload-plugin",
                    version=self.VERSION,
                    category=AssessmentCategory.COMPLIANCE,
                )

            def assess(self, sbom_id, sbom_path, dependency_status=None, context=None):
                return AssessmentResult(
                    plugin_name="fake-upload-plugin",
                    plugin_version=self.VERSION,
                    category=AssessmentCategory.COMPLIANCE.value,
                    assessed_at="2026-04-08T00:00:00Z",
                    summary=AssessmentSummary(
                        total_findings=0, pass_count=0, fail_count=0, warning_count=0, error_count=0
                    ),
                    findings=[],
                )

        sbom_instance_mock = MagicMock()
        sbom_instance_mock.sha256_hash = "b" * 64
        sbom_instance_mock.format = "cyclonedx"
        sbom_instance_mock.format_version = "1.6"
        sbom_instance_mock.name = "s"
        sbom_instance_mock.version = ""
        sbom_instance_mock.component_id = component.id
        sbom_instance_mock.component = component
        sbom_instance_mock.bom_type = "sbom"
        monkeypatch.setattr(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            lambda sid: (sbom_instance_mock, b'{"bomFormat":"CycloneDX","specVersion":"1.6"}'),
        )

        orchestrator = PluginOrchestrator()
        result_run = orchestrator.run_assessment(
            sbom_id=sbom.id,
            plugin=FakePlugin(),
            run_reason=RunReason.ON_UPLOAD,
            # release_id omitted — legacy / upload-path
        )

        assert result_run is not None
        result_run.refresh_from_db()
        assert result_run.release_id is None


@pytest.mark.django_db
class TestTriggerToOrchestratorIntegration:
    """End-to-end integration covering the full pipeline from ReleaseArtifact
    creation through AssessmentRun persistence. Goes through real Django
    signals, real enqueue_assessments_for_sbom, real enqueue_assessment,
    and a synchronously-invoked run_assessment_task. Stubs only the SBOM
    bytes fetch (to avoid S3) and the SBOM signal handler (to isolate the
    ReleaseArtifact signal).
    """

    def test_release_artifact_creation_results_in_assessment_run_with_correct_release_id(
        self, sample_team_with_owner_member, monkeypatch
    ):
        from unittest.mock import MagicMock

        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.models import AssessmentRun, TeamPluginSettings
        from sbomify.apps.plugins.sdk.base import AssessmentPlugin
        from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason
        from sbomify.apps.plugins.sdk.results import AssessmentResult, AssessmentSummary, PluginMetadata
        from sbomify.apps.plugins.tasks import run_assessment_task
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        # Reconcile registry so dependency-track exists with requires_release=True
        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        team = sample_team_with_owner_member.team
        TeamPluginSettings.objects.create(team=team, enabled_plugins=["dependency-track"])

        product = Product.objects.create(name="p", team=team)
        release = Release.objects.create(product=product, name="v1", version="1.0.0")

        # Swap DT plugin with a fake that succeeds without network/DT calls
        class FakeDT(AssessmentPlugin):
            VERSION = "1.1.0"

            def get_metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="dependency-track",
                    version=self.VERSION,
                    category=AssessmentCategory.SECURITY,
                    supported_bom_types=["sbom"],
                    requires_release=True,
                )

            def assess(self, sbom_id, sbom_path, dependency_status=None, context=None):
                # Record that assess was called with the expected release_id
                assert context is not None
                assert context.release_id == str(release.pk)
                return AssessmentResult(
                    plugin_name="dependency-track",
                    plugin_version=self.VERSION,
                    category=AssessmentCategory.SECURITY.value,
                    assessed_at="2026-04-08T00:00:00Z",
                    summary=AssessmentSummary(
                        total_findings=0, pass_count=0, fail_count=0, warning_count=0, error_count=0
                    ),
                    findings=[],
                )

        monkeypatch.setattr(
            "sbomify.apps.plugins.orchestrator.PluginOrchestrator.get_plugin_instance",
            lambda self, name, config=None: FakeDT(),
        )

        # Make enqueue_assessment run the task synchronously instead of going through Dramatiq
        def fake_send_with_options(*args, **kwargs):
            # Invoke the task body synchronously with the captured kwargs
            run_assessment_task.fn(**kwargs["kwargs"])

        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.transaction.on_commit",
            lambda fn: fn(),
        )
        monkeypatch.setattr(
            run_assessment_task,
            "send_with_options",
            fake_send_with_options,
        )

        # Stub get_sbom_data_bytes so the orchestrator doesn't hit S3
        sbom_component = Component.objects.create(name="c", team=team)
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            sbom = SBOM.objects.create(name="s", component=sbom_component, format="cyclonedx", sha256_hash="c" * 64)
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        sbom_instance_mock = MagicMock()
        sbom_instance_mock.sha256_hash = "c" * 64
        sbom_instance_mock.format = "cyclonedx"
        sbom_instance_mock.format_version = "1.6"
        sbom_instance_mock.name = sbom.name
        sbom_instance_mock.version = ""
        sbom_instance_mock.component_id = sbom_component.id
        sbom_instance_mock.component = sbom_component
        sbom_instance_mock.bom_type = "sbom"
        monkeypatch.setattr(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            lambda sid: (sbom_instance_mock, b'{"bomFormat":"CycloneDX","specVersion":"1.6"}'),
        )

        # Fire the end-to-end pipeline: creating a ReleaseArtifact should trigger the signal,
        # run the full plugin pipeline, and result in an AssessmentRun with release_id set.
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        # Verify an AssessmentRun was created with the correct release_id
        runs = AssessmentRun.objects.filter(sbom_id=sbom.id, plugin_name="dependency-track")
        assert runs.count() == 1, f"Expected exactly one AssessmentRun, got {runs.count()}"
        run = runs.first()
        assert run.release_id == release.pk
        assert run.release == release
        assert run.run_reason == RunReason.ON_RELEASE_ASSOCIATION.value
        assert run.status == "completed"


@pytest.mark.django_db
class TestOrchestratorHandlesDeletedReleaseToctou:
    """When the Release referenced by release_id is deleted between task
    enqueue and worker execution, the orchestrator's AssessmentRun.create()
    would raise IntegrityError on the FK constraint. The fix catches this
    and records the run with release=None, passing the original release_id
    through SBOMContext so the DT plugin can return a deterministic
    'release-deleted' skipped finding.
    """

    def test_run_assessment_records_null_release_when_release_id_is_stale(
        self, sample_team_with_owner_member, monkeypatch
    ):
        from typing import Any
        from unittest.mock import MagicMock

        from django.db import IntegrityError
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator
        from sbomify.apps.plugins.sdk.base import AssessmentPlugin
        from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason
        from sbomify.apps.plugins.sdk.results import AssessmentResult, AssessmentSummary, PluginMetadata
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        team = sample_team_with_owner_member.team

        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", sha256_hash="d" * 64)
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        # Stale release_id that points to a non-existent Release. In a
        # PostgreSQL production environment the FK constraint raises
        # IntegrityError on INSERT; in SQLite test mode FK enforcement may
        # be off, so we mock AssessmentRun.objects.create to raise
        # IntegrityError on the first call (with release_id set) and pass
        # through on the second call (with release_id=None). This exercises
        # the orchestrator's except branch deterministically across backends.
        stale_release_id = "deadbeef1234"

        captured_context: list[Any] = []

        class FakePlugin(AssessmentPlugin):
            VERSION = "0.0.1"

            def get_metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="fake-release-plugin",
                    version=self.VERSION,
                    category=AssessmentCategory.COMPLIANCE,
                    requires_release=True,
                )

            def assess(self, sbom_id, sbom_path, dependency_status=None, context=None):
                captured_context.append(context)
                return AssessmentResult(
                    plugin_name="fake-release-plugin",
                    plugin_version=self.VERSION,
                    category=AssessmentCategory.COMPLIANCE.value,
                    assessed_at="2026-04-08T00:00:00Z",
                    summary=AssessmentSummary(
                        total_findings=0, pass_count=0, fail_count=0, warning_count=0, error_count=0
                    ),
                    findings=[],
                )

        sbom_instance_mock = MagicMock()
        sbom_instance_mock.sha256_hash = "d" * 64
        sbom_instance_mock.format = "cyclonedx"
        sbom_instance_mock.format_version = "1.6"
        sbom_instance_mock.name = "s"
        sbom_instance_mock.version = ""
        sbom_instance_mock.component_id = component.id
        sbom_instance_mock.component = component
        sbom_instance_mock.bom_type = "sbom"
        monkeypatch.setattr(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            lambda sid: (sbom_instance_mock, b'{"bomFormat":"CycloneDX","specVersion":"1.6"}'),
        )

        # Wrap AssessmentRun.objects.create so the first call (with the stale
        # release_id) raises IntegrityError and the second call (with
        # release_id=None from the except branch) proceeds normally.
        original_create = AssessmentRun.objects.create

        def side_effect_create(**kwargs):
            if kwargs.get("release_id") == stale_release_id:
                raise IntegrityError("simulated FK constraint violation for stale release_id")
            return original_create(**kwargs)

        monkeypatch.setattr(AssessmentRun.objects, "create", side_effect_create)

        orchestrator = PluginOrchestrator()
        result_run = orchestrator.run_assessment(
            sbom_id=sbom.id,
            plugin=FakePlugin(),
            run_reason=RunReason.ON_RELEASE_ASSOCIATION,
            release_id=stale_release_id,
        )

        # The orchestrator should NOT have crashed — it should have caught
        # the IntegrityError and recorded the run with release=None.
        assert result_run is not None
        result_run.refresh_from_db()
        assert result_run.release_id is None, (
            "AssessmentRun.release should be NULL when the original release_id is stale"
        )

        # The plugin should still have received the ORIGINAL release_id via
        # SBOMContext so it can return a deterministic skipped finding.
        assert len(captured_context) == 1
        assert captured_context[0].release_id == stale_release_id

        # Sanity: exactly one AssessmentRun was created (the first create
        # raised before hitting the DB, the second succeeded).
        assert AssessmentRun.objects.filter(sbom_id=sbom.id).count() == 1


@pytest.mark.django_db
class TestSkippedRunsNotCountedAsPassing:
    """Regression: skipped AssessmentRuns (result.metadata.skipped=True)
    must not be counted as passing in status summaries, badge responses, or
    public 'passing assessments' aggregations. Otherwise a DT scan that was
    skipped due to missing release association would make the SBOM appear
    'all green' when in reality it was never actually scanned.
    """

    def _make_sbom_with_runs(self, sample_team_with_owner_member, runs_spec):
        """Create an SBOM with AssessmentRuns from a list of specs.

        runs_spec: list of dicts with keys plugin_name, status, result.
        Returns the SBOM instance.
        """
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        team = sample_team_with_owner_member.team
        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            component = Component.objects.create(name="c", team=team)
            sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        for spec in runs_spec:
            AssessmentRun.objects.create(
                sbom=sbom,
                plugin_name=spec["plugin_name"],
                plugin_version="1.0.0",
                plugin_config_hash="abc",
                category=spec.get("category", "security"),
                run_reason="on_upload",
                status=spec["status"],
                result=spec.get("result"),
            )
        return sbom

    def test_is_run_passing_returns_false_for_skipped_run(self, sample_team_with_owner_member):
        """_is_run_passing in public_assessment_utils must treat skipped runs as non-passing."""
        from sbomify.apps.plugins.public_assessment_utils import _is_run_passing, _is_run_skipped

        sbom = self._make_sbom_with_runs(
            sample_team_with_owner_member,
            [
                {
                    "plugin_name": "dependency-track",
                    "status": "completed",
                    "result": {
                        "summary": {
                            "total_findings": 1,
                            "pass_count": 0,
                            "fail_count": 0,
                            "warning_count": 1,
                            "error_count": 0,
                        },
                        "metadata": {"skipped": True},
                    },
                }
            ],
        )

        from sbomify.apps.plugins.models import AssessmentRun

        run = AssessmentRun.objects.get(sbom=sbom)
        assert _is_run_skipped(run) is True
        assert _is_run_passing(run) is False, "skipped run must NOT be considered passing"

    def test_status_summary_counts_skipped_separately(self, sample_team_with_owner_member):
        """_compute_status_summary must count skipped runs in skipped_count, not passing_count."""
        from sbomify.apps.plugins.apis import _compute_status_summary
        from sbomify.apps.plugins.models import AssessmentRun

        sbom = self._make_sbom_with_runs(
            sample_team_with_owner_member,
            [
                # NTIA: passing
                {
                    "plugin_name": "ntia-minimum-elements-2021",
                    "category": "compliance",
                    "status": "completed",
                    "result": {
                        "summary": {"total_findings": 0, "pass_count": 7, "fail_count": 0, "error_count": 0},
                    },
                },
                # DT: skipped (no release association)
                {
                    "plugin_name": "dependency-track",
                    "category": "security",
                    "status": "completed",
                    "result": {
                        "summary": {"total_findings": 1, "warning_count": 1, "fail_count": 0, "error_count": 0},
                        "metadata": {"skipped": True},
                    },
                },
            ],
        )

        runs = list(AssessmentRun.objects.filter(sbom=sbom))
        summary = _compute_status_summary(runs)

        assert summary.passing_count == 1, "only NTIA should be counted as passing"
        assert summary.skipped_count == 1, "DT should be counted as skipped"
        assert summary.failing_count == 0
        assert summary.total_assessments == 2
        assert summary.overall_status == "all_pass", "overall_status should reflect the real passing run"

    def test_status_summary_with_only_skipped_runs_is_no_assessments(self, sample_team_with_owner_member):
        """If every run is skipped, overall_status should be no_assessments — not all_pass."""
        from sbomify.apps.plugins.apis import _compute_status_summary
        from sbomify.apps.plugins.models import AssessmentRun

        sbom = self._make_sbom_with_runs(
            sample_team_with_owner_member,
            [
                {
                    "plugin_name": "dependency-track",
                    "category": "security",
                    "status": "completed",
                    "result": {
                        "summary": {"total_findings": 1, "warning_count": 1, "fail_count": 0, "error_count": 0},
                        "metadata": {"skipped": True},
                    },
                },
            ],
        )

        runs = list(AssessmentRun.objects.filter(sbom=sbom))
        summary = _compute_status_summary(runs)

        assert summary.passing_count == 0
        assert summary.skipped_count == 1
        assert summary.overall_status == "no_assessments", "a run that was skipped is not an 'all pass' signal"

    def test_badge_endpoint_exposes_skipped_as_distinct_status(self, sample_team_with_owner_member, client):
        """get_sbom_assessment_badge must surface status='skipped' for skipped runs so
        frontends can render a neutral badge instead of a green 'pass' badge.
        """
        from sbomify.apps.plugins.apis import get_sbom_assessment_badge

        sbom = self._make_sbom_with_runs(
            sample_team_with_owner_member,
            [
                {
                    "plugin_name": "dependency-track",
                    "category": "security",
                    "status": "completed",
                    "result": {
                        "summary": {"total_findings": 1, "warning_count": 1, "fail_count": 0, "error_count": 0},
                        "metadata": {"skipped": True},
                    },
                },
            ],
        )

        # Call the endpoint function directly with a fake request
        from unittest.mock import MagicMock

        fake_request = MagicMock()
        response = get_sbom_assessment_badge(fake_request, sbom.id)

        assert response.skipped_count == 1
        assert len(response.plugins) == 1
        assert response.plugins[0]["status"] == "skipped"
        assert response.plugins[0]["name"] == "dependency-track"

    def test_run_to_schema_prefetched_display_names_no_n_plus_one(self, sample_team_with_owner_member):
        """_run_to_schema with a prefetched display_names dict must not issue per-run
        RegisteredPlugin queries — proves the N+1 fix.
        """
        from django.db import connection

        from sbomify.apps.plugins.apis import _get_plugin_display_names_map, _run_to_schema
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.models import AssessmentRun

        # Ensure dependency-track and NTIA are in the registry
        config = PluginsConfig.create("sbomify.apps.plugins")
        config._register_builtin_plugins()  # noqa: SLF001 — public entry is a post_migrate signal; only private method is testable

        sbom = self._make_sbom_with_runs(
            sample_team_with_owner_member,
            [
                {"plugin_name": "dependency-track", "category": "security", "status": "completed"},
                {"plugin_name": "ntia-minimum-elements-2021", "category": "compliance", "status": "completed"},
                {"plugin_name": "dependency-track", "category": "security", "status": "completed"},
                {"plugin_name": "ntia-minimum-elements-2021", "category": "compliance", "status": "completed"},
                {"plugin_name": "dependency-track", "category": "security", "status": "completed"},
            ],
        )
        runs = list(AssessmentRun.objects.filter(sbom=sbom))
        assert len(runs) == 5

        # Prefetch display names once
        display_names = _get_plugin_display_names_map({r.plugin_name for r in runs})
        assert "dependency-track" in display_names
        assert "ntia-minimum-elements-2021" in display_names

        # Serialize all 5 runs using the prefetched map. With
        # CaptureQueriesContext we verify that ZERO additional queries are
        # issued during serialization — proving the N+1 fix.
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            schemas = [_run_to_schema(run, display_names) for run in runs]

        assert len(schemas) == 5
        assert len(captured.captured_queries) == 0, (
            f"_run_to_schema should issue zero queries when display_names is prefetched; "
            f"got {len(captured.captured_queries)} queries: "
            f"{[q['sql'] for q in captured.captured_queries]}"
        )
        for schema in schemas:
            assert schema.plugin_display_name is not None, (
                "prefetched display_name should be populated for every serialized run"
            )
