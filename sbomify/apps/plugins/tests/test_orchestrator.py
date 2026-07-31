"""Tests for the PluginOrchestrator."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.builtins.checksum import ChecksumPlugin
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.plugins.orchestrator import (
    PluginOrchestrator,
    PluginOrchestratorError,
)
from sbomify.apps.plugins.sdk.base import AssessmentPlugin, SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.utils import SBOMDataError
from sbomify.apps.teams.models import Team


class MockPlugin(AssessmentPlugin):
    """A mock plugin for testing."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="mock-plugin",
            version="1.0.0",
            category=AssessmentCategory.COMPLIANCE,
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        return AssessmentResult(
            plugin_name="mock-plugin",
            plugin_version="1.0.0",
            category="compliance",
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(total_findings=1, pass_count=1),
            findings=[
                Finding(
                    id="mock:test",
                    title="Mock Finding",
                    description="Test finding from mock plugin",
                    status="pass",
                )
            ],
        )


class FailingPlugin(AssessmentPlugin):
    """A plugin that always fails for testing error handling."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="failing-plugin",
            version="1.0.0",
            category=AssessmentCategory.SECURITY,
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        raise ValueError("Plugin intentionally failed")


@pytest.fixture
def test_team(db) -> Team:
    """Create a test team."""
    BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "max_products": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    team = Team.objects.create(name="Test Team", billing_plan="community")
    yield team
    team.delete()


@pytest.fixture
def test_component(test_team: Team):
    """Create a test component."""
    component = Component.objects.create(team=test_team, name="Test Component")
    yield component
    component.delete()


@pytest.fixture
def test_sbom(test_component):
    """Create a test SBOM."""
    sbom = SBOM.objects.create(
        name="test-sbom",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="test.json",
        component=test_component,
    )
    yield sbom
    sbom.delete()


@pytest.fixture
def mock_sbom_data():
    """Sample SBOM data for testing."""
    return json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "components": [],
        }
    ).encode("utf-8")


@pytest.fixture
def registered_checksum_plugin(db):
    """Register the checksum plugin for testing."""
    plugin = RegisteredPlugin.objects.create(
        name="checksum",
        display_name="Checksum Plugin",
        description="Computes SBOM checksum",
        category=AssessmentCategory.COMPLIANCE.value,
        version="1.0.0",
        plugin_class_path="sbomify.apps.plugins.builtins.checksum.ChecksumPlugin",
        is_enabled=True,
    )
    yield plugin
    plugin.delete()


@pytest.mark.django_db
class TestPluginOrchestrator:
    """Tests for PluginOrchestrator class."""

    def test_run_assessment_success(self, test_sbom, mock_sbom_data, mocker) -> None:
        """Test successful assessment run."""
        # Mock get_sbom_data_bytes
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )

        orchestrator = PluginOrchestrator()
        plugin = MockPlugin()

        run = orchestrator.run_assessment(
            sbom_id=test_sbom.id,
            plugin=plugin,
            run_reason=RunReason.ON_UPLOAD,
        )

        assert run.status == RunStatus.COMPLETED.value
        assert run.plugin_name == "mock-plugin"
        assert run.plugin_version == "1.0.0"
        assert run.category == "compliance"
        assert run.result is not None
        assert run.result["summary"]["total_findings"] == 1
        assert run.input_content_digest != ""
        assert run.started_at is not None
        assert run.completed_at is not None

    def test_run_assessment_sbom_not_found(self, db) -> None:
        """Test error when SBOM does not exist in database."""
        orchestrator = PluginOrchestrator()
        plugin = MockPlugin()

        non_existent_sbom_id = "nonexistent123"

        with pytest.raises(PluginOrchestratorError) as exc_info:
            orchestrator.run_assessment(
                sbom_id=non_existent_sbom_id,
                plugin=plugin,
                run_reason=RunReason.ON_UPLOAD,
            )

        assert "not found" in str(exc_info.value).lower()
        assert non_existent_sbom_id in str(exc_info.value)
        # Verify no AssessmentRun was created
        assert AssessmentRun.objects.filter(sbom_id=non_existent_sbom_id).count() == 0

    def test_run_assessment_sbom_fetch_error(self, test_sbom, mocker) -> None:
        """Test handling of SBOM fetch error."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            side_effect=SBOMDataError("SBOM not found"),
        )

        orchestrator = PluginOrchestrator()
        plugin = MockPlugin()

        run = orchestrator.run_assessment(
            sbom_id=test_sbom.id,
            plugin=plugin,
            run_reason=RunReason.ON_UPLOAD,
        )

        assert run.status == RunStatus.FAILED.value
        assert "SBOM not found" in run.error_message
        assert run.completed_at is not None

    def test_run_assessment_plugin_error(self, test_sbom, mock_sbom_data, mocker) -> None:
        """Test handling of plugin execution error."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )

        orchestrator = PluginOrchestrator()
        plugin = FailingPlugin()

        run = orchestrator.run_assessment(
            sbom_id=test_sbom.id,
            plugin=plugin,
            run_reason=RunReason.MANUAL,
        )

        assert run.status == RunStatus.FAILED.value
        assert "Plugin intentionally failed" in run.error_message

    def test_get_plugin_instance_success(self, registered_checksum_plugin, db) -> None:
        """Test loading a plugin by name."""
        orchestrator = PluginOrchestrator()

        plugin = orchestrator.get_plugin_instance("checksum")

        assert isinstance(plugin, ChecksumPlugin)
        metadata = plugin.get_metadata()
        assert metadata.name == "checksum"

    def test_get_plugin_instance_not_registered(self, db) -> None:
        """Test error when plugin is not registered."""
        orchestrator = PluginOrchestrator()

        with pytest.raises(PluginOrchestratorError) as exc_info:
            orchestrator.get_plugin_instance("nonexistent")

        assert "not registered" in str(exc_info.value)

    def test_get_plugin_instance_disabled(self, db) -> None:
        """Test error when plugin is disabled."""
        RegisteredPlugin.objects.create(
            name="disabled-plugin",
            display_name="Disabled Plugin",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="sbomify.apps.plugins.builtins.checksum.ChecksumPlugin",
            is_enabled=False,
        )

        orchestrator = PluginOrchestrator()

        with pytest.raises(PluginOrchestratorError) as exc_info:
            orchestrator.get_plugin_instance("disabled-plugin")

        assert "disabled" in str(exc_info.value)

    def test_run_assessment_by_name(self, test_sbom, mock_sbom_data, registered_checksum_plugin, mocker) -> None:
        """Test running assessment by plugin name."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )

        orchestrator = PluginOrchestrator()

        run = orchestrator.run_assessment_by_name(
            sbom_id=test_sbom.id,
            plugin_name="checksum",
            run_reason=RunReason.MANUAL,
        )

        assert run.status == RunStatus.COMPLETED.value
        assert run.plugin_name == "checksum"
        # Without a stored hash, the plugin produces a warning finding
        assert "checksum:no-stored-hash" in str(run.result)

    def test_assessment_run_records_created(self, test_sbom, mock_sbom_data, mocker) -> None:
        """Test that AssessmentRun records are created in the database."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )

        orchestrator = PluginOrchestrator()
        plugin = MockPlugin()

        initial_count = AssessmentRun.objects.count()

        orchestrator.run_assessment(
            sbom_id=test_sbom.id,
            plugin=plugin,
            run_reason=RunReason.ON_UPLOAD,
        )

        assert AssessmentRun.objects.count() == initial_count + 1


@pytest.mark.django_db
class TestDependencyChecking:
    """Tests for plugin dependency checking methods."""

    def test_check_dependencies_no_registered_plugin(self, db) -> None:
        """Test dependency check when plugin is not registered."""
        orchestrator = PluginOrchestrator()

        result = orchestrator._check_dependencies("test-sbom", "nonexistent-plugin")

        assert result is None

    def test_check_dependencies_no_dependencies_defined(self, registered_checksum_plugin, db) -> None:
        """Test dependency check when plugin has no dependencies."""
        orchestrator = PluginOrchestrator()

        result = orchestrator._check_dependencies("test-sbom", "checksum")

        assert result is None

    def test_check_dependencies_with_requires_one_of(self, test_sbom, db) -> None:
        """Test dependency check with requires_one_of."""
        # Create a plugin with dependencies
        RegisteredPlugin.objects.create(
            name="test-dependent-plugin",
            display_name="Test Dependent Plugin",
            category="compliance",
            version="1.0.0",
            plugin_class_path="sbomify.apps.plugins.builtins.checksum.ChecksumPlugin",
            is_enabled=True,
            dependencies={
                "requires_one_of": [
                    {"type": "category", "value": "attestation"},
                ],
            },
        )

        # Create a passing attestation run
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="sbom-verification",
            plugin_version="1.0.0",
            category="attestation",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 1}},
        )

        orchestrator = PluginOrchestrator()
        result = orchestrator._check_dependencies(test_sbom.id, "test-dependent-plugin")

        assert result is not None
        assert result["requires_one_of"]["satisfied"] is True
        assert "sbom-verification" in result["requires_one_of"]["passing_plugins"]

    def test_check_one_of_no_runs(self, test_sbom, db) -> None:
        """Test _check_one_of when no runs exist."""
        orchestrator = PluginOrchestrator()

        result = orchestrator._check_one_of(
            test_sbom.id,
            [{"type": "category", "value": "attestation"}],
        )

        assert result["satisfied"] is False
        assert result["passing_plugins"] == []
        assert result["failed_plugins"] == []

    def test_check_one_of_with_passing_run(self, test_sbom, db) -> None:
        """Test _check_one_of with a passing run."""
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="sbom-verification",
            plugin_version="1.0.0",
            category="attestation",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 1}},
        )

        orchestrator = PluginOrchestrator()
        result = orchestrator._check_one_of(
            test_sbom.id,
            [{"type": "category", "value": "attestation"}],
        )

        assert result["satisfied"] is True
        assert "sbom-verification" in result["passing_plugins"]

    def test_check_one_of_with_failing_run(self, test_sbom, db) -> None:
        """Test _check_one_of with a failing run."""
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="sbom-verification",
            plugin_version="1.0.0",
            category="attestation",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 1, "error_count": 0}},
        )

        orchestrator = PluginOrchestrator()
        result = orchestrator._check_one_of(
            test_sbom.id,
            [{"type": "category", "value": "attestation"}],
        )

        assert result["satisfied"] is False
        assert result["passing_plugins"] == []
        assert "sbom-verification" in result["failed_plugins"]

    def test_check_one_of_by_plugin_name(self, test_sbom, db) -> None:
        """Test _check_one_of with specific plugin dependency."""
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="specific-plugin",
            plugin_version="1.0.0",
            category="security",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 1}},
        )

        orchestrator = PluginOrchestrator()
        result = orchestrator._check_one_of(
            test_sbom.id,
            [{"type": "plugin", "value": "specific-plugin"}],
        )

        assert result["satisfied"] is True
        assert "specific-plugin" in result["passing_plugins"]

    def test_check_all_of_all_satisfied(self, test_sbom, db) -> None:
        """Test _check_all_of when all dependencies are satisfied."""
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="plugin-a",
            plugin_version="1.0.0",
            category="compliance",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 1}},
        )
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="plugin-b",
            plugin_version="1.0.0",
            category="security",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 1}},
        )

        orchestrator = PluginOrchestrator()
        result = orchestrator._check_all_of(
            test_sbom.id,
            [
                {"type": "plugin", "value": "plugin-a"},
                {"type": "plugin", "value": "plugin-b"},
            ],
        )

        assert result["satisfied"] is True
        assert "plugin-a" in result["passing_plugins"]
        assert "plugin-b" in result["passing_plugins"]

    def test_check_all_of_one_missing(self, test_sbom, db) -> None:
        """Test _check_all_of when one dependency is missing."""
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="plugin-a",
            plugin_version="1.0.0",
            category="compliance",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 1}},
        )

        orchestrator = PluginOrchestrator()
        result = orchestrator._check_all_of(
            test_sbom.id,
            [
                {"type": "plugin", "value": "plugin-a"},
                {"type": "plugin", "value": "plugin-b"},  # This one is missing
            ],
        )

        assert result["satisfied"] is False
        assert "plugin-a" in result["passing_plugins"]

    def test_check_all_of_one_failing(self, test_sbom, db) -> None:
        """Test _check_all_of when one dependency is failing."""
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="plugin-a",
            plugin_version="1.0.0",
            category="compliance",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 1}},
        )
        AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="plugin-b",
            plugin_version="1.0.0",
            category="security",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={
                "summary": {
                    "total_findings": 1,
                    "by_severity": {"critical": 0, "high": 1, "medium": 0, "low": 0},
                }
            },  # Failing - has vulnerabilities
        )

        orchestrator = PluginOrchestrator()
        result = orchestrator._check_all_of(
            test_sbom.id,
            [
                {"type": "plugin", "value": "plugin-a"},
                {"type": "plugin", "value": "plugin-b"},
            ],
        )

        assert result["satisfied"] is False
        assert "plugin-a" in result["passing_plugins"]
        assert "plugin-b" in result["failed_plugins"]

    def test_is_passing_with_no_failures(self, test_sbom, db) -> None:
        """Test _is_passing returns True when no failures or errors."""
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="test-plugin",
            plugin_version="1.0.0",
            category="compliance",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 1}},
        )

        orchestrator = PluginOrchestrator()
        assert orchestrator._is_passing(run) is True

    def test_is_passing_with_failures(self, test_sbom, db) -> None:
        """Test _is_passing returns False when there are failures."""
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="test-plugin",
            plugin_version="1.0.0",
            category="compliance",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 1, "error_count": 0}},
        )

        orchestrator = PluginOrchestrator()
        assert orchestrator._is_passing(run) is False

    def test_is_passing_with_errors(self, test_sbom, db) -> None:
        """Test _is_passing returns False when there are errors."""
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="test-plugin",
            plugin_version="1.0.0",
            category="compliance",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 1}},
        )

        orchestrator = PluginOrchestrator()
        assert orchestrator._is_passing(run) is False

    def test_is_passing_with_no_result(self, test_sbom, db) -> None:
        """Test _is_passing returns False when result is None."""
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="test-plugin",
            plugin_version="1.0.0",
            category="compliance",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result=None,
        )

        orchestrator = PluginOrchestrator()
        assert orchestrator._is_passing(run) is False

    def test_is_passing_warnings_only_is_not_passing(self, test_sbom, db) -> None:
        """A run with only warnings (zero passes) must NOT count as passing.

        Regression test for the latent bug behind the BSI / github-attestation
        false-positive: a plugin that emits warning findings only (e.g. the
        old github-attestation plugin returning a "no VCS info" warning) had
        ``fail_count=0, error_count=0`` and was treated as passing — silently
        satisfying ``requires_one_of`` dependency gates with no positive
        evidence.
        """
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="test-plugin",
            plugin_version="1.0.0",
            category="attestation",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 0, "warning_count": 3}},
        )

        orchestrator = PluginOrchestrator()
        assert orchestrator._is_passing(run) is False

    def test_is_passing_security_unaffected_by_pass_count(self, test_sbom, db) -> None:
        """Security plugins remain governed by ``by_severity`` totals, not pass_count.

        Vulnerability scanners report a clean SBOM with empty ``by_severity``
        and zero ``pass_count`` — the run is still passing.
        """
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="vuln-scanner",
            plugin_version="1.0.0",
            category="security",
            run_reason="manual",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"by_severity": {}, "pass_count": 0}},
        )

        orchestrator = PluginOrchestrator()
        assert orchestrator._is_passing(run) is True


@pytest.mark.django_db
class TestFinalizeRetryExhausted:
    """``finalize_retry_exhausted`` flips a stuck-PENDING run to a terminal state.

    Regression for the production-discovered bug where the task layer's
    ``RetryLaterError`` exhaustion branch returned a response dict
    without updating the AssessmentRun row, leaving it stuck in
    ``PENDING`` forever — invisible to ``_check_one_of`` (which filters
    on ``status=COMPLETED``) and producing endless spinners on the
    SBOM detail page.
    """

    def test_pending_run_finalised_with_retry_exhausted_finding(self, test_sbom, db) -> None:
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="sbom-verification",
            plugin_version="2.0.0",
            category="attestation",
            run_reason="on_upload",
            status=RunStatus.PENDING.value,
        )

        orchestrator = PluginOrchestrator()
        result = orchestrator.finalize_retry_exhausted(str(run.id), "GitHub returned 404 for sha256:abc...")

        assert result is not None
        run.refresh_from_db()
        assert run.status == RunStatus.COMPLETED.value
        assert run.completed_at is not None
        assert run.error_message and "Retry budget exhausted" in run.error_message

        # Synthesised payload shape — exactly what BSI's gate consumes.
        assert run.result is not None
        # ``schema_version`` mirrors ``AssessmentResult.to_dict()`` so
        # retry-exhausted runs round-trip through any schema-version
        # consumer the same as plugin-emitted runs.
        assert run.result["schema_version"] == "1.0"
        assert run.result_schema_version == "1.0"
        summary = run.result["summary"]
        assert summary["fail_count"] == 0
        assert summary["error_count"] == 1
        assert summary["pass_count"] == 0
        assert summary["total_findings"] == 1

        finding = run.result["findings"][0]
        assert finding["id"] == "sbom-verification:retry-exhausted"
        assert finding["status"] == "error"
        assert "GitHub returned 404" in finding["description"]
        assert finding["metadata"]["retry_exhausted"] is True

    def test_finalised_run_satisfies_check_one_of_query(self, test_sbom, db) -> None:
        """After finalising, BSI's ``_check_one_of`` sees the run as failed_plugins.

        This is the actual production symptom: the SBOM detail page kept
        spinning and BSI kept saying "No attestation plugin run" because
        the orchestrator's gate query filters on ``status=COMPLETED``.
        Once the run is finalised, the gate correctly classifies it as
        a failed attestation source.
        """
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="sbom-verification",
            plugin_version="2.0.0",
            category="attestation",
            run_reason="on_upload",
            status=RunStatus.PENDING.value,
        )

        orchestrator = PluginOrchestrator()
        # Before finalise: no completed attestation runs.
        before = orchestrator._check_one_of(str(test_sbom.id), [{"type": "category", "value": "attestation"}])
        assert before == {"satisfied": False, "passing_plugins": [], "failed_plugins": []}

        orchestrator.finalize_retry_exhausted(str(run.id), "transient condition persists")

        # After finalise: BSI sees ``sbom-verification`` in failed_plugins so the gate
        # produces an actionable failure message instead of "no attestation run".
        after = orchestrator._check_one_of(str(test_sbom.id), [{"type": "category", "value": "attestation"}])
        assert after["satisfied"] is False
        assert after["failed_plugins"] == ["sbom-verification"]
        assert after["passing_plugins"] == []

    def test_finalize_is_idempotent_on_terminal_state(self, test_sbom, db) -> None:
        """A run that's already COMPLETED/FAILED is left untouched."""
        run = AssessmentRun.objects.create(
            sbom_id=test_sbom.id,
            plugin_name="sbom-verification",
            plugin_version="2.0.0",
            category="attestation",
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"pass_count": 1, "fail_count": 0, "error_count": 0}},
            completed_at=datetime.now(timezone.utc),
        )
        original_completed_at = run.completed_at
        original_result = run.result

        orchestrator = PluginOrchestrator()
        result = orchestrator.finalize_retry_exhausted(str(run.id), "shouldn't matter")

        run.refresh_from_db()
        assert result is not None
        assert run.status == RunStatus.COMPLETED.value
        # Original payload preserved — no overwrite of legitimate run data.
        assert run.result == original_result
        assert run.completed_at == original_completed_at

    def test_finalize_returns_none_when_run_not_found(self, db) -> None:
        orchestrator = PluginOrchestrator()
        result = orchestrator.finalize_retry_exhausted("00000000-0000-0000-0000-000000000000", "nope")
        assert result is None


@pytest.mark.django_db
class TestCryptoAssetGate:
    """Crypto-gated plugins skip dispatch when the document holds no crypto assets."""

    def _pqc_plugin(self):
        from sbomify.apps.plugins.builtins.pqc import PqcReadinessPlugin

        return PqcReadinessPlugin()

    def test_skips_when_document_has_no_crypto_assets(self, test_sbom) -> None:
        test_sbom.has_crypto_assets = False
        test_sbom.save(update_fields=["has_crypto_assets"])

        run = PluginOrchestrator().run_assessment(
            sbom_id=test_sbom.id, plugin=self._pqc_plugin(), run_reason=RunReason.ON_UPLOAD
        )

        assert run is None

    def test_explicit_cbom_runs_even_when_stamped_crypto_free(self, test_sbom, mock_sbom_data, mocker) -> None:
        """A cbom-tagged artifact with has_crypto_assets=False is a generator
        misfire: PQC must run and warn, not skip."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )
        test_sbom.bom_type = "cbom"
        test_sbom.has_crypto_assets = False
        test_sbom.save(update_fields=["bom_type", "has_crypto_assets"])

        run = PluginOrchestrator().run_assessment(
            sbom_id=test_sbom.id, plugin=self._pqc_plugin(), run_reason=RunReason.ON_UPLOAD
        )

        assert run is not None
        assert run.status == RunStatus.COMPLETED.value
        assert run.result["findings"][0]["status"] == "warning"  # the misfire surfaces
        assert not (run.result.get("metadata") or {}).get("skipped")

    def test_runs_when_crypto_flag_unknown(self, test_sbom, mock_sbom_data, mocker) -> None:
        # Rows predating the field (None) still run: unknown is not a skip reason.
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )
        assert test_sbom.has_crypto_assets is None

        run = PluginOrchestrator().run_assessment(
            sbom_id=test_sbom.id, plugin=self._pqc_plugin(), run_reason=RunReason.ON_UPLOAD
        )

        assert run is not None
        assert run.status == RunStatus.COMPLETED.value


@pytest.mark.django_db
class TestSkippedPluginPendingCleanup:
    """A delayed enqueue materialises a PENDING row before the worker runs;
    when the orchestrator then skips (unsupported bom_type), the task must
    remove that orphan instead of leaving it Pending forever."""

    def test_skip_deletes_eager_pending_row(self, test_sbom, registered_checksum_plugin) -> None:
        from sbomify.apps.plugins.tasks import _create_pending_assessment_run, run_assessment_task

        test_sbom.bom_type = "cbom"
        test_sbom.save(update_fields=["bom_type"])
        run_id = _create_pending_assessment_run(
            sbom_id=str(test_sbom.id),
            plugin_name="checksum",  # pins supported_bom_types=["sbom"]
            run_reason=RunReason.ON_UPLOAD,
            triggered_by_user=None,
            triggered_by_token=None,
        )
        assert run_id is not None

        result = run_assessment_task(
            sbom_id=str(test_sbom.id),
            plugin_name="checksum",
            run_reason=RunReason.ON_UPLOAD.value,
            _existing_run_id=run_id,
        )

        assert result["status"] == "skipped"
        assert not AssessmentRun.objects.filter(id=run_id).exists()
