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
