"""
Object Storage

Utilities for working with S3-compatible storage services.
Supports optional credentials to enable cloud workload identity (IRSA, Pod Identity, ADC).
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any, Literal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings


class ObjectStoreClient(ABC):
    """Base class for object storage backends."""

    @abstractmethod
    def put_object(self, bucket_name: str, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get_object(self, bucket_name: str, key: str) -> bytes | None: ...

    @abstractmethod
    def delete_object(self, bucket_name: str, key: str) -> None: ...

    @abstractmethod
    def list_objects(self, bucket_name: str, prefix: str) -> list[str]: ...

    @abstractmethod
    def upload_file(self, bucket_name: str, file_path: str, key: str) -> None: ...

    @abstractmethod
    def download_file(self, bucket_name: str, key: str, file_path: str) -> None: ...

    @abstractmethod
    def generate_presigned_url(
        self,
        bucket_name: str,
        key: str,
        expires_in: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str: ...


class S3ObjectStoreClient(ObjectStoreClient):
    """S3-compatible storage backend using boto3. Works with AWS S3, Cloudflare R2, and Minio."""

    def __init__(
        self,
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._boto3_kwargs: dict[str, Any] = {
            "region_name": region,
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            # Pin SigV4 rather than leaving it to be resolved. A presigned GET
            # that carries response-header overrides (the CRA bundle download)
            # is rejected with SignatureDoesNotMatch by SeaweedFS under the
            # default configuration and accepted when this is set, even though
            # the default already resolves to s3v4. Addressing style is left
            # alone deliberately: it makes no difference here, and forcing
            # path-style would break AWS buckets created after Sept 2020.
            "config": Config(signature_version="s3v4"),
        }
        self._resource: Any = boto3.resource("s3", **self._boto3_kwargs)
        self._client_instance: Any | None = None

    def __repr__(self) -> str:
        return (
            f"S3ObjectStoreClient(region={self._boto3_kwargs['region_name']!r}, "
            f"endpoint_url={self._boto3_kwargs['endpoint_url']!r})"
        )

    def put_object(self, bucket_name: str, key: str, data: bytes) -> None:
        self._resource.Bucket(bucket_name).put_object(Key=key, Body=data)

    def get_object(self, bucket_name: str, key: str) -> bytes | None:
        try:
            response = self._resource.Bucket(bucket_name).Object(key).get()
            return response["Body"].read()  # type: ignore[no-any-return]
        except ClientError as e:
            # Only a missing object is absence. "404" is checked alongside
            # "NoSuchKey" because non-AWS implementations (Minio, R2) report a
            # missing key by status code alone. A missing *bucket* reports
            # NoSuchBucket, so it still raises rather than reading as empty.
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise

    def delete_object(self, bucket_name: str, key: str) -> None:
        self._resource.Object(bucket_name, key).delete()

    def list_objects(self, bucket_name: str, prefix: str) -> list[str]:
        return [obj.key for obj in self._resource.Bucket(bucket_name).objects.filter(Prefix=prefix)]

    def upload_file(self, bucket_name: str, file_path: str, key: str) -> None:
        self._resource.Bucket(bucket_name).upload_file(file_path, key)

    def download_file(self, bucket_name: str, key: str, file_path: str) -> None:
        self._resource.Bucket(bucket_name).download_file(key, file_path)

    @property
    def _client(self) -> Any:
        # Not thread-safe: assumes instances are not shared across threads (per-request lifecycle).
        if self._client_instance is None:
            self._client_instance = boto3.client("s3", **self._boto3_kwargs)
        return self._client_instance

    def generate_presigned_url(
        self,
        bucket_name: str,
        key: str,
        expires_in: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        if expires_in <= 0:
            raise ValueError(f"expires_in must be positive, got {expires_in}")
        params: dict[str, str] = {"Bucket": bucket_name, "Key": key}
        # Response-header overrides (ResponseContentDisposition,
        # ResponseContentType) are signed into the URL, so callers that need a
        # download to arrive as an attachment rather than render inline can say
        # so without reaching past this class for a raw boto3 client.
        if response_headers:
            params.update(response_headers)
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        return url


_VALID_BUCKET_TYPES = ("MEDIA", "SBOMS", "DOCUMENTS")


def _create_store(bucket_type: Literal["MEDIA", "SBOMS", "DOCUMENTS"]) -> ObjectStoreClient:
    """Create a storage backend based on STORAGE_BACKEND setting."""
    if bucket_type not in _VALID_BUCKET_TYPES:
        raise ValueError(f"Invalid bucket_type: {bucket_type!r}. Must be one of {_VALID_BUCKET_TYPES}")

    if settings.STORAGE_BACKEND == "s3":
        return S3ObjectStoreClient(
            region=settings.AWS_REGION or None,
            endpoint_url=settings.AWS_ENDPOINT_URL_S3 or None,
            access_key=getattr(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", None) or None,
            secret_key=getattr(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", None) or None,
        )

    raise ValueError(f"Unsupported STORAGE_BACKEND: {settings.STORAGE_BACKEND!r}. Supported values: 's3'")


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

    def get_cached_aggregate(self, object_name: str) -> bytes | None:
        """Return a cached aggregated-SBOM blob by key, or None if absent (#998).

        Aggregated release/product SBOMs are expensive to build (O(N) member
        fetches). For public releases the result is content-addressed (the key
        embeds an artifact-set hash), so it is cached in the SBOMS bucket and
        served directly on repeat downloads. A missing key returns ``None``.
        """
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")
        return self.get_file_data(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, object_name)

    def put_cached_aggregate(self, object_name: str, data: bytes) -> None:
        """Store a built aggregated-SBOM blob under the given cache key (#998)."""
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")
        self.upload_data_as_file(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, object_name, data)

    def list_cached_aggregates(self, prefix: str) -> list[str]:
        """Return cached-aggregate object keys under ``prefix`` (for orphan GC)."""
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")
        return self._store.list_objects(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, prefix)

    def delete_cached_aggregate(self, object_name: str) -> None:
        """Delete one cached-aggregate object by key (for orphan GC)."""
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")
        self.delete_object(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, object_name)

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
        self._store.upload_file(bucket_name, file_path, object_name)

    def download_file(self, bucket_name: str, object_name: str, file_path: str) -> None:
        self._store.download_file(bucket_name, object_name, file_path)

    def get_file_data(self, bucket_name: str, file_path: str) -> bytes | None:
        return self._store.get_object(bucket_name, file_path)

    def delete_object(self, bucket_name: str, object_name: str) -> None:
        self._store.delete_object(bucket_name, object_name)

    def object_exists(self, bucket_name: str, object_name: str) -> bool:
        """Return whether an object is present, without fetching its body.

        Listing under the full key as prefix and matching exactly, rather than
        a HEAD, keeps this on the backend interface instead of requiring every
        backend to expose a boto3-shaped ``Object().load()``.
        """
        return object_name in self._store.list_objects(bucket_name, object_name)

    def generate_presigned_url(
        self,
        bucket_name: str,
        key: str,
        expires_in: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        return self._store.generate_presigned_url(bucket_name, key, expires_in, response_headers)
