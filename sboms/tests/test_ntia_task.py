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

from sboms.models import SBOM, Component
from teams.models import Team
from sbomify.tasks import check_sbom_ntia_compliance


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
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
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
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
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
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = None

            result = check_sbom_ntia_compliance(str(sbom.id))

            assert "error" in result
            assert "Failed to download SBOM" in result["error"]

    def test_invalid_json_data(self, sbom):
        """Test task behavior when SBOM contains invalid JSON."""
        # Mock S3 client to return invalid JSON
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = b"invalid json data"

            result = check_sbom_ntia_compliance(str(sbom.id))

            assert "error" in result
            assert "not valid JSON" in result["error"]

    def test_unicode_decode_error(self, sbom):
        """Test task behavior when SBOM contains non-UTF8 data."""
        # Mock S3 client to return non-UTF8 data
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
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
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
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

    @patch('sbomify.tasks.logger')
    def test_logging_behavior(self, mock_logger, sbom, compliant_cyclonedx_data):
        """Test that appropriate logging occurs during task execution."""
        # Mock S3 client
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            check_sbom_ntia_compliance(str(sbom.id))

            # Verify logging calls
            mock_logger.info.assert_any_call(
                f"[TASK_check_sbom_ntia_compliance] Starting NTIA compliance check for SBOM ID: {sbom.id}"
            )
            mock_logger.debug.assert_any_call(
                f"[TASK_check_sbom_ntia_compliance] SBOM {sbom.sbom_filename} successfully parsed as JSON."
            )
            mock_logger.info.assert_any_call(
                f"[TASK_check_sbom_ntia_compliance] NTIA compliance check completed for SBOM ID: {sbom.id}. "
                f"Status: compliant, Errors: 0"
            )

    def test_database_transaction_rollback(self, sbom, compliant_cyclonedx_data):
        """Test that database transaction is rolled back on error."""
        # Mock S3 client
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
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

    @patch('sbomify.tasks.connection')
    def test_database_connection_check(self, mock_connection, sbom, compliant_cyclonedx_data):
        """Test that database connection is ensured during task execution."""
        # Mock S3 client
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            check_sbom_ntia_compliance(str(sbom.id))

            # Verify database connection was ensured
            mock_connection.ensure_connection.assert_called_once()

    def test_validation_result_serialization(self, sbom, non_compliant_cyclonedx_data):
        """Test that validation results are properly serialized to JSON."""
        # Mock S3 client
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
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
            assert "checked_at" in reloaded
            assert "status" in reloaded
            assert isinstance(reloaded["errors"], list)

    def test_task_return_values(self, sbom, compliant_cyclonedx_data):
        """Test that task returns expected values for monitoring/debugging."""
        # Mock S3 client
        with patch('sbomify.tasks.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_data).encode('utf-8')

            # Run the task
            result = check_sbom_ntia_compliance(str(sbom.id))

            # Verify return structure
            required_keys = ["sbom_id", "status", "compliance_status", "is_compliant", "error_count", "message"]
            for key in required_keys:
                assert key in result

            assert result["sbom_id"] == str(sbom.id)
            assert isinstance(result["is_compliant"], bool)
            assert isinstance(result["error_count"], int)
            assert isinstance(result["status"], str)
            assert isinstance(result["message"], str)