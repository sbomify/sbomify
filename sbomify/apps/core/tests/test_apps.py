import os

import pytest
from django.conf import settings
from pytest_mock import MockerFixture

from sbomify.apps.core.apps import CoreConfig


class TestStorageCredentialValidation:
    def test_mismatched_credentials_access_key_only(self, mocker: MockerFixture):
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        mocker.patch.object(settings, "AWS_SBOMS_ACCESS_KEY_ID", "test-key")
        mocker.patch.object(settings, "AWS_SBOMS_SECRET_ACCESS_KEY", "")
        with pytest.raises(ValueError, match="must both be set or both be empty"):
            CoreConfig._validate_storage_credentials()

    def test_mismatched_credentials_secret_key_only(self, mocker: MockerFixture):
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        mocker.patch.object(settings, "AWS_SBOMS_ACCESS_KEY_ID", "")
        mocker.patch.object(settings, "AWS_SBOMS_SECRET_ACCESS_KEY", "test-secret")
        with pytest.raises(ValueError, match="must both be set or both be empty"):
            CoreConfig._validate_storage_credentials()

    def test_both_credentials_empty_is_valid(self, mocker: MockerFixture):
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        for bucket_type in ("MEDIA", "SBOMS", "DOCUMENTS"):
            mocker.patch.object(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "")
            mocker.patch.object(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "")
        CoreConfig._validate_storage_credentials()  # should not raise

    def test_both_credentials_set_is_valid(self, mocker: MockerFixture):
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        for bucket_type in ("MEDIA", "SBOMS", "DOCUMENTS"):
            mocker.patch.object(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "key")
            mocker.patch.object(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "secret")
        CoreConfig._validate_storage_credentials()  # should not raise

    def test_skipped_for_non_s3_backend(self, mocker: MockerFixture):
        mocker.patch.object(settings, "STORAGE_BACKEND", "gcs")
        mocker.patch.object(settings, "AWS_SBOMS_ACCESS_KEY_ID", "key-only")
        mocker.patch.object(settings, "AWS_SBOMS_SECRET_ACCESS_KEY", "")
        CoreConfig._validate_storage_credentials()  # should not raise

    def test_partial_documents_credentials_are_caught(self, mocker: MockerFixture):
        """A half-configured documents pair must not hide behind the SBOMs fallback.

        AWS_DOCUMENTS_ACCESS_KEY_ID and AWS_DOCUMENTS_SECRET_ACCESS_KEY fall back
        to their SBOMs equivalents independently, so supplying only the access
        key resolves to the documents key alongside the SBOMs secret. That reads
        as a complete pair in settings and fails at runtime against the bucket.
        """
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        for bucket_type in ("MEDIA", "SBOMS", "DOCUMENTS"):
            mocker.patch.object(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "key")
            mocker.patch.object(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "secret")
        env = {k: v for k, v in os.environ.items() if k != "AWS_DOCUMENTS_SECRET_ACCESS_KEY"}
        env["AWS_DOCUMENTS_ACCESS_KEY_ID"] = "documents-key-only"
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(ValueError, match="AWS_DOCUMENTS_SECRET_ACCESS_KEY"):
            CoreConfig._validate_storage_credentials()

    def test_both_documents_credentials_supplied_is_valid(self, mocker: MockerFixture):
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        for bucket_type in ("MEDIA", "SBOMS", "DOCUMENTS"):
            mocker.patch.object(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "key")
            mocker.patch.object(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "secret")
        mocker.patch.dict(
            os.environ,
            {
                "AWS_DOCUMENTS_ACCESS_KEY_ID": "documents-key",
                "AWS_DOCUMENTS_SECRET_ACCESS_KEY": "documents-secret",
            },
        )

        CoreConfig._validate_storage_credentials()

    def test_documents_credentials_left_to_the_fallback_are_valid(self, mocker: MockerFixture):
        """Supplying neither is the normal case: documents inherit the SBOMs pair."""
        mocker.patch.object(settings, "STORAGE_BACKEND", "s3")
        for bucket_type in ("MEDIA", "SBOMS", "DOCUMENTS"):
            mocker.patch.object(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "key")
            mocker.patch.object(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "secret")
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("AWS_DOCUMENTS_ACCESS_KEY_ID", "AWS_DOCUMENTS_SECRET_ACCESS_KEY")
        }
        mocker.patch.dict(os.environ, env, clear=True)

        CoreConfig._validate_storage_credentials()
