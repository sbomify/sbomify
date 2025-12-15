"""
Shared S3 mocking utilities for tests.

This module provides consistent, reusable fixtures for mocking S3 operations
across all test files in the project.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Generator
from unittest.mock import MagicMock, Mock

import pytest
from pytest_mock import MockerFixture


class MockS3Client:
    """A mock S3Client that mimics the real S3Client interface with type safety."""

    def __init__(self, bucket_type: str = "SBOMS") -> None:
        self.bucket_type = bucket_type
        self.uploaded_files: dict[str, bytes] = {}
        self.should_raise_error = False
        self.error_message = "S3 operation failed"

    def upload_data_as_file(self, bucket_name: str, object_name: str, data: bytes) -> None:
        """Mock upload_data_as_file method."""
        if self.should_raise_error:
            raise Exception(self.error_message)
        self.uploaded_files[object_name] = data

    def upload_media(self, object_name: str, data: bytes) -> None:
        """Mock upload_media method."""
        if self.bucket_type != "MEDIA":
            raise ValueError("This method is only for MEDIA bucket")
        self.upload_data_as_file("media-bucket", object_name, data)

    def upload_sbom(self, data: bytes) -> str:
        """Mock upload_sbom method."""
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")
        filename = f"mock_sbom_{len(self.uploaded_files)}.json"
        self.upload_data_as_file("sboms-bucket", filename, data)
        return filename

    def upload_document(self, data: bytes) -> str:
        """Mock upload_document method."""
        if self.bucket_type != "DOCUMENTS":
            raise ValueError("This method is only for DOCUMENTS bucket")
        filename = f"mock_document_{len(self.uploaded_files)}.bin"
        self.upload_data_as_file("documents-bucket", filename, data)
        return filename

    def get_sbom_data(self, object_name: str) -> bytes | None:
        """Mock get_sbom_data method."""
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")
        if self.should_raise_error:
            raise Exception(self.error_message)
        return self.uploaded_files.get(object_name)

    def get_document_data(self, object_name: str) -> bytes | None:
        """Mock get_document_data method."""
        if self.bucket_type != "DOCUMENTS":
            raise ValueError("This method is only for DOCUMENTS bucket")
        if self.should_raise_error:
            raise Exception(self.error_message)
        return self.uploaded_files.get(object_name)

    def get_file_data(self, bucket_name: str, file_path: str) -> bytes | None:
        """Mock get_file_data method."""
        if self.should_raise_error:
            raise Exception(self.error_message)
        return self.uploaded_files.get(file_path)

    def delete_object(self, bucket_name: str, object_name: str) -> None:
        """Mock delete_object method."""
        if self.should_raise_error:
            raise Exception(self.error_message)
        self.uploaded_files.pop(object_name, None)

    def configure_error(self, should_raise: bool = True, message: str = "S3 operation failed") -> None:
        """Configure the mock to raise errors."""
        self.should_raise_error = should_raise
        self.error_message = message


@pytest.fixture
def mock_s3_client() -> Generator[MockS3Client, None, None]:
    """Provide a mock S3Client instance for testing."""
    yield MockS3Client()


@pytest.fixture
def s3_mock(mocker: MockerFixture) -> Generator[MockS3Client, None, None]:
    """
    Mock the core.object_store.S3Client class completely.

    This fixture replaces the S3Client class with our MockS3Client
    and returns the mock instance for test configuration.
    """
    mock_client = MockS3Client()
    mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)
    yield mock_client


@pytest.fixture
def s3_documents_mock(mocker: MockerFixture) -> Generator[MockS3Client, None, None]:
    """Mock S3Client specifically configured for documents operations."""
    mock_client = MockS3Client(bucket_type="DOCUMENTS")
    # Pre-populate with common test document data
    mock_client.uploaded_files["test_document.pdf"] = b"test document content"
    mock_client.uploaded_files["public_doc.pdf"] = b"public document content"
    mock_client.uploaded_files["private_doc.pdf"] = b"private document content"

    mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)
    yield mock_client


@pytest.fixture
def s3_sboms_mock(mocker: MockerFixture) -> Generator[MockS3Client, None, None]:
    """Mock S3Client specifically configured for SBOM operations."""
    mock_client = MockS3Client(bucket_type="SBOMS")

    # Pre-populate with common test SBOM data
    sample_sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"component": {"name": "test-component", "type": "library", "version": "1.0.0"}},
    }
    mock_client.uploaded_files["test_sbom.json"] = json.dumps(sample_sbom).encode()

    # Also add a legacy 1.5 version for testing
    legacy_sbom = sample_sbom.copy()
    legacy_sbom["specVersion"] = "1.5"
    mock_client.uploaded_files["legacy_sbom.json"] = json.dumps(legacy_sbom).encode()

    mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)
    yield mock_client


@pytest.fixture
def s3_error_mock(mocker: MockerFixture) -> Generator[MockS3Client, None, None]:
    """Mock S3Client that raises errors for testing error handling."""
    mock_client = MockS3Client()
    mock_client.configure_error(should_raise=True, message="S3 service unavailable")

    mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)
    yield mock_client


def create_s3_method_mock(
    mocker: MockerFixture, method_name: str, return_value: Any = None, side_effect: Exception | None = None
) -> Mock:
    """
    Create a mock for a specific S3Client method.

    Args:
        mocker: pytest-mock fixture
        method_name: Name of the S3Client method to mock (e.g., 'get_sbom_data')
        return_value: Value to return from the method
        side_effect: Exception to raise when method is called

    Returns:
        The mock object for further configuration
    """
    mock_path = f"sbomify.apps.core.object_store.S3Client.{method_name}"

    if side_effect:
        return mocker.patch(mock_path, side_effect=side_effect)
    else:
        return mocker.patch(mock_path, return_value=return_value)


def create_documents_api_mock(mocker: MockerFixture, scenario: str = "success") -> MagicMock:
    """
    Create a mock specifically for documents.apis.S3Client.

    Args:
        mocker: pytest-mock fixture
        scenario: Test scenario - 'success', 'upload_error', 'download_error', 'not_found'

    Returns:
        Mock S3Client instance configured for the scenario
    """
    mock_s3_client = mocker.patch("sbomify.apps.documents.apis.S3Client")
    mock_instance = MagicMock()
    mock_s3_client.return_value = mock_instance

    if scenario == "success":
        mock_instance.upload_document.return_value = "mocked_filename.pdf"
        mock_instance.get_document_data.return_value = b"test document content"
    elif scenario == "upload_error":
        mock_instance.upload_document.side_effect = Exception("S3 upload failed")
    elif scenario == "download_error":
        mock_instance.get_document_data.side_effect = Exception("S3 download failed")
    elif scenario == "not_found":
        mock_instance.get_document_data.return_value = None
    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    return mock_instance


def create_documents_views_mock(mocker: MockerFixture, scenario: str = "success") -> MagicMock:
    """
    Create a mock specifically for documents.views.S3Client.

    Args:
        mocker: pytest-mock fixture
        scenario: Test scenario - 'success', 'upload_error', 'download_error', 'not_found'

    Returns:
        Mock S3Client instance configured for the scenario
    """
    mock_s3_client = mocker.patch("sbomify.apps.documents.views.document_download.S3Client")
    mock_instance = MagicMock()
    mock_s3_client.return_value = mock_instance

    if scenario == "success":
        mock_instance.upload_document.return_value = "mocked_filename.pdf"
        mock_instance.get_document_data.return_value = b"test document content"
    elif scenario == "upload_error":
        mock_instance.upload_document.side_effect = Exception("S3 upload failed")
    elif scenario == "download_error":
        mock_instance.get_document_data.side_effect = Exception("S3 download failed")
    elif scenario == "not_found":
        mock_instance.get_document_data.return_value = None
    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    return mock_instance


# Type aliases for better type hints
S3MockFactory = Callable[[str], MockS3Client]
S3MethodMock = Callable[[str, Any, Exception | None], Mock]
