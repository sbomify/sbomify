"""GCSObjectStoreClient: the native Google Cloud Storage backend (ADR-0007).

The google-cloud-storage client is mocked; what is under test is the contract
the rest of the application relies on: S3-shaped errors, absence reported as
None/False, and signed URLs that work without a private key.
"""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from google.api_core import exceptions as gexc
from google.auth import credentials as gcreds
from google.auth.exceptions import DefaultCredentialsError
from pytest_mock.plugin import MockerFixture

from sbomify.apps.core.object_store import (
    GCSObjectStoreClient,
    ObjectStoreUnavailableError,
    StorageClient,
)


@pytest.fixture
def gcs(mocker: MockerFixture):
    """A GCSObjectStoreClient whose storage.Client is a mock, plus that mock."""
    # The client cache is per thread and class-wide; start every test empty.
    GCSObjectStoreClient._local.__dict__.clear()
    client = MagicMock(name="storage.Client()")
    factory = mocker.patch("google.cloud.storage.Client", return_value=client)
    store = GCSObjectStoreClient()
    yield store, client, factory
    GCSObjectStoreClient._local.__dict__.clear()


def _blob(client: MagicMock) -> MagicMock:
    return client.bucket.return_value.blob.return_value


class TestBackendSelection:
    def test_gcs_backend_is_selected(self, mocker: MockerFixture):
        mocker.patch.object(settings, "STORAGE_BACKEND", "gcs")
        mocker.patch.object(settings, "GCS_PROJECT_ID", "acme", create=True)
        mocker.patch.object(settings, "GCS_SIGNING_SERVICE_ACCOUNT", "", create=True)
        store = StorageClient("SBOMS")._store
        assert isinstance(store, GCSObjectStoreClient)
        assert store._project == "acme"
        assert store._signing_service_account is None

    def test_no_static_credentials_are_read(self, mocker: MockerFixture, gcs):
        # Building the client must not reach for AWS-style keys; the only
        # authentication is Application Default Credentials.
        store, _client, factory = gcs
        store.get_object("b", "k")
        factory.assert_called_once_with(project=None)

    def test_client_is_reused_within_a_thread(self, gcs):
        store, _client, factory = gcs
        store.get_object("b", "k")
        store.object_exists("b", "k")
        GCSObjectStoreClient().get_object("b", "k")
        assert factory.call_count == 1

    def test_missing_credentials_surface_as_unavailable(self, mocker: MockerFixture):
        GCSObjectStoreClient._local.__dict__.clear()
        mocker.patch("google.cloud.storage.Client", side_effect=DefaultCredentialsError("no ADC"))
        with pytest.raises(ObjectStoreUnavailableError) as exc:
            GCSObjectStoreClient().get_object("b", "k")
        assert isinstance(exc.value, BotoCoreError)


class TestDataOperations:
    def test_put_object_defaults_to_octet_stream(self, gcs):
        store, client, _ = gcs
        store.put_object("bucket", "key", b"data")
        client.bucket.assert_called_with("bucket")
        client.bucket.return_value.blob.assert_called_with("key")
        args, kwargs = _blob(client).upload_from_string.call_args
        assert args == (b"data",)
        assert kwargs["content_type"] == "application/octet-stream"

    def test_put_object_keeps_given_content_type(self, gcs):
        store, client, _ = gcs
        store.put_object("bucket", "logo.png", b"png", "image/png")
        assert _blob(client).upload_from_string.call_args.kwargs["content_type"] == "image/png"

    def test_get_object_returns_bytes(self, gcs):
        store, client, _ = gcs
        _blob(client).download_as_bytes.return_value = b"hello"
        assert store.get_object("bucket", "key") == b"hello"

    def test_get_missing_object_returns_none(self, gcs):
        store, client, _ = gcs
        _blob(client).download_as_bytes.side_effect = gexc.NotFound("No such object: bucket/key")
        assert store.get_object("bucket", "key") is None

    def test_get_from_missing_bucket_raises_no_such_bucket(self, gcs):
        # A missing bucket is misconfiguration, not absence: callers branch on
        # NoSuchBucket exactly as they do for S3.
        store, client, _ = gcs
        _blob(client).download_as_bytes.side_effect = gexc.NotFound("The specified bucket does not exist.")
        with pytest.raises(ClientError) as exc:
            store.get_object("bucket", "key")
        assert exc.value.response["Error"]["Code"] == "NoSuchBucket"

    def test_permission_denied_maps_to_access_denied(self, gcs):
        store, client, _ = gcs
        _blob(client).upload_from_string.side_effect = gexc.Forbidden("storage.objects.create denied")
        with pytest.raises(ClientError) as exc:
            store.put_object("bucket", "key", b"x")
        assert exc.value.response["Error"]["Code"] == "AccessDenied"
        assert isinstance(exc.value.__cause__, gexc.Forbidden)

    def test_other_api_errors_keep_their_status(self, gcs):
        store, client, _ = gcs
        _blob(client).download_as_bytes.side_effect = gexc.ServiceUnavailable("try later")
        with pytest.raises(ClientError) as exc:
            store.get_object("bucket", "key")
        assert exc.value.response["Error"]["Code"] == "503"

    def test_delete_missing_object_is_not_an_error(self, gcs):
        store, client, _ = gcs
        _blob(client).delete.side_effect = gexc.NotFound("No such object: bucket/key")
        store.delete_object("bucket", "key")

    def test_object_exists(self, gcs):
        store, client, _ = gcs
        assert store.object_exists("bucket", "key") is True
        _blob(client).reload.side_effect = gexc.NotFound("No such object: bucket/key")
        assert store.object_exists("bucket", "key") is False

    def test_iter_and_list_objects(self, gcs):
        store, client, _ = gcs
        blobs = [MagicMock(), MagicMock()]
        blobs[0].name, blobs[1].name = "agg/a", "agg/b"
        client.list_blobs.return_value = iter(blobs)
        assert store.list_objects("bucket", "agg/") == ["agg/a", "agg/b"]
        assert client.list_blobs.call_args.args == ("bucket",)
        assert client.list_blobs.call_args.kwargs["prefix"] == "agg/"

    def test_listing_error_while_paging_is_translated(self, gcs):
        store, client, _ = gcs

        def pages():
            yield MagicMock(name="first")
            raise gexc.Forbidden("storage.objects.list denied")

        client.list_blobs.return_value = pages()
        it = store.iter_objects("bucket", "")
        next(it)
        with pytest.raises(ClientError):
            next(it)

    def test_file_transfers(self, gcs):
        store, client, _ = gcs
        store.upload_file("bucket", "/tmp/in", "key")
        _blob(client).upload_from_filename.assert_called_once()
        assert _blob(client).upload_from_filename.call_args.args == ("/tmp/in",)
        store.download_file("bucket", "key", "/tmp/out")
        assert _blob(client).download_to_filename.call_args.args == ("/tmp/out",)


class _KeyedCredentials(gcreds.Signing, gcreds.Credentials):
    """Service-account-key credentials: can sign locally."""

    def refresh(self, request):  # pragma: no cover - never refreshed
        pass

    def sign_bytes(self, message):  # pragma: no cover
        return b""

    @property
    def signer_email(self):  # pragma: no cover
        return "key@acme.iam.gserviceaccount.com"

    @property
    def signer(self):  # pragma: no cover
        return None


class TestSignedUrls:
    def test_rejects_non_positive_expiry(self, gcs):
        store, _client, _ = gcs
        with pytest.raises(ValueError, match="positive"):
            store.generate_presigned_url("bucket", "key", 0)

    def test_rejects_unknown_response_header(self, gcs):
        store, _client, _ = gcs
        with pytest.raises(ValueError, match="Unsupported response header"):
            store.generate_presigned_url("bucket", "key", 60, {"ResponseCacheControl": "no-cache"})

    def test_key_credentials_sign_locally(self, gcs):
        store, client, _ = gcs
        client._credentials = _KeyedCredentials()
        _blob(client).generate_signed_url.return_value = "https://signed"
        url = store.generate_presigned_url(
            "bucket",
            "key",
            900,
            {"ResponseContentDisposition": 'attachment; filename="x.zip"', "ResponseContentType": "application/zip"},
        )
        assert url == "https://signed"
        kwargs = _blob(client).generate_signed_url.call_args.kwargs
        assert kwargs["version"] == "v4"
        assert kwargs["expiration"] == timedelta(seconds=900)
        assert kwargs["response_disposition"] == 'attachment; filename="x.zip"'
        assert kwargs["response_type"] == "application/zip"
        assert "access_token" not in kwargs

    def test_workload_identity_signs_through_iam(self, gcs):
        # Workload Identity credentials have no key: sign through IAM signBlob
        # as the workload's own service account with a fresh access token.
        store, client, _ = gcs
        creds = MagicMock(spec=["valid", "refresh", "token", "service_account_email"])
        creds.valid = False
        creds.token = "ya29.token"
        creds.service_account_email = "sbomify@acme.iam.gserviceaccount.com"
        client._credentials = creds
        store.generate_presigned_url("bucket", "key", 60)
        creds.refresh.assert_called_once()
        kwargs = _blob(client).generate_signed_url.call_args.kwargs
        assert kwargs["service_account_email"] == "sbomify@acme.iam.gserviceaccount.com"
        assert kwargs["access_token"] == "ya29.token"

    def test_configured_signer_overrides_workload_account(self, mocker: MockerFixture, gcs):
        _store, client, _ = gcs
        store = GCSObjectStoreClient(signing_service_account="signer@acme.iam.gserviceaccount.com")
        creds = MagicMock(spec=["valid", "refresh", "token", "service_account_email"])
        creds.valid = True
        creds.token = "ya29.token"
        creds.service_account_email = "default"
        client._credentials = creds
        store.generate_presigned_url("bucket", "key", 60)
        kwargs = _blob(client).generate_signed_url.call_args.kwargs
        assert kwargs["service_account_email"] == "signer@acme.iam.gserviceaccount.com"

    def test_unresolvable_signer_is_reported(self, gcs):
        store, client, _ = gcs
        creds = MagicMock(spec=["valid", "refresh", "token", "service_account_email"])
        creds.valid = True
        creds.service_account_email = "default"
        client._credentials = creds
        with pytest.raises(ObjectStoreUnavailableError, match="GCS_SIGNING_SERVICE_ACCOUNT"):
            store.generate_presigned_url("bucket", "key", 60)

    def test_missing_token_creator_role_is_access_denied(self, gcs):
        store, client, _ = gcs
        client._credentials = _KeyedCredentials()
        _blob(client).generate_signed_url.side_effect = gexc.Forbidden("iam.serviceAccounts.signBlob denied")
        with pytest.raises(ClientError) as exc:
            store.generate_presigned_url("bucket", "key", 60)
        assert exc.value.response["Error"]["Code"] == "AccessDenied"
