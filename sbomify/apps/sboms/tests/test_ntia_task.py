"""
Unit tests for NTIA compliance checking task.

Tests the background task that checks SBOM NTIA compliance.
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from django.test import TestCase
from django.utils import timezone as django_timezone

from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.ntia_validator import (
    NTIAComplianceStatus,
    NTIACheckResult,
    NTIACheckStatus,
    NTIASection,
    NTIASectionResult,
    NTIAValidationResult,
)
from sbomify.apps.sboms.utils import build_ntia_template_context, calculate_ntia_compliance_summary
from sbomify.apps.teams.models import Team
from sbomify.apps.sboms.tasks import check_sbom_ntia_compliance


@pytest.mark.django_db
class TestNTIAComplianceTask:
    """Test cases for NTIA compliance checking task."""

    @pytest.fixture
    def team(self):
        """Create a test team."""
        return Team.objects.create(
            name="Test Team",
            key="test-team"
        )

    @pytest.fixture
    def component(self, team):
        """Create a test component."""
        return Component.objects.create(
            name="test-component",
            team=team,
            component_type="sbom"
        )

    @pytest.fixture
    def sbom(self, component):
        """Create a test SBOM."""
        return SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="test-sbom.json",
            source="test"
        )

    @pytest.fixture
    def compliant_cyclonedx_data(self):
        """Sample compliant CycloneDX SBOM data."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0"
                }
            ],
            "dependencies": [
                {
                    "ref": "pkg:pypi/example-component@1.0.0",
                    "dependsOn": []
                }
            ],
            "metadata": {
                "authors": [
                    {
                        "name": "Example Developer"
                    }
                ],
                "timestamp": "2023-01-01T00:00:00Z"
            }
        }

    @pytest.fixture
    def non_compliant_cyclonedx_data(self):
        """Sample non-compliant CycloneDX SBOM data."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    # Missing version, publisher, and unique identifiers
                }
            ],
            # Missing dependencies
            "metadata": {
                # Missing authors/tools and timestamp
            }
        }

    def test_successful_compliant_check(self, sbom, compliant_cyclonedx_data):
        """Test successful NTIA compliance check for compliant SBOM."""
        # Mock S3 client
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            result = check_sbom_ntia_compliance(str(sbom.id))

            # Verify result
            assert result["status"] == "NTIA compliance check completed"
            assert result["compliance_status"] == "compliant"
            assert result["is_compliant"] is True
            assert result["error_count"] == 0

            # Verify SBOM was updated
            sbom.refresh_from_db()
            assert sbom.ntia_compliance_status == SBOM.NTIAComplianceStatus.COMPLIANT
            assert sbom.ntia_compliance_details is not None
            assert sbom.ntia_compliance_checked_at is not None
            assert isinstance(sbom.ntia_compliance_checked_at, datetime)

    def test_successful_non_compliant_check(self, sbom, non_compliant_cyclonedx_data):
        """Test successful NTIA compliance check for non-compliant SBOM."""
        # Mock S3 client
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(non_compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            result = check_sbom_ntia_compliance(str(sbom.id))

            # Verify result
            assert result["status"] == "NTIA compliance check completed"
            assert result["compliance_status"] == "non_compliant"
            assert result["is_compliant"] is False
            assert result["error_count"] > 0

            # Verify SBOM was updated
            sbom.refresh_from_db()
            assert sbom.ntia_compliance_status == SBOM.NTIAComplianceStatus.NON_COMPLIANT
            assert sbom.ntia_compliance_details is not None
            assert "errors" in sbom.ntia_compliance_details
            assert len(sbom.ntia_compliance_details["errors"]) > 0
            assert sbom.ntia_compliance_checked_at is not None

    def test_partial_compliance_persists_warning_details(self, sbom):
        """Partial NTIA compliance should persist warnings and summary details."""
        partial_result = NTIAValidationResult(
            is_compliant=False,
            status=NTIAComplianceStatus.PARTIAL,
            errors=[],
            sections=[
                NTIASectionResult(
                    name=NTIASection.DATA_FIELDS,
                    title="Data Fields",
                    summary="Some supplier metadata is advisory.",
                    checks=[
                        NTIACheckResult(
                            element="supplier_name",
                            title="Supplier Name",
                            status=NTIACheckStatus.WARNING,
                            message="One component is missing supplier information.",
                            suggestion="Update the SBOM with supplier details.",
                            affected=["Component A"],
                        ),
                        NTIACheckResult(
                            element="component_name",
                            title="Component Name",
                            status=NTIACheckStatus.PASS,
                            message="All components include names.",
                        ),
                    ],
                ),
            ],
        )

        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class, patch(
            'sbomify.apps.sboms.tasks.validate_sbom_ntia_compliance', return_value=partial_result
        ) as mock_validator:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps({"bomFormat": "CycloneDX"}).encode('utf-8')

            result = check_sbom_ntia_compliance(str(sbom.id))

        mock_validator.assert_called_once()
        sbom.refresh_from_db()

        assert result["compliance_status"] == "partial"
        assert result["warning_count"] == 1
        assert sbom.ntia_compliance_status == SBOM.NTIAComplianceStatus.PARTIAL
        assert sbom.ntia_compliance_details["status"] == "partial"
        assert sbom.ntia_compliance_details["warning_count"] == 1
        assert sbom.ntia_compliance_details["warnings"][0]["status"] == "warning"
        assert sbom.ntia_compliance_details["sections"][0]["status"] == "warning"

    def test_sbom_not_found(self):
        """Test task behavior when SBOM doesn't exist."""
        non_existent_id = "non-existent-id"

        result = check_sbom_ntia_compliance(non_existent_id)

        assert "error" in result
        assert f"SBOM with ID {non_existent_id} not found" in result["error"]

    def test_sbom_without_filename(self, sbom):
        """Test task behavior when SBOM has no filename."""
        sbom.sbom_filename = ""
        sbom.save()

        result = check_sbom_ntia_compliance(str(sbom.id))

        assert "error" in result
        assert f"SBOM ID: {sbom.id} has no sbom_filename" in result["error"]

    def test_s3_download_failure(self, sbom):
        """Test task behavior when S3 download fails."""
        # Mock S3 client to return empty data
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = None

            result = check_sbom_ntia_compliance(str(sbom.id))

            assert "error" in result
            assert "Failed to download SBOM" in result["error"]

    def test_invalid_json_data(self, sbom):
        """Test task behavior when SBOM contains invalid JSON."""
        # Mock S3 client to return invalid JSON
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = b"invalid json data"

            result = check_sbom_ntia_compliance(str(sbom.id))

            assert "error" in result
            assert "not valid JSON" in result["error"]

    def test_unicode_decode_error(self, sbom):
        """Test task behavior when SBOM contains non-UTF8 data."""
        # Mock S3 client to return non-UTF8 data
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = b'\x80\x81\x82'  # Invalid UTF-8

            result = check_sbom_ntia_compliance(str(sbom.id))

            assert "error" in result
            assert "encoding issues" in result["error"]

    def test_spdx_format_validation(self, component):
        """Test NTIA compliance check for SPDX format."""
        sbom = SBOM.objects.create(
            name="spdx-test-sbom",
            component=component,
            format="spdx",
            format_version="2.3",
            sbom_filename="test-spdx.json",
            source="test"
        )

        spdx_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0"
                        }
                    ]
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package"
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z"
            }
        }

        # Mock S3 client
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(spdx_data).encode('utf-8')

            # Run the task
            result = check_sbom_ntia_compliance(str(sbom.id))

            # Verify result
            assert result["compliance_status"] == "compliant"
            assert result["is_compliant"] is True

            # Verify SBOM was updated
            sbom.refresh_from_db()
            assert sbom.ntia_compliance_status == SBOM.NTIAComplianceStatus.COMPLIANT

    @pytest.fixture
    def partial_spdx_data(self):
        """SPDX data that should trigger NTIA warnings but no failures."""
        return {
            "spdxVersion": "SPDX-2.3",
            "name": "Example SPDX SBOM",
            "SPDXID": "SPDXRef-DOCUMENT",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/spdx/doc/123",
            "creationInfo": {
                "creators": [
                    "Organization: Example Corp",
                    "Tool: spdx-generator 1.2.3 <builder@example.com>",
                ],
                "created": "2024-05-01T12:00:00Z",
                "comment": "Generated during build pipeline",
            },
            "documentDescribes": ["SPDXRef-PackageA", "SPDXRef-PackageB"],
            "externalDocumentRefs": [
                {"externalDocumentId": "DocumentRef-external", "uri": "https://example.com/external/spdx"}
            ],
            "packages": [
                {
                    "SPDXID": "SPDXRef-PackageA",
                    "name": "example-lib",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "downloadLocation": "https://example.com/example-lib-1.0.0.tar.gz",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-lib@1.0.0",
                        }
                    ],
                    "checksums": [
                        {"algorithm": "SHA256", "checksumValue": "1234abcd"}
                    ],
                },
                {
                    "SPDXID": "SPDXRef-PackageB",
                    "name": "utility-tool",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "2.0.0",
                    "downloadLocation": "NOASSERTION",
                    "externalRefs": [
                        {"referenceCategory": "OTHER", "referenceType": "OTHER", "referenceLocator": "internal-id-123"}
                    ],
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-PackageA",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-PackageB",
                }
            ],
        }

    def test_spdx_partial_compliance(self, component, partial_spdx_data):
        """Ensure SPDX SBOM with advisory gaps results in partial compliance."""
        sbom = SBOM.objects.create(
            name="spdx-partial-sbom",
            component=component,
            format="spdx",
            format_version="2.3",
            sbom_filename="partial-spdx.json",
            source="test",
        )

        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(partial_spdx_data).encode('utf-8')

            result = check_sbom_ntia_compliance(str(sbom.id))

        sbom.refresh_from_db()
        assert result["compliance_status"] == "partial"
        assert result["warning_count"] >= 1
        assert sbom.ntia_compliance_status == SBOM.NTIAComplianceStatus.PARTIAL

        details = sbom.ntia_compliance_details
        assert details["status"] == "partial"
        assert details["summary"]["warnings"] == result["warning_count"]
        assert len(details["warnings"]) >= 1
        assert any(section["name"] == "data_fields" for section in details["sections"])

    def test_build_ntia_template_context_empty(self):
        context = build_ntia_template_context({})
        assert context["has_data"] is False
        assert context["status"] == "unknown"

    def test_build_ntia_template_context_populates_sections(self):
        details = {
            "status": "partial",
            "summary": {"errors": 1, "warnings": 2, "status": "partial"},
            "checked_at": "2024-06-01T12:00:00Z",
            "sections": [
                {
                    "name": "data_fields",
                    "title": "Data Fields",
                    "status": "fail",
                    "summary": "Some required data is missing",
                    "checks": [
                        {
                            "title": "Supplier name recorded",
                            "status": "fail",
                            "message": "Supplier information missing",
                            "suggestion": "Add supplier metadata",
                            "affected": ["Component A"],
                        },
                        {
                            "title": "Component version recorded",
                            "status": "warning",
                            "message": "Version uses placeholder",
                            "suggestion": "Replace NOASSERTION with actual version",
                        },
                    ],
                }
            ],
        }

        context = build_ntia_template_context(details)
        assert context["has_data"] is True
        assert context["status"] == "partial"
        assert len(context["sections"]) == 1
        assert len(context["issues"]["failures"]) == 1
        assert len(context["issues"]["warnings"]) == 1

    def test_calculate_ntia_summary_from_models(self, component):
        sbom1 = SBOM.objects.create(
            name="sbom-1",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="sbom1.json",
            ntia_compliance_status=SBOM.NTIAComplianceStatus.COMPLIANT,
            ntia_compliance_details={"summary": {"errors": 0, "warnings": 0}},
        )
        sbom2 = SBOM.objects.create(
            name="sbom-2",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="sbom2.json",
            ntia_compliance_status=SBOM.NTIAComplianceStatus.PARTIAL,
            ntia_compliance_details={"summary": {"errors": 0, "warnings": 2}},
        )
        result = calculate_ntia_compliance_summary(SBOM.objects.filter(id__in=[sbom1.id, sbom2.id]))
        assert result["total"] == 2
        assert result["counts"]["compliant"] == 1
        assert result["counts"]["partial"] == 1
        assert result["status"] == "partial"
        assert result["warnings"] == 2
        assert result["errors"] == 0

    def test_calculate_ntia_summary_from_dict_payload(self):
        payload = [
            {"ntia_compliance_status": "compliant", "ntia_compliance_details": {"summary": {"errors": 0, "warnings": 0}}},
            {"ntia_compliance_status": "non_compliant", "ntia_compliance_details": {"summary": {"errors": 3, "warnings": 1}}},
        ]
        result = calculate_ntia_compliance_summary(payload)
        assert result["total"] == 2
        assert result["counts"]["non_compliant"] == 1
        assert result["status"] == "non_compliant"
        assert result["errors"] == 3
        assert result["warnings"] == 1

    @patch('sbomify.apps.sboms.tasks.logger')
    @patch('sbomify.apps.sboms.utils.log')
    def test_logging_behavior(self, mock_utils_logger, mock_task_logger, sbom, compliant_cyclonedx_data):
        """Test that appropriate logging occurs during task execution."""
        # Mock S3 client
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            check_sbom_ntia_compliance(str(sbom.id))

            # Verify logging calls from the task
            mock_task_logger.info.assert_any_call(
                f"[TASK_check_sbom_ntia_compliance] Starting NTIA compliance check for SBOM ID: {sbom.id}"
            )
            # Verify logging calls from the shared utility
            mock_utils_logger.debug.assert_any_call(
                f"SBOM {sbom.sbom_filename} successfully fetched and parsed as JSON"
            )
            mock_task_logger.info.assert_any_call(
                f"[TASK_check_sbom_ntia_compliance] NTIA compliance check completed for SBOM ID: {sbom.id}. "
                f"Status: compliant, Errors: 0"
            )

    def test_database_transaction_rollback(self, sbom, compliant_cyclonedx_data):
        """Test that database transaction is rolled back on error."""
        # Mock S3 client
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_data).encode('utf-8')

            # Mock the validation to raise an exception during save
            original_status = sbom.ntia_compliance_status

            with patch.object(SBOM, 'save', side_effect=Exception("Database error")):
                # This should raise the exception and not catch it
                with pytest.raises(Exception, match="Database error"):
                    check_sbom_ntia_compliance(str(sbom.id))

            # Verify SBOM was not updated due to rollback
            sbom.refresh_from_db()
            assert sbom.ntia_compliance_status == original_status

    @patch('sbomify.task_utils.connection')
    def test_database_connection_check(self, mock_connection, sbom, compliant_cyclonedx_data):
        """Test that database connection is ensured during task execution."""
        # Mock S3 client
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            check_sbom_ntia_compliance(str(sbom.id))

            # Verify database connection was ensured
            mock_connection.ensure_connection.assert_called_once()

    def test_validation_result_serialization(self, sbom, non_compliant_cyclonedx_data):
        """Test that validation results are properly serialized to JSON."""
        # Mock S3 client
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(non_compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            check_sbom_ntia_compliance(str(sbom.id))

            # Verify SBOM details can be JSON serialized/deserialized
            sbom.refresh_from_db()
            details = sbom.ntia_compliance_details

            # Should be able to serialize back to JSON
            json_str = json.dumps(details)
            reloaded = json.loads(json_str)

            assert "errors" in reloaded
            assert "warnings" in reloaded
            assert "sections" in reloaded
            assert "summary" in reloaded
            assert "error_count" in reloaded
            assert "warning_count" in reloaded
            assert "checked_at" in reloaded
            assert "status" in reloaded
            assert isinstance(reloaded["errors"], list)
            assert isinstance(reloaded["warnings"], list)

    def test_task_return_values(self, sbom, compliant_cyclonedx_data):
        """Test that task returns expected values for monitoring/debugging."""
        # Mock S3 client
        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            result = check_sbom_ntia_compliance(str(sbom.id))

            # Verify return structure
            required_keys = [
                "sbom_id",
                "status",
                "compliance_status",
                "is_compliant",
                "error_count",
                "warning_count",
                "message",
            ]
            for key in required_keys:
                assert key in result

            assert result["sbom_id"] == str(sbom.id)
            assert isinstance(result["is_compliant"], bool)
            assert isinstance(result["error_count"], int)
            assert isinstance(result["status"], str)
            assert isinstance(result["message"], str)
