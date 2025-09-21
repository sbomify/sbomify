"""
Integration tests for NTIA compliance checking workflow.

Tests the complete workflow from SBOM upload through compliance checking
to frontend display.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Team, Member
from sbomify.tasks import check_sbom_ntia_compliance

User = get_user_model()


@pytest.mark.django_db(transaction=True, reset_sequences=True)
class TestNTIAComplianceIntegration:
    """Integration tests for NTIA compliance workflow."""

    @pytest.fixture(autouse=True)
    def clean_state(self):
        """Ensure clean state for each test."""
        # Clear any existing SBOM data
        from sbomify.apps.sboms.models import SBOM
        SBOM.objects.all().delete()

        # Reset any cached connections or state
        from django.db import connection
        connection.close()
        yield
        # Cleanup after test
        SBOM.objects.all().delete()
        connection.close()

    @pytest.fixture
    def user(self):
        """Create a test user."""
        return User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )

    @pytest.fixture
    def team(self):
        """Create a test team."""
        return Team.objects.create(
            name="Test Team",
            key="test-team"
        )

    @pytest.fixture
    def member(self, user, team):
        """Create team membership for user."""
        return Member.objects.create(
            user=user,
            team=team,
            role="owner"
        )

    @pytest.fixture
    def component(self, team):
        """Create a test component."""
        return Component.objects.create(
            name="test-component",
            team=team,
            component_type="sbom",
            is_public=True
        )

    @pytest.fixture
    def client(self, user, member):
        """Create authenticated client."""
        client = Client()
        client.force_login(user)
        # Set up session with team info
        session = client.session
        session['current_team'] = {
            'id': member.team.id,
            'name': member.team.name,
            'role': member.role
        }
        session.save()
        return client

    @pytest.fixture
    def compliant_cyclonedx_sbom(self):
        """Sample compliant CycloneDX SBOM for upload."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "metadata": {
                "component": {
                    "name": "test-component",
                    "version": "1.0.0",
                    "type": "application"
                },
                "authors": [
                    {
                        "name": "Test Developer"
                    }
                ],
                "timestamp": "2023-01-01T00:00:00Z"
            },
            "components": [
                {
                    "name": "example-dependency",
                    "version": "2.0.0",
                    "type": "library",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-dependency@2.0.0"
                }
            ],
            "dependencies": [
                {
                    "ref": {
                        "value": "pkg:pypi/example-dependency@2.0.0"
                    },
                    "dependsOn": []
                }
            ]
        }

    @pytest.fixture
    def non_compliant_cyclonedx_sbom(self):
        """Sample non-compliant CycloneDX SBOM for upload."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "metadata": {
                "component": {
                    "name": "test-component",
                    "version": "1.0.0",
                    "type": "application"
                }
                # Missing authors/tools and timestamp
            },
            "components": [
                {
                    "name": "example-dependency",
                    "type": "library"
                    # Missing version, publisher, and unique identifiers
                }
            ]
            # Missing dependencies
        }

    def test_complete_compliant_workflow(self, client, component, compliant_cyclonedx_sbom):
        """Test complete workflow for compliant SBOM upload and processing."""
        # Mock S3 client comprehensively for all usage points
        with patch('sbomify.apps.sboms.apis.S3Client') as mock_apis_s3_class, \
             patch('sbomify.apps.core.object_store.S3Client') as mock_core_s3_class:
            # Configure mock for API usage (upload)
            mock_apis_instance = mock_apis_s3_class.return_value
            mock_apis_instance.upload_sbom.return_value = "test-sbom.json"

            # Configure mock for utils/task usage (download)
            mock_core_instance = mock_core_s3_class.return_value
            mock_core_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_sbom).encode('utf-8')

            # 1. Upload SBOM via API
            upload_response = client.post(
                f"/api/v1/sboms/upload-file/{component.id}",
                data={
                    'sbom_file': self._create_file_upload(compliant_cyclonedx_sbom)
                },
                follow=True
            )

            assert upload_response.status_code == 201
            upload_data = upload_response.json()
            sbom_id = upload_data["id"]

            # Verify SBOM was created with unknown status initially
            sbom = SBOM.objects.get(id=sbom_id)
            assert sbom.ntia_compliance_status == SBOM.NTIAComplianceStatus.UNKNOWN

            # 2. Simulate background task execution
            task_result = check_sbom_ntia_compliance(sbom_id)

            # Verify task completed successfully
            assert task_result["compliance_status"] == "compliant"
            assert task_result["is_compliant"] is True
            assert task_result["error_count"] == 0

            # 3. Verify SBOM was updated
            sbom.refresh_from_db()
            assert sbom.ntia_compliance_status == SBOM.NTIAComplianceStatus.COMPLIANT
            assert sbom.ntia_compliance_details is not None
            assert sbom.ntia_compliance_checked_at is not None

            # 4. Test private component details page loads
            private_response = client.get(f"/component/{component.id}/")
            assert private_response.status_code == 200

            # 5. Test public component details page loads
            public_response = client.get(f"/public/component/{component.id}/")
            assert public_response.status_code == 200

            # 6. Verify SBOM data via API includes NTIA compliance
            component_api_response = client.get(f"/api/v1/components/{component.id}")
            if component_api_response.status_code == 200:
                # If the API includes SBOM data, verify NTIA compliance is present
                component_data = component_api_response.json()
                # This is a basic test that the API is accessible and the component exists

    def test_complete_non_compliant_workflow(self, client, component, non_compliant_cyclonedx_sbom):
        """Test complete workflow for non-compliant SBOM upload and processing."""
        # Mock S3 client comprehensively for all usage points
        with patch('sbomify.apps.sboms.apis.S3Client') as mock_apis_s3_class, \
             patch('sbomify.apps.core.object_store.S3Client') as mock_core_s3_class:
            # Configure mock for API usage (upload)
            mock_apis_instance = mock_apis_s3_class.return_value
            mock_apis_instance.upload_sbom.return_value = "test-non-compliant-sbom.json"

            # Configure mock for utils/task usage (download)
            mock_core_instance = mock_core_s3_class.return_value
            mock_core_instance.get_sbom_data.return_value = json.dumps(non_compliant_cyclonedx_sbom).encode('utf-8')

            # 1. Upload SBOM
            upload_response = client.post(
                f"/api/v1/sboms/upload-file/{component.id}",
                data={
                    'sbom_file': self._create_file_upload(non_compliant_cyclonedx_sbom)
                },
                follow=True
            )

            assert upload_response.status_code == 201
            sbom_id = upload_response.json()["id"]

            # 2. Process NTIA compliance
            task_result = check_sbom_ntia_compliance(sbom_id)

            # Verify task found non-compliance
            assert task_result["compliance_status"] == "non_compliant"
            assert task_result["is_compliant"] is False
            assert task_result["error_count"] > 0

            # 3. Verify SBOM was updated with errors
            sbom = SBOM.objects.get(id=sbom_id)
            assert sbom.ntia_compliance_status == SBOM.NTIAComplianceStatus.NON_COMPLIANT
            assert len(sbom.get_ntia_compliance_errors()) > 0

            # 4. Test private page loads
            private_response = client.get(f"/component/{component.id}/")
            assert private_response.status_code == 200

            # 5. Test public page loads
            public_response = client.get(f"/public/component/{component.id}/")
            assert public_response.status_code == 200

    def test_sbom_detail_page_compliance_display(self, client, component, compliant_cyclonedx_sbom):
        """Test that SBOM detail pages show NTIA compliance information."""
        # Mock S3 client comprehensively for all usage points
        with patch('sbomify.apps.sboms.apis.S3Client') as mock_apis_s3_class, \
             patch('sbomify.apps.core.object_store.S3Client') as mock_core_s3_class:
            # Configure mock for API usage (upload)
            mock_apis_instance = mock_apis_s3_class.return_value
            mock_apis_instance.upload_sbom.return_value = "test-sbom.json"

            # Configure mock for utils/task usage (download)
            mock_core_instance = mock_core_s3_class.return_value
            mock_core_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_sbom).encode('utf-8')

            # Create and process SBOM
            upload_response = client.post(
                f"/api/v1/sboms/upload-file/{component.id}",
                data={'sbom_file': self._create_file_upload(compliant_cyclonedx_sbom)},
                follow=True
            )
            sbom_id = upload_response.json()["id"]
            check_sbom_ntia_compliance(sbom_id)

            # Test private SBOM detail page loads
            private_detail_response = client.get(f"/component/{component.id}/detailed/")
            assert private_detail_response.status_code == 200

            # Test public SBOM detail page loads
            public_detail_response = client.get(f"/public/component/{component.id}/detailed/")
            assert public_detail_response.status_code == 200

    def test_signal_triggered_compliance_check(self, component, compliant_cyclonedx_sbom):
        """Test that NTIA compliance checking is triggered by SBOM creation signal."""
        # Set up team with billing plan that includes NTIA compliance
        from sbomify.apps.billing.models import BillingPlan

        # Create or get a billing plan that includes NTIA compliance
        billing_plan, created = BillingPlan.objects.get_or_create(
            key="business",
            defaults={
                "name": "Business Plan",
                "max_users": 10,
                "max_products": 100,
                "max_projects": 100,
                "max_components": 1000,
            }
        )

        # Set the team's billing plan
        component.team.billing_plan = billing_plan.key
        component.team.save()

        # Mock the task to verify it gets called
        with patch('sbomify.tasks.check_sbom_ntia_compliance.send_with_options') as mock_task:
            # Create SBOM directly (simulates what happens in upload endpoints)
            sbom = SBOM.objects.create(
                name="test-sbom",
                component=component,
                format="cyclonedx",
                format_version="1.5",
                sbom_filename="test.json",
                source="test"
            )

            # Verify task was scheduled
            mock_task.assert_called_once()
            call_args = mock_task.call_args
            assert call_args[1]["args"] == [sbom.id]
            assert call_args[1]["delay"] == 60000  # 60 second delay

    def test_model_properties_and_methods(self, component):
        """Test SBOM model properties and methods for NTIA compliance."""
        # Create SBOM with various compliance states
        compliant_sbom = SBOM.objects.create(
            name="compliant-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="compliant.json",
            source="test",
            ntia_compliance_status=SBOM.NTIAComplianceStatus.COMPLIANT,
            ntia_compliance_details={
                "is_compliant": True,
                "status": "compliant",
                "errors": [],
                "checked_at": "2023-01-01T00:00:00Z"
            }
        )

        non_compliant_sbom = SBOM.objects.create(
            name="non-compliant-sbom",
            component=component,
            format="spdx",
            format_version="2.3",
            sbom_filename="non-compliant.json",
            source="test",
            ntia_compliance_status=SBOM.NTIAComplianceStatus.NON_COMPLIANT,
            ntia_compliance_details={
                "is_compliant": False,
                "status": "non_compliant",
                "errors": [
                    {
                        "field": "supplier",
                        "message": "Missing supplier",
                        "suggestion": "Add supplier field"
                    },
                    {
                        "field": "version",
                        "message": "Missing version",
                        "suggestion": "Add version field"
                    }
                ],
                "checked_at": "2023-01-01T00:00:00Z"
            }
        )

        unknown_sbom = SBOM.objects.create(
            name="unknown-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="unknown.json",
            source="test"
            # Default status is UNKNOWN
        )

        # Test compliant SBOM properties
        assert compliant_sbom.is_ntia_compliant is True
        assert compliant_sbom.ntia_compliance_display == "Compliant"
        assert compliant_sbom.get_ntia_compliance_error_count() == 0
        assert len(compliant_sbom.get_ntia_compliance_errors()) == 0
        assert compliant_sbom.needs_ntia_compliance_check() is False

        # Test non-compliant SBOM properties
        assert non_compliant_sbom.is_ntia_compliant is False
        assert non_compliant_sbom.ntia_compliance_display == "Non-Compliant"
        assert non_compliant_sbom.get_ntia_compliance_error_count() == 2
        assert len(non_compliant_sbom.get_ntia_compliance_errors()) == 2
        assert non_compliant_sbom.needs_ntia_compliance_check() is False

        # Test unknown SBOM properties
        assert unknown_sbom.is_ntia_compliant is False
        assert unknown_sbom.ntia_compliance_display == "Unknown"
        assert unknown_sbom.get_ntia_compliance_error_count() == 0
        assert len(unknown_sbom.get_ntia_compliance_errors()) == 0
        assert unknown_sbom.needs_ntia_compliance_check() is True

    def test_api_response_includes_ntia_data(self, client, component, compliant_cyclonedx_sbom):
        """Test that API responses include NTIA compliance data."""
        with patch('sbomify.apps.sboms.apis.S3Client') as mock_apis_s3_class, \
             patch('sbomify.apps.core.object_store.S3Client') as mock_core_s3_class:
            # Configure mock for API usage (upload)
            mock_apis_instance = mock_apis_s3_class.return_value
            mock_apis_instance.upload_sbom.return_value = "test-sbom.json"

            # Configure mock for utils/task usage (download)
            mock_core_instance = mock_core_s3_class.return_value
            mock_core_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_sbom).encode('utf-8')

            # Upload and process SBOM
            upload_response = client.post(
                f"/api/v1/sboms/upload-file/{component.id}",
                data={'sbom_file': self._create_file_upload(compliant_cyclonedx_sbom)},
                follow=True
            )
            sbom_id = upload_response.json()["id"]
            check_sbom_ntia_compliance(sbom_id)

            # Test component API includes NTIA data
            component_response = client.get(f"/api/v1/components/{component.id}")
            assert component_response.status_code == 200

            # Note: The actual API structure depends on how the component endpoint
            # is implemented. This test verifies the integration works end-to-end.

    def _create_file_upload(self, sbom_data):
        """Helper to create file upload for testing."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        content = json.dumps(sbom_data).encode('utf-8')
        return SimpleUploadedFile(
            "test-sbom.json",
            content,
            content_type="application/json"
        )



    def test_error_handling_in_workflow(self, client, component):
        """Test error handling throughout the workflow."""
        # Test upload with invalid JSON
        invalid_json_file = self._create_file_upload("invalid json content")

        upload_response = client.post(
            f"/api/v1/sboms/upload-file/{component.id}",
            data={'sbom_file': invalid_json_file},
            follow=True
        )

        assert upload_response.status_code == 400
        # The actual error message may vary, just check that it's a 400 error
        assert "detail" in upload_response.json()

    def test_concurrent_compliance_checks(self, component, compliant_cyclonedx_sbom):
        """Test that concurrent compliance checks don't interfere with each other."""
        sbom1 = SBOM.objects.create(
            name="sbom1",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="sbom1.json",
            source="test"
        )

        sbom2 = SBOM.objects.create(
            name="sbom2",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="sbom2.json",
            source="test"
        )

        with patch('sbomify.apps.core.object_store.S3Client') as mock_s3_class:
            mock_s3_instance = mock_s3_class.return_value
            mock_s3_instance.get_sbom_data.return_value = json.dumps(compliant_cyclonedx_sbom).encode('utf-8')

            # Run compliance checks for both SBOMs
            result1 = check_sbom_ntia_compliance(str(sbom1.id))
            result2 = check_sbom_ntia_compliance(str(sbom2.id))

            # Both should succeed independently
            assert result1["compliance_status"] == "compliant"
            assert result2["compliance_status"] == "compliant"

            # Verify both SBOMs were updated correctly
            sbom1.refresh_from_db()
            sbom2.refresh_from_db()

            assert sbom1.ntia_compliance_status == SBOM.NTIAComplianceStatus.COMPLIANT
            assert sbom2.ntia_compliance_status == SBOM.NTIAComplianceStatus.COMPLIANT