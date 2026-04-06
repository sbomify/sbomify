"""
S3 Compatible Storage

Utilities for working with S3 compatible storage services.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

import boto3
from botocore.exceptions import ClientError
from django.conf import settings


class S3Client:
    def __init__(self, bucket_type: Literal["MEDIA", "SBOMS", "DOCUMENTS"]) -> None:
        self.bucket_type = bucket_type
        access_key: str = getattr(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID")
        secret_key: str = getattr(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY")
        self.s3: Any = boto3.resource(
            "s3",
            region_name=settings.AWS_REGION,
            endpoint_url=settings.AWS_ENDPOINT_URL_S3,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def upload_data_as_file(self, bucket_name: str, object_name: str, data: bytes) -> None:
        try:
            self.s3.Bucket(bucket_name).put_object(Key=object_name, Body=data)
        except ClientError as e:
            print(e)  # noqa F821
            raise

    def upload_media(self, object_name: str, data: bytes) -> None:
        if self.bucket_type != "MEDIA":
            raise ValueError("This method is only for MEDIA bucket")

        self.upload_data_as_file(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, object_name, data)

    def upload_sbom(self, data: bytes) -> str:
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")

        object_name = hashlib.sha256(data).hexdigest() + ".json"
        self.upload_data_as_file(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, object_name, data)

        return object_name

    def get_sbom_data(self, object_name: str) -> bytes | None:
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")

        return self.get_file_data(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, object_name)

    _HEX_SHA256_RE = re.compile(r"[a-f0-9]{64}\Z")

    def _upload_sbom_artifact(self, sbom_id: str, sbom_hash: str, data: bytes, suffix: str) -> str:
        """Upload an artifact associated with an SBOM. Named: <sbom_id>/<hash><suffix>"""
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")
        if not self._HEX_SHA256_RE.fullmatch(sbom_hash):
            raise ValueError(f"Invalid SHA-256 hash: {sbom_hash!r}")
        object_name = f"{sbom_id}/{sbom_hash}{suffix}"
        self.upload_data_as_file(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, object_name, data)
        return object_name

    def upload_sbom_signature(self, sbom_id: str, sbom_hash: str, data: bytes) -> str:
        """Upload a signature blob for an SBOM."""
        return self._upload_sbom_artifact(sbom_id, sbom_hash, data, ".sig")

    def upload_sbom_provenance(self, sbom_id: str, sbom_hash: str, data: bytes) -> str:
        """Upload a provenance attestation for an SBOM."""
        return self._upload_sbom_artifact(sbom_id, sbom_hash, data, ".provenance.json")

    def upload_document(self, data: bytes) -> str:
        if self.bucket_type != "DOCUMENTS":
            raise ValueError("This method is only for DOCUMENTS bucket")

        object_name = hashlib.sha256(data).hexdigest() + ".bin"
        self.upload_data_as_file(settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, object_name, data)

        return object_name

    def get_document_data(self, object_name: str) -> bytes | None:
        if self.bucket_type != "DOCUMENTS":
            raise ValueError("This method is only for DOCUMENTS bucket")

        return self.get_file_data(settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, object_name)

    def upload_file(self, bucket_name: str, file_path: str, object_name: str) -> None:
        try:
            self.s3.Bucket(bucket_name).upload_file(file_path, object_name)
        except ClientError as e:
            print(e)  # noqa F821
            raise

    def download_file(self, bucket_name: str, object_name: str, file_path: str) -> None:
        try:
            self.s3.Bucket(bucket_name).download_file(object_name, file_path)
        except ClientError as e:
            print(e)  # noqa F821
            raise

    def get_file_data(self, bucket_name: str, file_path: str) -> bytes | None:
        try:
            response = self.s3.Bucket(bucket_name).Object(file_path).get()
            if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
                return response["Body"].read()  # type: ignore[no-any-return]
            else:
                return None
        except ClientError as e:
            print(e)  # noqa F821
            raise

    def delete_object(self, bucket_name: str, object_name: str) -> None:
        try:
            self.s3.Object(bucket_name, object_name).delete()
        except ClientError as e:
            print(e)  # noqa F821
            raise
