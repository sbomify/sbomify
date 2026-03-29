from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError
from django.conf import settings
from pytest_mock.plugin import MockerFixture

from sbomify.apps.core.object_store import ObjectStoreClient, S3ObjectStoreClient, StorageClient


# ---------------------------------------------------------------------------
# ObjectStoreClient (abstract base)
# ---------------------------------------------------------------------------


class TestObjectStoreClient:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            ObjectStoreClient()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# S3ObjectStoreClient
# ---------------------------------------------------------------------------


class TestS3ObjectStoreClient:
    def test_init_with_explicit_credentials(self, mocker: MockerFixture):
        mock_resource = mocker.patch("boto3.resource")
        mock_client = mocker.patch("boto3.client")

        S3ObjectStoreClient(
            region="us-east-1",
            endpoint_url="http://localhost:9000",
            access_key="my-key",
            secret_key="my-secret",
        )

        mock_resource.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://localhost:9000",
            aws_access_key_id="my-key",
            aws_secret_access_key="my-secret",
        )
        mock_client.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://localhost:9000",
            aws_access_key_id="my-key",
            aws_secret_access_key="my-secret",
        )

    def test_init_without_credentials(self, mocker: MockerFixture):
        mock_resource = mocker.patch("boto3.resource")
        mock_client = mocker.patch("boto3.client")

        S3ObjectStoreClient(
            region="us-east-1",
            endpoint_url="http://localhost:9000",
        )

        mock_resource.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://localhost:9000",
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )
        mock_client.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://localhost:9000",
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )

    def test_init_with_empty_string_credentials(self, mocker: MockerFixture):
        """Empty strings (from os.environ.get(..., '')) should be treated as None (no credentials)."""
        mock_resource = mocker.patch("boto3.resource")
        mock_client = mocker.patch("boto3.client")

        S3ObjectStoreClient(
            region="us-east-1",
            endpoint_url="http://localhost:9000",
            access_key="",
            secret_key="",
        )

        # Empty strings should be converted to None so boto3 uses default credential chain
        mock_resource.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://localhost:9000",
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )
        mock_client.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://localhost:9000",
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )

    @pytest.fixture
    def s3_store(self, mocker: MockerFixture):
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")
        store = S3ObjectStoreClient(region="us-east-1", endpoint_url="http://localhost:9000")
        return store, mock_resource.return_value

    def test_put_object(self, s3_store):
        store, mock_s3 = s3_store
        store.put_object("my-bucket", "path/to/key", b"hello")
        mock_s3.Bucket.return_value.put_object.assert_called_once_with(Key="path/to/key", Body=b"hello")

    def test_get_object(self, s3_store):
        store, mock_s3 = s3_store
        mock_body = Mock()
        mock_body.read.return_value = b"hello"
        mock_s3.Bucket.return_value.Object.return_value.get.return_value = {
            "Body": mock_body,
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }
        result = store.get_object("my-bucket", "path/to/key")
        assert result == b"hello"

    def test_delete_object(self, s3_store):
        store, mock_s3 = s3_store
        store.delete_object("my-bucket", "path/to/key")
        mock_s3.Object.return_value.delete.assert_called_once()
        mock_s3.Object.assert_called_with("my-bucket", "path/to/key")

    def test_upload_file(self, s3_store):
        store, mock_s3 = s3_store
        store.upload_file("my-bucket", "/tmp/file.txt", "path/to/key")
        mock_s3.Bucket.return_value.upload_file.assert_called_once_with("/tmp/file.txt", "path/to/key")

    def test_download_file(self, s3_store):
        store, mock_s3 = s3_store
        store.download_file("my-bucket", "path/to/key", "/tmp/file.txt")
        mock_s3.Bucket.return_value.download_file.assert_called_once_with("path/to/key", "/tmp/file.txt")

    def test_generate_presigned_url(self, mocker: MockerFixture):
        mocker.patch("boto3.resource")
        mock_client_fn = mocker.patch("boto3.client")
        mock_client = mock_client_fn.return_value
        mock_client.generate_presigned_url.return_value = "https://s3.example.com/presigned"

        store = S3ObjectStoreClient(region="us-east-1", endpoint_url="http://localhost:9000")
        url = store.generate_presigned_url("my-bucket", "path/to/key", expires_in=7200)

        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "path/to/key"},
            ExpiresIn=7200,
        )
        assert url == "https://s3.example.com/presigned"

    def test_error_propagation(self, s3_store):
        store, mock_s3 = s3_store
        mock_s3.Bucket.return_value.put_object.side_effect = ClientError(
            error_response={"Error": {"Code": "403"}},
            operation_name="PutObject",
        )
        with pytest.raises(ClientError):
            store.put_object("my-bucket", "key", b"data")


# ---------------------------------------------------------------------------
# StorageClient (domain wrapper, delegates to S3ObjectStoreClient)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_s3(mocker: MockerFixture):
    """Mock boto3 S3 resource and return mock bucket/object references."""
    mock_resource = mocker.patch("boto3.resource")
    mocker.patch("boto3.client")
    return mock_resource.return_value


class TestStorageClient:
    def test_creates_s3_store_with_credentials(self, mocker: MockerFixture):
        mocker.patch.object(settings, "AWS_SBOMS_ACCESS_KEY_ID", "test-key")
        mocker.patch.object(settings, "AWS_SBOMS_SECRET_ACCESS_KEY", "test-secret")
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")

        client = StorageClient("SBOMS")

        assert client.bucket_type == "SBOMS"
        assert isinstance(client._store, S3ObjectStoreClient)
        mock_resource.assert_called_once_with(
            "s3",
            region_name=settings.AWS_REGION,
            endpoint_url=settings.AWS_ENDPOINT_URL_S3,
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
        )

    def test_credentials_optional_when_empty(self, mocker: MockerFixture):
        """Empty credential strings (from env defaults) should result in None passed to boto3."""
        mocker.patch.object(settings, "AWS_SBOMS_ACCESS_KEY_ID", "")
        mocker.patch.object(settings, "AWS_SBOMS_SECRET_ACCESS_KEY", "")
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")

        StorageClient("SBOMS")

        mock_resource.assert_called_once_with(
            "s3",
            region_name=settings.AWS_REGION,
            endpoint_url=settings.AWS_ENDPOINT_URL_S3,
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )

    @pytest.mark.parametrize("bucket_type", ["MEDIA", "SBOMS", "DOCUMENTS"])
    def test_client_initialization(self, bucket_type: str, mocker: MockerFixture):
        mocker.patch.object(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "test-key")
        mocker.patch.object(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "test-secret")
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")

        client = StorageClient(bucket_type)

        assert client.bucket_type == bucket_type
        mock_resource.assert_called_once_with(
            "s3",
            region_name=settings.AWS_REGION,
            endpoint_url=settings.AWS_ENDPOINT_URL_S3,
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
        )

    def test_upload_media_success(self, mock_s3):
        test_data = b"test_data"
        client = StorageClient("MEDIA")
        mock_bucket = mock_s3.Bucket.return_value

        client.upload_media("test_object", test_data)

        mock_bucket.put_object.assert_called_once_with(Key="test_object", Body=test_data)
        assert mock_s3.Bucket.call_args[0][0] == settings.AWS_MEDIA_STORAGE_BUCKET_NAME

    def test_upload_sbom_success(self, mock_s3):
        test_data = b"test_data"
        client = StorageClient("SBOMS")
        mock_bucket = mock_s3.Bucket.return_value

        object_name = client.upload_sbom(test_data)

        assert object_name.endswith(".json")
        mock_bucket.put_object.assert_called_once()
        assert mock_s3.Bucket.call_args[0][0] == settings.AWS_SBOMS_STORAGE_BUCKET_NAME

    def test_get_sbom_data_success(self, mock_s3):
        client = StorageClient("SBOMS")
        mock_object = mock_s3.Bucket.return_value.Object.return_value
        mock_body = Mock()
        mock_body.read.return_value = b"test_data"
        mock_object.get.return_value = {
            "Body": mock_body,
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

        data = client.get_sbom_data("test_object")

        assert data == b"test_data"
        mock_s3.Bucket.assert_called_with(settings.AWS_SBOMS_STORAGE_BUCKET_NAME)

    def test_delete_object_success(self, mock_s3):
        client = StorageClient("MEDIA")
        mock_object = mock_s3.Object.return_value

        client.delete_object("test_bucket", "test_object")

        mock_object.delete.assert_called_once()
        mock_s3.Object.assert_called_with("test_bucket", "test_object")

    @pytest.mark.parametrize(
        "method,args",
        [
            ("upload_sbom", (b"data",)),
            ("get_sbom_data", ("test",)),
        ],
    )
    def test_bucket_type_validation(self, method: str, args: tuple, mock_s3):
        client = StorageClient("MEDIA")
        mock_bucket = mock_s3.Bucket.return_value

        with pytest.raises(ValueError) as exc:
            getattr(client, method)(*args)

        assert "only for SBOMS bucket" in str(exc.value)
        mock_bucket.put_object.assert_not_called()
        mock_s3.Bucket.return_value.Object.return_value.get.assert_not_called()

    def test_error_handling(self, mock_s3):
        client = StorageClient("MEDIA")
        mock_s3.Bucket.return_value.put_object.side_effect = ClientError(
            error_response={"Error": {"Code": 403}}, operation_name="PutObject"
        )

        with pytest.raises(ClientError):
            client.upload_media("test", b"data")

    def test_generate_presigned_url(self, mocker: MockerFixture):
        mocker.patch("boto3.resource")
        mock_client_fn = mocker.patch("boto3.client")
        mock_client = mock_client_fn.return_value
        mock_client.generate_presigned_url.return_value = "https://s3.example.com/presigned"

        client = StorageClient("DOCUMENTS")
        url = client.generate_presigned_url("my-bucket", "path/to/key", expires_in=3600)

        assert url == "https://s3.example.com/presigned"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "path/to/key"},
            ExpiresIn=3600,
        )
