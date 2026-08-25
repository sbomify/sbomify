from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError
from django.conf import settings
from pytest_mock.plugin import MockerFixture

from sbomify.apps.core.object_store import S3Client


@pytest.fixture
def mock_s3(mocker: MockerFixture):
    """Mock boto3 S3 resource and return mock bucket/object references"""
    mock_resource = mocker.patch("boto3.resource")
    mock_s3 = mock_resource.return_value
    return mock_s3


class TestS3Client:
    @pytest.mark.parametrize("bucket_type", ["MEDIA", "SBOMS"])
    def test_client_initialization(self, bucket_type: str, mocker: MockerFixture):
        """Test S3 client initialization with different bucket types"""
        # Mock settings access
        mocker.patch.object(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "test-key")
        mocker.patch.object(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "test-secret")

        # Mock boto3 and capture constructor args
        mock_resource = mocker.patch("boto3.resource")

        client = S3Client(bucket_type)

        # Verify initialization parameters
        assert client.bucket_type == bucket_type
        mock_resource.assert_called_once()
        args, kwargs = mock_resource.call_args
        assert args == ("s3",)
        assert kwargs["region_name"] == settings.AWS_REGION
        assert kwargs["endpoint_url"] == settings.AWS_ENDPOINT_URL_S3
        assert kwargs["aws_access_key_id"] == "test-key"
        assert kwargs["aws_secret_access_key"] == "test-secret"

    @pytest.mark.parametrize("bucket_type", ["MEDIA", "SBOMS", "DOCUMENTS"])
    def test_transfers_have_bounded_timeouts_and_retries(self, bucket_type: str, mocker: MockerFixture):
        """Every bucket's client, not just the one a caller happened to check.

        Botocore's defaults are a 60 second connect and a 60 second read, and
        these clients are used from background tasks with shorter limits of
        their own — the VEX re-apply allows two minutes for all its work, so one
        unresponsive read took half of it and the task died mid-socket-read with
        ``TimeLimitExceeded`` instead of failing the read and retrying it.
        """
        mocker.patch.object(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "test-key")
        mocker.patch.object(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "test-secret")
        mock_resource = mocker.patch("boto3.resource")

        S3Client(bucket_type)

        config = mock_resource.call_args.kwargs["config"]
        assert 0 < config.connect_timeout < 60
        assert 0 < config.read_timeout < 60
        # ``standard`` backs off between attempts and covers connection errors;
        # botocore's ``legacy`` default is narrower.
        assert config.retries["mode"] == "standard"
        assert config.retries["max_attempts"] > 1

    def test_upload_media_success(self, mock_s3):
        """Test media upload to correct bucket"""
        test_data = b"test_data"
        client = S3Client("MEDIA")
        mock_bucket = mock_s3.Bucket.return_value

        client.upload_media("test_object", test_data)

        mock_bucket.put_object.assert_called_once_with(
            Key="test_object",
            Body=test_data
        )
        assert mock_s3.Bucket.call_args[0][0] == settings.AWS_MEDIA_STORAGE_BUCKET_NAME

    def test_upload_sbom_success(self, mock_s3):
        """Test SBOM upload with generated filename"""
        test_data = b"test_data"
        client = S3Client("SBOMS")
        mock_bucket = mock_s3.Bucket.return_value

        object_name = client.upload_sbom(test_data)

        assert object_name.endswith(".json")
        mock_bucket.put_object.assert_called_once()
        assert mock_s3.Bucket.call_args[0][0] == settings.AWS_SBOMS_STORAGE_BUCKET_NAME

    def test_get_sbom_data_success(self, mock_s3):
        """Test retrieving SBOM data from correct bucket"""
        client = S3Client("SBOMS")
        mock_object = mock_s3.Bucket.return_value.Object.return_value
        # Create mock body with read() method using unittest.mock.Mock
        mock_body = Mock()
        mock_body.read.return_value = b"test_data"
        mock_object.get.return_value = {
            "Body": mock_body,
            "ResponseMetadata": {"HTTPStatusCode": 200}
        }

        data = client.get_sbom_data("test_object")

        assert data == b"test_data"
        mock_s3.Bucket.assert_called_with(settings.AWS_SBOMS_STORAGE_BUCKET_NAME)

    def test_delete_object_success(self, mock_s3):
        """Test object deletion in correct bucket"""
        client = S3Client("MEDIA")
        mock_object = mock_s3.Object.return_value

        client.delete_object("test_bucket", "test_object")

        mock_object.delete.assert_called_once()
        mock_s3.Object.assert_called_with("test_bucket", "test_object")

    @pytest.mark.parametrize("method,args", [
        # Test MEDIA client trying to call SBOMS-only methods
        ("upload_sbom", (b"data",)),
        ("get_sbom_data", ("test",)),
    ])
    def test_bucket_type_validation(self, method: str, args: tuple, mock_s3):
        """Test methods validate bucket type before operation"""
        client = S3Client("MEDIA")

        # Setup mock for any S3 operations that might be called
        mock_bucket = mock_s3.Bucket.return_value

        with pytest.raises(ValueError) as exc:
            getattr(client, method)(*args)

        assert "only for SBOMS bucket" in str(exc.value)

        # Verify no S3 operations were called
        mock_bucket.put_object.assert_not_called()
        mock_s3.Bucket.return_value.Object.return_value.get.assert_not_called()

    def test_error_handling(self, mock_s3):
        """Test ClientError propagation"""
        client = S3Client("MEDIA")
        mock_s3.Bucket.return_value.put_object.side_effect = ClientError(
            error_response={"Error": {"Code": 403}},
            operation_name="PutObject"
        )

        with pytest.raises(ClientError):
            client.upload_media("test", b"data")