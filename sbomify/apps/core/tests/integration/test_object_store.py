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
        # boto3.client is lazy — not called at construction time
        mock_client.assert_not_called()

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
        mock_client.assert_not_called()

    def test_init_with_empty_string_credentials(self, mocker: MockerFixture):
        """Empty strings should be passed as-is — normalization is the caller's responsibility."""
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")

        S3ObjectStoreClient(
            region="us-east-1",
            endpoint_url="http://localhost:9000",
            access_key="",
            secret_key="",
        )

        mock_resource.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://localhost:9000",
            aws_access_key_id="",
            aws_secret_access_key="",
        )

    @pytest.fixture
    def s3_store(self, mocker: MockerFixture):
        mock_resource = mocker.patch("boto3.resource")
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
        # boto3.client is lazy — not created until first presigned URL call
        mock_client_fn.assert_not_called()

        url = store.generate_presigned_url("my-bucket", "path/to/key", expires_in=7200)

        # Now it should have been created
        mock_client_fn.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://localhost:9000",
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "path/to/key"},
            ExpiresIn=7200,
        )
        assert url == "https://s3.example.com/presigned"

    def test_get_object_returns_none_for_missing_key(self, s3_store):
        store, mock_s3 = s3_store
        mock_s3.Bucket.return_value.Object.return_value.get.side_effect = ClientError(
            error_response={"Error": {"Code": "NoSuchKey"}},
            operation_name="GetObject",
        )
        result = store.get_object("my-bucket", "missing/key")
        assert result is None

    def test_get_object_raises_on_other_errors(self, s3_store):
        store, mock_s3 = s3_store
        mock_s3.Bucket.return_value.Object.return_value.get.side_effect = ClientError(
            error_response={"Error": {"Code": "AccessDenied"}},
            operation_name="GetObject",
        )
        with pytest.raises(ClientError):
            store.get_object("my-bucket", "path/to/key")

    def test_error_propagation(self, s3_store):
        store, mock_s3 = s3_store
        mock_s3.Bucket.return_value.put_object.side_effect = ClientError(
            error_response={"Error": {"Code": "403"}},
            operation_name="PutObject",
        )
        with pytest.raises(ClientError):
            store.put_object("my-bucket", "key", b"data")


# ---------------------------------------------------------------------------
# StorageClient (domain wrapper, delegates to ObjectStoreClient)
# ---------------------------------------------------------------------------


class TestStorageClient:
    @pytest.fixture(autouse=True)
    def _mock_store(self, mocker: MockerFixture):
        """Replace _create_store so StorageClient gets a mock ObjectStoreClient."""
        self.mock_store = mocker.MagicMock(spec=S3ObjectStoreClient)
        mocker.patch("sbomify.apps.core.object_store._create_store", return_value=self.mock_store)

    def test_creates_s3_store_with_credentials(self, mocker: MockerFixture):
        # Undo autouse mock to test real _create_store
        mocker.stopall()
        mocker.patch.object(settings, "AWS_SBOMS_ACCESS_KEY_ID", "test-key")
        mocker.patch.object(settings, "AWS_SBOMS_SECRET_ACCESS_KEY", "test-secret")
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        mock_resource = mocker.patch("boto3.resource")

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
        mocker.stopall()
        mocker.patch.object(settings, "AWS_SBOMS_ACCESS_KEY_ID", "")
        mocker.patch.object(settings, "AWS_SBOMS_SECRET_ACCESS_KEY", "")
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        mock_resource = mocker.patch("boto3.resource")

        StorageClient("SBOMS")

        mock_resource.assert_called_once_with(
            "s3",
            region_name=settings.AWS_REGION,
            endpoint_url=settings.AWS_ENDPOINT_URL_S3,
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )

    def test_unsupported_backend_raises(self, mocker: MockerFixture):
        mocker.stopall()
        mocker.patch.object(settings, "STORAGE_BACKEND", "azure")
        with pytest.raises(ValueError, match="Unsupported STORAGE_BACKEND"):
            StorageClient("SBOMS")

    @pytest.mark.parametrize("bucket_type", ["MEDIA", "SBOMS", "DOCUMENTS"])
    def test_client_initialization(self, bucket_type: str):
        client = StorageClient(bucket_type)
        assert client.bucket_type == bucket_type
        assert client._store is self.mock_store

    def test_upload_data_as_file_delegates(self):
        client = StorageClient("MEDIA")
        client.upload_data_as_file("my-bucket", "key", b"data")
        self.mock_store.put_object.assert_called_once_with("my-bucket", "key", b"data")

    def test_upload_media_delegates(self):
        client = StorageClient("MEDIA")
        client.upload_media("test_object", b"test_data")
        self.mock_store.put_object.assert_called_once_with(
            settings.AWS_MEDIA_STORAGE_BUCKET_NAME, "test_object", b"test_data"
        )

    def test_upload_sbom_delegates(self):
        client = StorageClient("SBOMS")
        object_name = client.upload_sbom(b"test_data")
        assert object_name.endswith(".json")
        self.mock_store.put_object.assert_called_once()
        call_args = self.mock_store.put_object.call_args
        assert call_args[0][0] == settings.AWS_SBOMS_STORAGE_BUCKET_NAME

    def test_get_sbom_data_delegates(self):
        self.mock_store.get_object.return_value = b"test_data"
        client = StorageClient("SBOMS")
        data = client.get_sbom_data("test_object")
        assert data == b"test_data"
        self.mock_store.get_object.assert_called_once_with(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, "test_object")

    def test_get_file_data_delegates(self):
        self.mock_store.get_object.return_value = b"file_bytes"
        client = StorageClient("SBOMS")
        data = client.get_file_data("my-bucket", "path/to/file")
        assert data == b"file_bytes"
        self.mock_store.get_object.assert_called_once_with("my-bucket", "path/to/file")

    def test_delete_object_delegates(self):
        client = StorageClient("MEDIA")
        client.delete_object("test_bucket", "test_object")
        self.mock_store.delete_object.assert_called_once_with("test_bucket", "test_object")

    def test_upload_file_delegates(self):
        client = StorageClient("MEDIA")
        client.upload_file("my-bucket", "/tmp/file.txt", "key")
        self.mock_store.upload_file.assert_called_once_with("my-bucket", "/tmp/file.txt", "key")

    def test_download_file_delegates(self):
        client = StorageClient("MEDIA")
        client.download_file("my-bucket", "key", "/tmp/file.txt")
        self.mock_store.download_file.assert_called_once_with("my-bucket", "key", "/tmp/file.txt")

    def test_generate_presigned_url_delegates(self):
        self.mock_store.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        client = StorageClient("DOCUMENTS")
        url = client.generate_presigned_url("my-bucket", "path/to/key", expires_in=3600)
        assert url == "https://s3.example.com/presigned"
        self.mock_store.generate_presigned_url.assert_called_once_with("my-bucket", "path/to/key", 3600)

    @pytest.mark.parametrize(
        "method,args",
        [
            ("upload_sbom", (b"data",)),
            ("get_sbom_data", ("test",)),
        ],
    )
    def test_bucket_type_validation(self, method: str, args: tuple):
        client = StorageClient("MEDIA")
        with pytest.raises(ValueError, match="only for SBOMS bucket"):
            getattr(client, method)(*args)

    def test_error_propagation(self):
        self.mock_store.put_object.side_effect = ClientError(
            error_response={"Error": {"Code": 403}}, operation_name="PutObject"
        )
        client = StorageClient("MEDIA")
        with pytest.raises(ClientError):
            client.upload_media("test", b"data")
