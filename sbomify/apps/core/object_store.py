"""
Object Storage

Utilities for working with S3-compatible storage services.
Supports optional credentials to enable cloud workload identity (IRSA, Pod Identity, ADC).
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Any, Literal

import boto3
from django.conf import settings

logger = logging.getLogger(__name__)


class ObjectStoreClient(ABC):
    """Base class for object storage backends."""

    @abstractmethod
    def put_object(self, bucket_name: str, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get_object(self, bucket_name: str, key: str) -> bytes | None: ...

    @abstractmethod
    def delete_object(self, bucket_name: str, key: str) -> None: ...

    @abstractmethod
    def upload_file(self, bucket_name: str, file_path: str, key: str) -> None: ...

    @abstractmethod
    def download_file(self, bucket_name: str, key: str, file_path: str) -> None: ...

    @abstractmethod
    def generate_presigned_url(self, bucket_name: str, key: str, expires_in: int = 3600) -> str: ...


class S3ObjectStoreClient(ObjectStoreClient):
    """S3-compatible storage backend using boto3. Works with AWS S3, Cloudflare R2, and Minio."""

    def __init__(
        self,
        region: str,
        endpoint_url: str,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        # When credentials are omitted, boto3 falls through to its default credential chain:
        # env vars, IRSA tokens, EKS Pod Identity, EC2 instance metadata, etc.
        self._resource: Any = boto3.resource(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key if access_key else None,
            aws_secret_access_key=secret_key if secret_key else None,
        )
        self._client: Any = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key if access_key else None,
            aws_secret_access_key=secret_key if secret_key else None,
        )

    def put_object(self, bucket_name: str, key: str, data: bytes) -> None:
        self._resource.Bucket(bucket_name).put_object(Key=key, Body=data)

    def get_object(self, bucket_name: str, key: str) -> bytes | None:
        response = self._resource.Bucket(bucket_name).Object(key).get()
        return response["Body"].read()  # type: ignore[no-any-return]

    def delete_object(self, bucket_name: str, key: str) -> None:
        self._resource.Object(bucket_name, key).delete()

    def upload_file(self, bucket_name: str, file_path: str, key: str) -> None:
        self._resource.Bucket(bucket_name).upload_file(file_path, key)

    def download_file(self, bucket_name: str, key: str, file_path: str) -> None:
        self._resource.Bucket(bucket_name).download_file(key, file_path)

    def generate_presigned_url(self, bucket_name: str, key: str, expires_in: int = 3600) -> str:
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )
        return url


def _create_store(bucket_type: str) -> ObjectStoreClient:
    """Create a storage backend based on STORAGE_BACKEND setting."""
    backend = settings.STORAGE_BACKEND

    if backend == "s3":
        access_key: str = getattr(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", "") or ""
        secret_key: str = getattr(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", "") or ""
        return S3ObjectStoreClient(
            region=settings.AWS_REGION,
            endpoint_url=settings.AWS_ENDPOINT_URL_S3,
            access_key=access_key or None,
            secret_key=secret_key or None,
        )

    raise ValueError(f"Unsupported STORAGE_BACKEND: {backend!r}. Supported values: 's3'")


class StorageClient:
    """Domain-level storage client. Delegates to an ObjectStoreClient backend."""

    def __init__(self, bucket_type: Literal["MEDIA", "SBOMS", "DOCUMENTS"]) -> None:
        self.bucket_type = bucket_type
        self._store: ObjectStoreClient = _create_store(bucket_type)

    def upload_data_as_file(self, bucket_name: str, object_name: str, data: bytes) -> None:
        self._store.put_object(bucket_name, object_name, data)

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
        self._store.upload_file(bucket_name, file_path, object_name)

    def download_file(self, bucket_name: str, object_name: str, file_path: str) -> None:
        self._store.download_file(bucket_name, object_name, file_path)

    def get_file_data(self, bucket_name: str, file_path: str) -> bytes | None:
        return self._store.get_object(bucket_name, file_path)

    def delete_object(self, bucket_name: str, object_name: str) -> None:
        self._store.delete_object(bucket_name, object_name)

    def generate_presigned_url(self, bucket_name: str, key: str, expires_in: int = 3600) -> str:
        return self._store.generate_presigned_url(bucket_name, key, expires_in)
