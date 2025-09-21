"""
Example tests demonstrating usage of the new S3 fixtures.

This file serves as documentation and verification that the S3 fixtures work correctly.
"""

import json

import pytest
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.s3_fixtures import (
    MockS3Client,
    create_documents_api_mock,
    create_s3_method_mock,
)


class TestS3FixturesUsage:
    """Example tests showing different ways to use S3 fixtures."""

    def test_basic_s3_mock_usage(self, s3_mock: MockS3Client) -> None:
        """Example: Basic usage of the s3_mock fixture."""
        # The S3Client is already mocked at the class level
        from sbomify.apps.core.object_store import S3Client

        client = S3Client("SBOMS")

        # Upload some data
        filename = client.upload_sbom(b'{"bomFormat": "CycloneDX"}')

        # Verify it was stored in our mock
        assert filename in s3_mock.uploaded_files
        assert s3_mock.uploaded_files[filename] == b'{"bomFormat": "CycloneDX"}'

        # Retrieve the data
        retrieved = client.get_sbom_data(filename)
        assert retrieved == b'{"bomFormat": "CycloneDX"}'

    def test_documents_specific_mock(self, s3_documents_mock: MockS3Client) -> None:
        """Example: Using the documents-specific mock with pre-populated data."""
        from sbomify.apps.core.object_store import S3Client

        client = S3Client("DOCUMENTS")

        # The mock comes pre-populated with test documents
        assert client.get_document_data("test_document.pdf") == b"test document content"
        assert client.get_document_data("public_doc.pdf") == b"public document content"

        # Upload a new document
        filename = client.upload_document(b"new document content")
        assert client.get_document_data(filename) == b"new document content"

    def test_sboms_specific_mock(self, s3_sboms_mock: MockS3Client) -> None:
        """Example: Using the SBOM-specific mock with pre-populated data."""
        from sbomify.apps.core.object_store import S3Client

        client = S3Client("SBOMS")

        # The mock comes pre-populated with test SBOMs
        sbom_data = client.get_sbom_data("test_sbom.json")
        assert sbom_data is not None

        parsed = json.loads(sbom_data.decode())
        assert parsed["bomFormat"] == "CycloneDX"
        assert parsed["specVersion"] == "1.6"

        # Also has legacy data
        legacy_data = client.get_sbom_data("legacy_sbom.json")
        legacy_parsed = json.loads(legacy_data.decode())
        assert legacy_parsed["specVersion"] == "1.5"

    def test_error_scenarios(self, s3_error_mock: MockS3Client) -> None:
        """Example: Testing error scenarios."""
        from sbomify.apps.core.object_store import S3Client

        client = S3Client("SBOMS")

        # All operations should raise exceptions
        with pytest.raises(Exception, match="S3 service unavailable"):
            client.upload_sbom(b'{"test": "data"}')

        with pytest.raises(Exception, match="S3 service unavailable"):
            client.get_sbom_data("test.json")

    def test_configurable_mock_behavior(self, s3_mock: MockS3Client) -> None:
        """Example: Configuring mock behavior during test."""
        from sbomify.apps.core.object_store import S3Client

        client = S3Client("SBOMS")

        # Initially works fine
        filename = client.upload_sbom(b'{"test": "data"}')
        assert client.get_sbom_data(filename) == b'{"test": "data"}'

        # Configure it to fail
        s3_mock.configure_error(should_raise=True, message="Custom error message")

        with pytest.raises(Exception, match="Custom error message"):
            client.get_sbom_data(filename)

        # Re-enable success
        s3_mock.configure_error(should_raise=False)
        assert client.get_sbom_data(filename) == b'{"test": "data"}'

    def test_method_specific_mocking(self, mocker: MockerFixture) -> None:
        """Example: Mocking only specific S3Client methods."""
        # Mock only the get_sbom_data method
        mock_get = create_s3_method_mock(mocker, "get_sbom_data", return_value=b'{"mocked": "data"}')

        from sbomify.apps.core.object_store import S3Client

        client = S3Client("SBOMS")

        result = client.get_sbom_data("any_filename")
        assert result == b'{"mocked": "data"}'
        mock_get.assert_called_once_with("any_filename")

    def test_method_error_mocking(self, mocker: MockerFixture) -> None:
        """Example: Mocking method to raise specific errors."""
        mock_upload = create_s3_method_mock(mocker, "upload_sbom", side_effect=Exception("Upload failed"))

        from sbomify.apps.core.object_store import S3Client

        client = S3Client("SBOMS")

        with pytest.raises(Exception, match="Upload failed"):
            client.upload_sbom(b'{"test": "data"}')

        mock_upload.assert_called_once_with(b'{"test": "data"}')

    def test_documents_api_mock_success(self, mocker: MockerFixture) -> None:
        """Example: Using the documents API mock helper for success scenario."""
        mock_instance = create_documents_api_mock(mocker, scenario="success")

        # This would be used in actual API tests
        assert mock_instance.upload_document.return_value == "mocked_filename.pdf"
        assert mock_instance.get_document_data.return_value == b"test document content"

    def test_documents_api_mock_error(self, mocker: MockerFixture) -> None:
        """Example: Using the documents API mock helper for error scenario."""
        mock_instance = create_documents_api_mock(mocker, scenario="upload_error")

        # The mock is configured to raise an exception on upload
        mock_instance.upload_document.assert_not_called()  # Not called yet
        # In real tests, this would be called by the API endpoint being tested


class TestMockS3ClientDirectly:
    """Test the MockS3Client class directly to ensure it works correctly."""

    def test_mock_client_bucket_validation(self) -> None:
        """Test that MockS3Client validates bucket types correctly."""
        sbom_client = MockS3Client("SBOMS")
        doc_client = MockS3Client("DOCUMENTS")

        # SBOM client can't do document operations
        with pytest.raises(ValueError, match="only for DOCUMENTS bucket"):
            sbom_client.upload_document(b"test")

        # Document client can't do SBOM operations
        with pytest.raises(ValueError, match="only for SBOMS bucket"):
            doc_client.upload_sbom(b"test")

    def test_mock_client_file_storage(self) -> None:
        """Test that MockS3Client properly stores and retrieves files."""
        client = MockS3Client("SBOMS")

        # Upload and retrieve
        filename = client.upload_sbom(b'{"test": "data"}')
        retrieved = client.get_sbom_data(filename)
        assert retrieved == b'{"test": "data"}'

        # File is stored in the mock's internal storage
        assert filename in client.uploaded_files
        assert client.uploaded_files[filename] == b'{"test": "data"}'

    def test_mock_client_deletion(self) -> None:
        """Test that MockS3Client handles file deletion."""
        client = MockS3Client("SBOMS")

        # Upload a file
        filename = client.upload_sbom(b'{"test": "data"}')
        assert filename in client.uploaded_files

        # Delete it
        client.delete_object("bucket", filename)
        assert filename not in client.uploaded_files

        # Retrieving deleted file returns None
        assert client.get_sbom_data(filename) is None

    def test_mock_client_error_configuration(self) -> None:
        """Test MockS3Client error configuration."""
        client = MockS3Client("SBOMS")

        # Configure to raise errors
        client.configure_error(True, "Test error")

        with pytest.raises(Exception, match="Test error"):
            client.upload_sbom(b"test")

        with pytest.raises(Exception, match="Test error"):
            client.get_sbom_data("test.json")

        with pytest.raises(Exception, match="Test error"):
            client.delete_object("bucket", "test.json")
