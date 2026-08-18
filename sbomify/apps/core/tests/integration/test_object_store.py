from unittest.mock import ANY, Mock

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
            config=ANY,
        )
        # boto3.client is lazy — not called at construction time
        mock_client.assert_not_called()

    def test_object_exists_uses_head_not_listing(self, mocker: MockerFixture):
        """Existence is a HEAD, so it does not require ListBucket.

        Least-privilege policies commonly grant GetObject/PutObject/DeleteObject
        without ListBucket. A prefix-listing implementation would report a
        readable object as absent (or fail outright) under such a policy.
        """
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")

        store = S3ObjectStoreClient(region="us-east-1", access_key="k", secret_key="s")
        assert store.object_exists("my-bucket", "some/key.json") is True

        mock_resource.return_value.Object.assert_called_once_with("my-bucket", "some/key.json")
        mock_resource.return_value.Object.return_value.load.assert_called_once()
        # No bucket listing anywhere in that path.
        mock_resource.return_value.Bucket.assert_not_called()

    def test_object_exists_false_when_head_404s(self, mocker: MockerFixture):
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")
        mock_resource.return_value.Object.return_value.load.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        store = S3ObjectStoreClient(region="us-east-1", access_key="k", secret_key="s")
        assert store.object_exists("my-bucket", "absent.json") is False

    def test_object_exists_propagates_other_errors(self, mocker: MockerFixture):
        """AccessDenied must not read as absent."""
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")
        mock_resource.return_value.Object.return_value.load.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "HeadObject"
        )

        store = S3ObjectStoreClient(region="us-east-1", access_key="k", secret_key="s")
        with pytest.raises(ClientError):
            store.object_exists("my-bucket", "forbidden.json")

    def test_response_headers_cannot_override_bucket_or_key(self, mocker: MockerFixture):
        """The call's own arguments win over the response-header mapping.

        Applying the mapping last would let a stray "Bucket" or "Key" sign a URL
        for a different object than the caller named, which on a presigned URL
        means handing out access to something else entirely.
        """
        mocker.patch("boto3.resource")
        mock_client_fn = mocker.patch("boto3.client")

        store = S3ObjectStoreClient(region="us-east-1", access_key="k", secret_key="s")
        store.generate_presigned_url(
            "right-bucket",
            "right/key.zip",
            expires_in=900,
            response_headers={
                "Bucket": "attacker-bucket",
                "Key": "someone/elses.zip",
                "ResponseContentType": "application/zip",
            },
        )

        params = mock_client_fn.return_value.generate_presigned_url.call_args.kwargs["Params"]
        assert params["Bucket"] == "right-bucket"
        assert params["Key"] == "right/key.zip"
        assert params["ResponseContentType"] == "application/zip"

    def test_signature_version_is_pinned_to_s3v4(self, mocker: MockerFixture):
        """SigV4 is set explicitly, not left to botocore to resolve.

        Verified against SeaweedFS: a presigned GET carrying response-header
        overrides (the CRA bundle download forces an attachment disposition) is
        rejected with SignatureDoesNotMatch under the default configuration and
        accepted when this is set, even though the default already resolves to
        s3v4. Addressing style is deliberately not forced: it made no
        difference, and path-style would break AWS buckets created after
        Sept 2020.
        """
        mock_resource = mocker.patch("boto3.resource")
        mocker.patch("boto3.client")

        S3ObjectStoreClient(region="us-east-1", access_key="k", secret_key="s")

        config = mock_resource.call_args.kwargs["config"]
        assert config.signature_version == "s3v4"
        assert config.s3 is None, "addressing style must stay unforced"

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
            config=ANY,
        )
        mock_client.assert_not_called()

    def test_repr_does_not_expose_secrets(self, mocker: MockerFixture):
        mocker.patch("boto3.resource")
        store = S3ObjectStoreClient(
            region="us-east-1",
            endpoint_url="http://localhost:9000",
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        r = repr(store)
        assert "us-east-1" in r
        assert "localhost:9000" in r
        assert "AKIAIOSFODNN7EXAMPLE" not in r
        assert "wJalrXUtnFEMI" not in r

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
            config=ANY,
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
            config=ANY,
        )
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "path/to/key"},
            ExpiresIn=7200,
        )
        assert url == "https://s3.example.com/presigned"

    @pytest.mark.parametrize("bad_value", [0, -1, -3600])
    def test_generate_presigned_url_rejects_non_positive_expiry(self, mocker: MockerFixture, bad_value: int):
        mocker.patch("boto3.resource")
        store = S3ObjectStoreClient(region="us-east-1", endpoint_url="http://localhost:9000")
        with pytest.raises(ValueError, match="expires_in must be positive"):
            store.generate_presigned_url("my-bucket", "key", expires_in=bad_value)

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

    def test_generate_presigned_url_propagates_client_error(self, mocker: MockerFixture):
        mocker.patch("boto3.resource")
        mock_client_fn = mocker.patch("boto3.client")
        mock_client_fn.return_value.generate_presigned_url.side_effect = ClientError(
            error_response={"Error": {"Code": "ExpiredToken"}},
            operation_name="GeneratePresignedUrl",
        )
        store = S3ObjectStoreClient(region="us-east-1", endpoint_url="http://localhost:9000")
        with pytest.raises(ClientError):
            store.generate_presigned_url("my-bucket", "key")

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
            config=ANY,
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
            config=ANY,
        )

    def test_empty_endpoint_url_normalized_to_none(self, mocker: MockerFixture):
        """Empty AWS_ENDPOINT_URL_S3 (production default) should be normalized to None for boto3."""
        mocker.stopall()
        mocker.patch.object(settings, "AWS_SBOMS_ACCESS_KEY_ID", "test-key")
        mocker.patch.object(settings, "AWS_SBOMS_SECRET_ACCESS_KEY", "test-secret")
        mocker.patch.object(settings, "AWS_ENDPOINT_URL_S3", "")
        mocker.patch.object(settings, "AWS_REGION", "")
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        mock_resource = mocker.patch("boto3.resource")

        StorageClient("SBOMS")

        mock_resource.assert_called_once_with(
            "s3",
            region_name=None,
            endpoint_url=None,
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            config=ANY,
        )

    def test_invalid_bucket_type_raises(self, mocker: MockerFixture):
        mocker.stopall()
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        mocker.patch("boto3.resource")
        with pytest.raises(ValueError, match="Invalid bucket_type"):
            StorageClient("INVALID")  # type: ignore[arg-type]

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

    def test_object_exists_delegates(self):
        self.mock_store.object_exists.return_value = True
        assert StorageClient("SBOMS").object_exists("my-bucket", "k.json") is True
        self.mock_store.object_exists.assert_called_once_with("my-bucket", "k.json")

    def test_generate_presigned_url_delegates(self):
        self.mock_store.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        client = StorageClient("DOCUMENTS")
        url = client.generate_presigned_url("my-bucket", "path/to/key", expires_in=3600)
        assert url == "https://s3.example.com/presigned"
        self.mock_store.generate_presigned_url.assert_called_once_with("my-bucket", "path/to/key", 3600, None)

    def test_generate_presigned_url_passes_response_headers(self):
        """Response-header overrides reach the backend.

        The CRA bundle download relies on this: it forces
        Content-Disposition: attachment so a ZIP of regulated evidence
        downloads rather than rendering inline.
        """
        self.mock_store.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        client = StorageClient("DOCUMENTS")
        headers = {"ResponseContentDisposition": 'attachment; filename="bundle.zip"'}
        client.generate_presigned_url("my-bucket", "path/to/key", expires_in=900, response_headers=headers)
        self.mock_store.generate_presigned_url.assert_called_once_with("my-bucket", "path/to/key", 900, headers)

    @pytest.mark.parametrize(
        "method,args,wrong_type,expected_match",
        [
            ("upload_sbom", (b"data",), "MEDIA", "only for SBOMS bucket"),
            ("get_sbom_data", ("test",), "MEDIA", "only for SBOMS bucket"),
            ("upload_document", (b"data",), "SBOMS", "only for DOCUMENTS bucket"),
            ("get_document_data", ("test",), "SBOMS", "only for DOCUMENTS bucket"),
            ("upload_media", ("obj", b"data"), "SBOMS", "only for MEDIA bucket"),
        ],
    )
    def test_bucket_type_validation(self, method: str, args: tuple, wrong_type: str, expected_match: str):
        client = StorageClient(wrong_type)
        with pytest.raises(ValueError, match=expected_match):
            getattr(client, method)(*args)

    def test_generate_presigned_url_propagates_errors(self):
        self.mock_store.generate_presigned_url.side_effect = ClientError(
            error_response={"Error": {"Code": "NoSuchBucket"}}, operation_name="GeneratePresignedUrl"
        )
        client = StorageClient("SBOMS")
        with pytest.raises(ClientError):
            client.generate_presigned_url("missing-bucket", "key")

    def test_error_propagation(self):
        self.mock_store.put_object.side_effect = ClientError(
            error_response={"Error": {"Code": 403}}, operation_name="PutObject"
        )
        client = StorageClient("MEDIA")
        with pytest.raises(ClientError):
            client.upload_media("test", b"data")
