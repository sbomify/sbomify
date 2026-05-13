"""Shared fixtures for compliance tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_s3_client():
    """Patch ``boto3.client`` and yield the mocked S3 instance.

    ``get_download_url`` does ``import boto3`` inside the function
    body then calls ``boto3.client("s3", ...)``; patching
    ``boto3.client`` at module level intercepts that call because the
    local import resolves to the same module object. The fixture
    pre-configures ``generate_presigned_url`` with a stable URL so
    tests that only care about call-args don't need to set it
    themselves.
    """
    with patch("boto3.client") as mock_client_fn:
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_client_fn.return_value = mock_s3
        yield mock_s3
