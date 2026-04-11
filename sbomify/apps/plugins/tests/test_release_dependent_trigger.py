"""Tests for the plugin trigger infrastructure (scan-once-per-SBOM model).

Covers the ``only_categories`` filter on ``enqueue_assessments_for_sbom``, the
``ReleaseArtifact`` post_save signal handler (attach task), cross-team guards,
skipped-run semantics, and the assessment badge/API layer.

Under the scan-once-per-SBOM model (sbomify/sbomify#881), SBOM upload triggers
one scan per plugin (all categories). Release associations add the release to
the existing run's M2M and call sync hooks on continuous plugins — no rescan.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason
from sbomify.apps.plugins.sdk.results import PluginMetadata


class TestPluginMetadataToDict:
    def test_to_dict_omits_requires_release(self):
        """Serialized metadata must not contain the removed requires_release key."""
        meta = PluginMetadata(
            name="example",
            version="1.0.0",
            category=AssessmentCategory.COMPLIANCE,
        )
        result = meta.to_dict()
        assert "requires_release" not in result

    def test_to_dict_includes_category(self):
        meta = PluginMetadata(
            name="example",
            version="1.0.0",
            category=AssessmentCategory.SECURITY,
        )
        result = meta.to_dict()
        assert result["category"] == "security"


class TestRunReasonEnum:
    def test_on_release_association_exists(self):
        assert RunReason.ON_RELEASE_ASSOCIATION.value == "on_release_association"


class TestDependencyTrackPluginMetadata:
    def test_metadata_category_is_security(self):
        """DT plugin metadata declares category=security (the driver for release-aware triggering)."""
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        plugin = DependencyTrackPlugin()
        meta = plugin.get_metadata()
        assert meta.category == AssessmentCategory.SECURITY

    def test_metadata_has_no_requires_release_field(self):
        """PluginMetadata must not expose the removed requires_release field."""
        from dataclasses import fields

        field_names = {f.name for f in fields(PluginMetadata)}
        assert "requires_release" not in field_names


@pytest.mark.django_db
class TestDependencyTrackSkippedFinding:
    """When the DT plugin runs against an SBOM with no release, it should
    return a 'skipped' warning finding rather than a hard error. This branch
    is reachable from cron and manual triggers for SBOMs that have no
    release association — never from the upload path after Task 9 lands.
    """

    def test_no_release_returns_warning_not_error(self, tmp_path, sample_team_with_owner_member):
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
        assert finding.id == "dependency-track:no-product"
        assert "product" in finding.description.lower()
        assert result.summary.error_count == 0
        assert result.summary.warning_count == 1

    def test_proceeds_when_product_exists_but_no_release_artifact(self, sample_team_with_owner_member, tmp_path):
        """Race case: component has product membership but ReleaseArtifact
        hasn't been committed yet (sbomify-action 2-step upload). Scan must
        proceed with empty tags, NOT return a skipped result."""
        from sbomify.apps.core.models import Component, Product, Project
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="race-test", team=team)
        product = Product.objects.create(name="p", team=team)
        project = Project.objects.create(name="proj", team=team)
        project.products.add(product)
        project.components.add(component)

        sbom = SBOM.objects.create(name="race-sbom", component=component, format="cyclonedx")
        # No ReleaseArtifact created — simulates the race window

        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_text('{"bomFormat": "CycloneDX", "specVersion": "1.6"}')

        plugin = DependencyTrackPlugin()
        with (
            patch.object(plugin, "_team_has_dt_enabled", return_value=True),
            patch.object(plugin, "_select_dt_server", side_effect=RuntimeError("no server")),
        ):
            result = plugin.assess(sbom_id=sbom.id, sbom_path=sbom_path)

        # Should NOT be skipped — the product membership check passes.
        # It will fail with "no server" from our mock, which proves it
        # passed the product-membership guard and reached server selection.
        assert result.metadata.get("skipped") is not True
        assert any("no server" in (f.description or "").lower() for f in result.findings)

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
    """The only_categories parameter splits the plugin set by category."""

    def _enable_plugins(self, team, plugin_names):
        from sbomify.apps.plugins.models import TeamPluginSettings

        TeamPluginSettings.objects.create(team=team, enabled_plugins=list(plugin_names))

    def test_only_categories_compliance_excludes_security(self, sample_team_with_owner_member, monkeypatch):
        """Passing only_categories={'compliance','attestation','license'} (upload path) excludes security plugins."""
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
            run_reason=RunReason.ON_UPLOAD,
            only_categories={"compliance", "attestation", "license"},
        )

        assert "dependency-track" not in enqueued
        assert "ntia-minimum-elements-2021" in enqueued
        assert "dependency-track" not in captured

    def test_only_categories_security_includes_only_security(self, sample_team_with_owner_member, monkeypatch):
        """Passing only_categories={'security'} (release-association path) includes only security plugins."""
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
            only_categories={"security"},
        )

        assert enqueued == ["dependency-track"]
        assert captured == ["dependency-track"]

    def test_only_categories_none_runs_everything(self, sample_team_with_owner_member, monkeypatch):
        """Passing only_categories=None (or omitting it) enqueues all enabled plugins regardless of category."""
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
            run_reason=RunReason.ON_UPLOAD,
            # only_categories defaults to None — runs everything
        )

        assert "ntia-minimum-elements-2021" in enqueued
        assert "dependency-track" in enqueued

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

        # Ensure the registry has ntia-minimum-elements-2021
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
            only_categories={"compliance", "attestation", "license"},
        )

        # NTIA should be enqueued; the missing plugin should be silently skipped
        assert "ntia-minimum-elements-2021" in enqueued
        assert "this-plugin-does-not-exist" not in enqueued
        assert "ntia-minimum-elements-2021" in captured


@pytest.mark.django_db
class TestReleaseArtifactSignalHandler:
    """Cross-cutting safety checks for the post_save → ReleaseArtifact handler
    under the scan-once-per-SBOM model. The handler does NOT trigger a rescan;
    it enqueues a lightweight ``attach_release_to_runs_task`` that extends the
    existing run's M2M and (for DT) updates project tags.
    """

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

    def test_handler_enqueues_attach_task_on_create(self, sample_team_with_owner_member, monkeypatch):
        """New artifact → one attach_release_to_runs_task.send call, no rescan."""
        captured_attach: list[dict] = []
        captured_enqueue: list[dict] = []

        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.attach_release_to_runs_task.send",
            lambda **kwargs: captured_attach.append(kwargs),
        )
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom",
            lambda **kwargs: captured_enqueue.append(kwargs) or [],
        )

        artifact = self._make_release_with_artifact(sample_team_with_owner_member)

        assert len(captured_attach) == 1
        assert captured_attach[0]["sbom_id"] == str(artifact.sbom_id)
        assert captured_attach[0]["release_id"] == str(artifact.release_id)
        assert captured_enqueue == [], "Handler must not enqueue a rescan under the scan-once-per-SBOM model"

    def test_handler_ignores_document_artifacts(self, sample_team_with_owner_member, monkeypatch):
        """Document-only ReleaseArtifacts are skipped — no attach task fired."""
        from sbomify.apps.core.models import Component
        from sbomify.apps.documents.models import Document

        captured_attach: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.attach_release_to_runs_task.send",
            lambda **kwargs: captured_attach.append(kwargs),
        )

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        document = Document.objects.create(name="d", component=component)
        self._make_release_with_artifact(sample_team_with_owner_member, document=document)

        assert captured_attach == []

    def test_handler_ignores_updates(self, sample_team_with_owner_member, monkeypatch):
        """Only post_save with created=True fires the attach; updates are skipped."""
        captured_attach: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.attach_release_to_runs_task.send",
            lambda **kwargs: captured_attach.append(kwargs),
        )

        artifact = self._make_release_with_artifact(sample_team_with_owner_member)
        captured_attach.clear()

        # Save again — should not re-fire the attach task
        artifact.save()
        assert captured_attach == []

    def test_handler_ignores_when_release_info_is_none(self, sample_team_with_owner_member, monkeypatch):
        """Defensive: if the Release lookup returns None, the handler skips silently."""
        from sbomify.apps.core.models import Component
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import attach_release_to_existing_runs

        # Create the SBOM before patching so the upload signal does not populate captured.
        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="c", team=team)
        SBOM.objects.create(name="s", component=component, format="cyclonedx")

        captured_attach: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.attach_release_to_runs_task.send",
            lambda **kwargs: captured_attach.append(kwargs),
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
            sbom_id = "fake-sbom-id"

        attach_release_to_existing_runs(sender=None, instance=_FakeArtifact(), created=True)

        assert captured_attach == []

    def test_handler_swallows_broker_failures(self, sample_team_with_owner_member, monkeypatch):
        """If attach_release_to_runs_task.send raises (broker outage), handler logs and continues."""
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        def _boom(**kwargs):
            raise RuntimeError("simulated broker outage")

        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.attach_release_to_runs_task.send",
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

    def test_handler_skips_cross_team_release_artifact(self, sample_team_with_owner_member, monkeypatch):
        """Defense-in-depth: cross-team ReleaseArtifact must not trigger attach task."""
        from django.db.models.signals import post_save

        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments
        from sbomify.apps.teams.models import Team

        captured_attach: list[dict] = []
        monkeypatch.setattr(
            "sbomify.apps.plugins.tasks.attach_release_to_runs_task.send",
            lambda **kwargs: captured_attach.append(kwargs),
        )

        team_a = sample_team_with_owner_member.team
        team_b = Team.objects.create(name="other-team")

        product_a = Product.objects.create(name="product-a", team=team_a)
        release_a = Release.objects.create(product=product_a, name="v1", version="1.0.0")
        component_b = Component.objects.create(name="component-b", team=team_b)

        post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            sbom_b = SBOM.objects.create(name="sbom-b", component=component_b, format="cyclonedx")
        finally:
            post_save.connect(trigger_plugin_assessments, sender=SBOM)

        ReleaseArtifact.objects.create(release=release_a, sbom=sbom_b)

        assert captured_attach == [], "cross-team ReleaseArtifact must not trigger attach task"


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
    exclude security category plugins (e.g., dependency-track) that need
    release context and are triggered via a separate signal path.
    """

    def test_backfill_excludes_security_plugins(self, sample_team_with_owner_member, monkeypatch):
        """Backfill uses category-based filtering: security plugins are skipped because they
        require release context and are handled by the ReleaseArtifact signal, not the
        bulk backfill path. This mirrors the upload-path behavior.
        """
        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.apps import PluginsConfig
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task
        from sbomify.apps.sboms.models import SBOM

        # Ensure registry has dependency-track (category=security) and ntia (category=compliance)
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
        # NTIA (compliance category) should still have been enqueued for the backfill
        assert "ntia-minimum-elements-2021" in captured
        # Task result should reflect what was actually enqueued (DT was skipped)
        assert result["assessments_enqueued"] >= 1


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
        # Prefetch ``releases`` M2M in addition to display names — the
        # scan-once-per-SBOM model expects both to be batched so per-run
        # serialization stays zero-query.
        runs = list(AssessmentRun.objects.filter(sbom=sbom).prefetch_related("releases"))
        assert len(runs) == 5

        # Prefetch display names once
        display_names = _get_plugin_display_names_map({r.plugin_name for r in runs})
        assert "dependency-track" in display_names
        assert "ntia-minimum-elements-2021" in display_names

        # Serialize all 5 runs using the prefetched map + prefetched releases.
        # CaptureQueriesContext verifies that ZERO additional queries are
        # issued during serialization — proving both N+1 fixes.
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
