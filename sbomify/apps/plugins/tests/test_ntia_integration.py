"""Integration tests for NTIA compliance plugin workflow.

Tests the complete workflow from SBOM creation through plugin assessment.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus
from sbomify.apps.plugins.tasks import run_assessment_task
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.signals import trigger_plugin_assessments
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
class TestNTIAPluginIntegration:
    """Integration tests for NTIA plugin workflow."""

    @pytest.fixture
    def team(self) -> Team:
        """Create a test team with business plan."""
        BillingPlan.objects.get_or_create(
            key="business",
            defaults={"name": "Business Plan"},
        )
        return Team.objects.create(
            name="Test Team",
            key="test-team-ntia",
            billing_plan="business",
        )

    @pytest.fixture
    def component(self, team: Team) -> Component:
        """Create a test component."""
        return Component.objects.create(
            name="test-component",
            team=team,
            component_type="bom",
        )

    @pytest.fixture
    def ntia_plugin(self) -> RegisteredPlugin:
        """Register the NTIA plugin."""
        plugin, _ = RegisteredPlugin.objects.update_or_create(
            name="ntia-minimum-elements-2021",
            defaults={
                "display_name": "NTIA Minimum Elements (2021)",
                "description": "NTIA compliance checking",
                "category": "compliance",
                "version": "1.0.0",
                "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
                "is_enabled": True,
            },
        )
        return plugin

    @pytest.fixture
    def compliant_cyclonedx_sbom(self) -> dict:
        """Sample compliant CycloneDX SBOM."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

    @pytest.fixture
    def non_compliant_cyclonedx_sbom(self) -> dict:
        """Sample non-compliant CycloneDX SBOM."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    # Missing version, publisher, unique identifiers
                }
            ],
            # Missing dependencies
            "metadata": {
                # Missing authors and timestamp
            },
        }

    def test_signal_triggers_plugin_assessments(
        self, team: Team, component: Component, ntia_plugin: RegisteredPlugin
    ) -> None:
        """Test that SBOM creation signal triggers plugin assessments."""
        from sbomify.apps.plugins.models import TeamPluginSettings

        # Enable the NTIA plugin for this team
        TeamPluginSettings.objects.create(
            team=team,
            enabled_plugins=["ntia-minimum-elements-2021"],
        )

        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="test.json",
            source="test",
        )

        with patch("sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom") as mock_enqueue:
            trigger_plugin_assessments(sender=SBOM, instance=sbom, created=True)

            # Scan-once-per-SBOM model: exactly one enqueue call, no category
            # filter — all enabled plugins run in one batch.
            mock_enqueue.assert_called_once()
            call_kwargs = mock_enqueue.call_args[1]
            assert call_kwargs["sbom_id"] == sbom.id
            assert call_kwargs["team_id"] == str(team.id)
            assert call_kwargs["run_reason"] == RunReason.ON_UPLOAD
            assert "only_categories" not in call_kwargs or call_kwargs.get("only_categories") is None

    def test_signal_triggers_for_all_teams(self, component: Component) -> None:
        """Test that SBOM creation signal triggers plugin assessment check for all teams.

        The actual filtering of which plugins run is handled by enqueue_assessments_for_sbom
        based on TeamPluginSettings. The compliance call always fires; security plugins
        are also enqueued if the component belongs to a product (not the case here).
        """
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="test.json",
            source="test",
        )

        with patch("sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom") as mock_enqueue:
            trigger_plugin_assessments(sender=SBOM, instance=sbom, created=True)

            # Scan-once: exactly one enqueue call with no category filter.
            mock_enqueue.assert_called_once()

    def test_full_assessment_workflow_compliant(
        self,
        team: Team,
        component: Component,
        ntia_plugin: RegisteredPlugin,
        compliant_cyclonedx_sbom: dict,
    ) -> None:
        """Test complete workflow for compliant SBOM assessment."""
        sbom = SBOM.objects.create(
            name="compliant-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="compliant.json",
            source="test",
        )

        # Mock SBOM data retrieval
        mock_sbom_bytes = json.dumps(compliant_cyclonedx_sbom).encode("utf-8")

        with patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(sbom, mock_sbom_bytes),
        ):
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.ON_UPLOAD.value,
            )

        # Verify assessment completed successfully
        assessment_run = AssessmentRun.objects.filter(sbom=sbom, plugin_name="ntia-minimum-elements-2021").first()
        assert assessment_run is not None
        assert assessment_run.status == RunStatus.COMPLETED.value
        assert assessment_run.result is not None
        assert assessment_run.result["summary"]["fail_count"] == 0
        assert assessment_run.result["summary"]["pass_count"] == 7
        assert assessment_run.completed_at is not None

    def test_full_assessment_workflow_non_compliant(
        self,
        team: Team,
        component: Component,
        ntia_plugin: RegisteredPlugin,
        non_compliant_cyclonedx_sbom: dict,
    ) -> None:
        """Test complete workflow for non-compliant SBOM assessment."""
        sbom = SBOM.objects.create(
            name="non-compliant-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="non-compliant.json",
            source="test",
        )

        # Mock SBOM data retrieval
        mock_sbom_bytes = json.dumps(non_compliant_cyclonedx_sbom).encode("utf-8")

        with patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(sbom, mock_sbom_bytes),
        ):
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.ON_UPLOAD.value,
            )

        # Verify assessment completed with failures
        assessment_run = AssessmentRun.objects.filter(sbom=sbom, plugin_name="ntia-minimum-elements-2021").first()
        assert assessment_run is not None
        assert assessment_run.status == RunStatus.COMPLETED.value
        assert assessment_run.result is not None
        assert assessment_run.result["summary"]["fail_count"] > 0

    def test_assessment_run_preserves_history(
        self,
        team: Team,
        component: Component,
        ntia_plugin: RegisteredPlugin,
        compliant_cyclonedx_sbom: dict,
    ) -> None:
        """Test that multiple assessment runs are preserved for audit trail."""
        sbom = SBOM.objects.create(
            name="history-test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="history.json",
            source="test",
        )

        mock_sbom_bytes = json.dumps(compliant_cyclonedx_sbom).encode("utf-8")

        with patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(sbom, mock_sbom_bytes),
        ):
            # Run first assessment
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.ON_UPLOAD.value,
            )

            # Run second assessment (manual re-run)
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.MANUAL.value,
            )

        # Verify both runs exist
        runs = AssessmentRun.objects.filter(sbom=sbom, plugin_name="ntia-minimum-elements-2021")
        assert runs.count() == 2

        # Both should be completed
        for run in runs:
            assert run.status == RunStatus.COMPLETED.value


class TestNTIAPluginAPIIntegration(TestCase):
    """Integration tests for NTIA plugin API endpoints."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.team = Team.objects.create(
            name="API Test Team",
            key="api-test-team",
            billing_plan="business",
        )
        BillingPlan.objects.get_or_create(
            key="business",
            defaults={"name": "Business Plan"},
        )
        self.component = Component.objects.create(
            name="api-test-component",
            team=self.team,
            component_type="bom",
        )
        RegisteredPlugin.objects.update_or_create(
            name="ntia-minimum-elements-2021",
            defaults={
                "display_name": "NTIA Minimum Elements (2021)",
                "description": "NTIA compliance checking",
                "category": "compliance",
                "version": "1.0.0",
                "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
                "is_enabled": True,
            },
        )

    def test_assessment_api_returns_ntia_results(self) -> None:
        """Test that assessment API returns NTIA plugin results."""
        from sbomify.apps.plugins.apis import get_sbom_assessments

        sbom = SBOM.objects.create(
            name="api-test-sbom",
            component=self.component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="api-test.json",
            source="test",
        )

        # Create completed assessment run with all required fields
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            category="compliance",
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            completed_at=timezone.now(),
            result={
                "plugin_name": "ntia-minimum-elements-2021",
                "plugin_version": "1.0.0",
                "category": "compliance",
                "assessed_at": timezone.now().isoformat(),
                "summary": {
                    "total_findings": 7,
                    "pass_count": 7,
                    "fail_count": 0,
                    "error_count": 0,
                    "info_count": 0,
                },
                "findings": [],
                "metadata": {
                    "standard_name": "NTIA Minimum Elements",
                    "standard_version": "2021-07",
                },
            },
        )

        # Mock request
        mock_request = MagicMock()

        response = get_sbom_assessments(mock_request, str(sbom.id))

        assert response.status_summary.overall_status == "all_pass"
        assert len(response.latest_runs) == 1
        assert response.latest_runs[0].plugin_name == "ntia-minimum-elements-2021"

    def test_badge_api_returns_status_summary(self) -> None:
        """Test that badge API returns correct status summary."""
        from sbomify.apps.plugins.apis import get_sbom_assessment_badge

        sbom = SBOM.objects.create(
            name="badge-test-sbom",
            component=self.component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="badge-test.json",
            source="test",
        )

        # Create completed assessment with failures
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            category="compliance",
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            completed_at=timezone.now(),
            result={
                "summary": {
                    "total_findings": 7,
                    "pass_count": 4,
                    "fail_count": 3,
                    "error_count": 0,
                    "info_count": 0,
                },
            },
        )

        mock_request = MagicMock()
        response = get_sbom_assessment_badge(mock_request, str(sbom.id))

        assert response.overall_status == "has_failures"
        assert response.failing_count == 1


class TestFileTypeComponentSkipped:
    """File-type components should be skipped in unique-identifier checks."""

    def test_cyclonedx_file_type_skipped_in_purl_check(self):
        """CycloneDX type=file components should not fail unique-identifiers."""
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2026-01-01T00:00:00Z",
            },
            "components": [
                {
                    "name": "django",
                    "version": "5.2.3",
                    "type": "library",
                    "purl": "pkg:pypi/django@5.2.3",
                    "publisher": "Django",
                },
                {
                    "name": "uv.lock",
                    "type": "file",
                    "hashes": [{"alg": "SHA-256", "content": "abc123"}],
                },
            ],
            "dependencies": [{"ref": "pkg:pypi/django@5.2.3", "dependsOn": []}],
        }
        plugin = NTIAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test", Path(f.name))

        uid_finding = next((f for f in result.findings if f.id == "ntia-2021:unique-identifiers"), None)
        assert uid_finding is not None
        assert uid_finding.status == "pass", f"uv.lock (type=file) should be skipped: {uid_finding.description}"

    def test_spdx_file_entry_skipped_in_purl_check(self):
        """SPDX packages with -File- in SPDXID should not fail unique-identifiers."""
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "creationInfo": {
                "created": "2026-01-01T00:00:00Z",
                "creators": ["Tool: test"],
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-django",
                    "name": "django",
                    "versionInfo": "5.2.3",
                    "supplier": "Organization: Django",
                    "downloadLocation": "NOASSERTION",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/django@5.2.3",
                        }
                    ],
                },
                {
                    "SPDXID": "SPDXRef-DocumentRoot-File-uv.lock",
                    "name": "uv.lock",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-django",
                }
            ],
        }
        plugin = NTIAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".spdx.json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test", Path(f.name))

        uid_finding = next((f for f in result.findings if f.id == "ntia-2021:unique-identifiers"), None)
        assert uid_finding is not None
        assert uid_finding.status == "pass", f"uv.lock (File entry) should be skipped: {uid_finding.description}"

    def test_cyclonedx_file_type_skipped_in_supplier_and_version_checks(self):
        """CycloneDX type=file components must also be skipped for Supplier Name
        and Component Version — not just Unique Identifiers. Generators like syft
        emit lockfiles as file-type entries which lack supplier/version by design.
        """
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2026-01-01T00:00:00Z",
            },
            "components": [
                {
                    "name": "django",
                    "version": "5.2.3",
                    "type": "library",
                    "purl": "pkg:pypi/django@5.2.3",
                    "publisher": "Django",
                },
                {
                    # No supplier, no version — file-type should be skipped
                    "name": "uv.lock",
                    "type": "file",
                    "hashes": [{"alg": "SHA-256", "content": "abc123"}],
                },
            ],
            "dependencies": [{"ref": "pkg:pypi/django@5.2.3", "dependsOn": []}],
        }
        plugin = NTIAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test", Path(f.name))

        supplier = next((f for f in result.findings if f.id == "ntia-2021:supplier-name"), None)
        version = next((f for f in result.findings if f.id == "ntia-2021:version"), None)
        assert supplier is not None, "supplier-name finding missing"
        assert version is not None, "version finding missing"
        assert supplier.status == "pass", f"file skipped for supplier: {supplier.description}"
        assert version.status == "pass", f"file skipped for version: {version.description}"

    def test_spdx_file_entry_skipped_in_supplier_and_version_checks(self):
        """SPDX File-type entries must be skipped for Supplier + Version too."""
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "creationInfo": {
                "created": "2026-01-01T00:00:00Z",
                "creators": ["Tool: test"],
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-django",
                    "name": "django",
                    "versionInfo": "5.2.3",
                    "supplier": "Organization: Django",
                    "downloadLocation": "NOASSERTION",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/django@5.2.3",
                        }
                    ],
                },
                {
                    # No supplier, no versionInfo — File entry should be skipped
                    "SPDXID": "SPDXRef-DocumentRoot-File-uv.lock",
                    "name": "uv.lock",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-django",
                }
            ],
        }
        plugin = NTIAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".spdx.json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test", Path(f.name))

        supplier = next((f for f in result.findings if f.id == "ntia-2021:supplier-name"), None)
        version = next((f for f in result.findings if f.id == "ntia-2021:version"), None)
        assert supplier is not None, "supplier-name finding missing"
        assert version is not None, "version finding missing"
        assert supplier.status == "pass", f"File entry skipped for supplier: {supplier.description}"
        assert version.status == "pass", f"File entry skipped for version: {version.description}"

    def test_cyclonedx_library_component_still_fails_when_missing_fields(self):
        """Regression guard: file-type skip must not accidentally silence real failures.

        A non-file component missing supplier or version must still surface the
        failure. This test lives alongside the skip tests so that any future
        refactor of the is_file_type check immediately breaks if the skip logic
        accidentally widens.
        """
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2026-01-01T00:00:00Z",
            },
            "components": [
                {
                    # Library-type with missing supplier AND missing version
                    "name": "unmaintained-lib",
                    "type": "library",
                    "purl": "pkg:pypi/unmaintained-lib@unknown",
                },
                {
                    # File-type (should still be skipped)
                    "name": "uv.lock",
                    "type": "file",
                },
            ],
            "dependencies": [{"ref": "pkg:pypi/unmaintained-lib@unknown", "dependsOn": []}],
        }
        plugin = NTIAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test", Path(f.name))

        supplier = next((f for f in result.findings if f.id == "ntia-2021:supplier-name"), None)
        version = next((f for f in result.findings if f.id == "ntia-2021:version"), None)
        assert supplier is not None and supplier.status == "fail", "library component without supplier must still fail"
        assert "unmaintained-lib" in (supplier.description or "")
        assert "uv.lock" not in (supplier.description or ""), "file-type must not appear in failure list"
        assert version is not None and version.status == "fail", "library component without version must still fail"
        assert "unmaintained-lib" in (version.description or "")

    def test_cyclonedx_file_type_case_insensitive(self):
        """type matching is case-insensitive — File, FILE, file all skipped."""
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"authors": [{"name": "Dev"}], "timestamp": "2026-01-01T00:00:00Z"},
            "components": [
                {
                    "name": "django",
                    "version": "5.2.3",
                    "type": "library",
                    "purl": "pkg:pypi/django@5.2.3",
                    "publisher": "Django",
                },
                {"name": "lock1.lock", "type": "File"},
                {"name": "lock2.lock", "type": "FILE"},
                {"name": "lock3.lock", "type": "file"},
            ],
            "dependencies": [{"ref": "pkg:pypi/django@5.2.3", "dependsOn": []}],
        }
        plugin = NTIAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test", Path(f.name))

        for fid in ("ntia-2021:supplier-name", "ntia-2021:version", "ntia-2021:unique-identifiers"):
            finding = next((f for f in result.findings if f.id == fid), None)
            assert finding is not None and finding.status == "pass", (
                f"{fid}: all case variations of type=file must be skipped, got {finding.status if finding else None}: "
                f"{finding.description if finding else None}"
            )


class TestFileTypeSkipAcrossGenerators:
    """Verify the file-type skip works for SBOMs produced by multiple generators,
    not just syft's specific output format (which is what Lithium uses).

    Different tools emit file-like metadata with different conventions:
    - syft:               SPDXRef-DocumentRoot-File-<name>-<hash>
    - Microsoft sbom-tool: SPDXRef-File--<name>-<hash> (double dash)
    - Clean convention:   SPDXRef-File-<name>
    - cdxgen / cyclonedx-py: CycloneDX type="file" with mime-type set

    The common marker the plugin uses is the "-File-" substring in SPDXID for
    SPDX and "type == 'file'" for CycloneDX. These tests prove the heuristic
    covers the practical generator ecosystem, not only Lithium's setup.
    """

    def _assess(self, sbom_data: dict):
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        plugin = NTIAMinimumElementsPlugin()
        suffix = ".spdx.json" if "spdxVersion" in sbom_data else ".json"
        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test", Path(f.name))

    def _base_spdx_doc(self, packages: list[dict]) -> dict:
        return {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "creationInfo": {
                "created": "2026-01-01T00:00:00Z",
                "creators": ["Tool: test"],
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-django",
                    "name": "django",
                    "versionInfo": "5.2.3",
                    "supplier": "Organization: Django",
                    "downloadLocation": "NOASSERTION",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/django@5.2.3",
                        }
                    ],
                },
                *packages,
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-django",
                }
            ],
        }

    def test_spdx_syft_document_root_file_naming(self):
        """syft emits SPDXRef-DocumentRoot-File-<name>-<hash>."""
        sbom = self._base_spdx_doc(
            [
                {
                    "SPDXID": "SPDXRef-DocumentRoot-File-uv.lock-e473982c",
                    "name": "uv.lock",
                    "downloadLocation": "NOASSERTION",
                }
            ]
        )
        result = self._assess(sbom)
        for fid in ("ntia-2021:supplier-name", "ntia-2021:version", "ntia-2021:unique-identifiers"):
            finding = next((f for f in result.findings if f.id == fid), None)
            assert finding is not None and finding.status == "pass", (
                f"syft convention not skipped for {fid}: {finding.description if finding else None}"
            )

    def test_spdx_microsoft_sbom_tool_double_dash_naming(self):
        """Microsoft sbom-tool emits SPDXRef-File--<name>-<hash> (double dash)."""
        sbom = self._base_spdx_doc(
            [
                {
                    "SPDXID": "SPDXRef-File--sbom-tool-win-x64.exe-E55F25E239D8D3572D75D5CDC5CA24899FD4993F",
                    "name": "sbom-tool-win-x64.exe",
                    "downloadLocation": "NOASSERTION",
                }
            ]
        )
        result = self._assess(sbom)
        for fid in ("ntia-2021:supplier-name", "ntia-2021:version", "ntia-2021:unique-identifiers"):
            finding = next((f for f in result.findings if f.id == fid), None)
            assert finding is not None and finding.status == "pass", (
                f"Microsoft sbom-tool convention not skipped for {fid}: {finding.description if finding else None}"
            )

    def test_spdx_clean_file_naming(self):
        """Clean convention: SPDXRef-File-<name>."""
        sbom = self._base_spdx_doc(
            [
                {
                    "SPDXID": "SPDXRef-File-manifest.txt",
                    "name": "manifest.txt",
                    "downloadLocation": "NOASSERTION",
                }
            ]
        )
        result = self._assess(sbom)
        for fid in ("ntia-2021:supplier-name", "ntia-2021:version", "ntia-2021:unique-identifiers"):
            finding = next((f for f in result.findings if f.id == fid), None)
            assert finding is not None and finding.status == "pass", (
                f"Clean File- convention not skipped for {fid}: {finding.description if finding else None}"
            )

    def test_spdx_real_packages_containing_file_in_name_not_skipped(self):
        """Real packages with 'File' in their name must NOT be falsely skipped.

        The '-File-' heuristic requires dashes on BOTH sides (making it a
        word-segment marker) AND is case-sensitive. This keeps these real
        packages from being misclassified as file entries:

        - filelock          (pypi, capital F absent: '-filelock-' has no match)
        - FileManager       ('-FileM' has no trailing dash)
        - file-utils        (lowercase 'file', not capital 'File')
        - python-file-utils (same — lowercase)

        Any of these missing supplier/version must still surface in failures.
        """
        sbom = self._base_spdx_doc(
            [
                {
                    "SPDXID": "SPDXRef-Package-filelock-3.12.0",
                    "name": "filelock",
                    "downloadLocation": "NOASSERTION",
                    # Intentionally missing supplier + versionInfo
                },
                {
                    "SPDXID": "SPDXRef-Package-FileManager-abc123",
                    "name": "FileManager",
                    "downloadLocation": "NOASSERTION",
                },
                {
                    "SPDXID": "SPDXRef-Package-python-file-utils-2.0",
                    "name": "python-file-utils",
                    "downloadLocation": "NOASSERTION",
                },
            ]
        )
        result = self._assess(sbom)
        supplier = next((f for f in result.findings if f.id == "ntia-2021:supplier-name"), None)
        version = next((f for f in result.findings if f.id == "ntia-2021:version"), None)

        # All three packages must appear in the supplier + version failure lists
        # because they are real packages, not file entries.
        assert supplier is not None and supplier.status == "fail"
        assert version is not None and version.status == "fail"
        for expected_name in ("filelock", "FileManager", "python-file-utils"):
            assert expected_name in (supplier.description or ""), (
                f"real package '{expected_name}' missing from supplier failures — "
                f"heuristic may be over-skipping: {supplier.description}"
            )
            assert expected_name in (version.description or ""), (
                f"real package '{expected_name}' missing from version failures: {version.description}"
            )

    def test_cyclonedx_works_on_multiple_spec_versions(self):
        """The type=file skip is not tied to a specific CycloneDX spec version.
        Works on 1.4, 1.5, and 1.6 (all versions sbomify-action produces)."""
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        def _sbom(spec_version: str) -> dict:
            return {
                "bomFormat": "CycloneDX",
                "specVersion": spec_version,
                "metadata": {"authors": [{"name": "Dev"}], "timestamp": "2026-01-01T00:00:00Z"},
                "components": [
                    {
                        "name": "django",
                        "version": "5.2.3",
                        "type": "library",
                        "purl": "pkg:pypi/django@5.2.3",
                        "publisher": "Django",
                    },
                    {"name": "uv.lock", "type": "file"},
                ],
                "dependencies": [{"ref": "pkg:pypi/django@5.2.3", "dependsOn": []}],
            }

        for spec_version in ("1.4", "1.5", "1.6"):
            plugin = NTIAMinimumElementsPlugin()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(_sbom(spec_version), f)
                f.flush()
                result = plugin.assess("test", Path(f.name))
            for fid in ("ntia-2021:supplier-name", "ntia-2021:version", "ntia-2021:unique-identifiers"):
                finding = next((f for f in result.findings if f.id == fid), None)
                assert finding is not None and finding.status == "pass", (
                    f"CycloneDX {spec_version}: {fid} should pass but got "
                    f"{finding.status if finding else None}: {finding.description if finding else None}"
                )
