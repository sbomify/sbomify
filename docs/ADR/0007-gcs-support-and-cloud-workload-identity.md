# 7. GCS Support and Cloud Workload Identity

Date: 2026-03-29

## Status

Proposed

## Context

sbomify currently requires static, long-lived credentials for object storage. The `S3Client` in `object_store.py` passes explicit `aws_access_key_id` and `aws_secret_access_key` to `boto3.resource()`, bypassing boto3's default credential chain. This has two consequences:

1. **No native GCP support.** Users deploying sbomify on Google Cloud Platform cannot use Google Cloud Storage (GCS) as their object store. GCS offers an S3-compatible API via HMAC keys, but HMAC keys are static credentials — they defeat the purpose of GCP's keyless authentication model.

2. **AWS workload identity is blocked.** Even on AWS, passing explicit credentials prevents boto3 from discovering IAM credentials automatically. AWS users on EKS with IRSA (IAM Roles for Service Accounts) or Pod Identity cannot use keyless authentication because the explicit credentials take precedence over the default credential chain.

Static credentials are a security and operational concern:

- **Rotation burden**: Keys must be manually rotated on a schedule. Missed rotations create compliance gaps.
- **Blast radius**: A leaked static key grants access until revoked. Workload identity tokens are short-lived (typically 1 hour) and automatically rotated.
- **Secret sprawl**: sbomify requires up to six credential values (`ACCESS_KEY_ID` + `SECRET_ACCESS_KEY` for each of the three buckets: media, sboms, documents), all of which must be provisioned and stored securely.

Cloud providers have converged on workload identity as the standard for service-to-service authentication:

| Cloud | Mechanism | How it works |
|---|---|---|
| **GCP** | Workload Identity Federation | Kubernetes service account is mapped to a GCP service account; pods receive short-lived tokens via Application Default Credentials (ADC) |
| **AWS** | IRSA / EKS Pod Identity | IAM role is associated with a Kubernetes service account; projected service account tokens are exchanged for temporary AWS credentials |

Both mechanisms eliminate static credentials entirely. The application authenticates using its runtime identity rather than a pre-provisioned secret.

### Current Storage Architecture

All object storage access is isolated in `sbomify/apps/core/object_store.py` (~100 lines). The `S3Client` class provides a small surface area for uploading, downloading, fetching, and deleting objects (including helpers that work with both raw data and files). Three separate bucket configurations exist: `AWS_MEDIA_*`, `AWS_SBOMS_*`, and `AWS_DOCUMENTS_*` (documents falls back to the sboms bucket if unset).

**Production backend:** sbomify uses [Cloudflare R2](https://developers.cloudflare.com/r2/) as its production object store. R2 is S3-compatible, so the existing `S3Client` with boto3 works unchanged. Development uses Minio.

**Presigned URLs:** The CRA export download flow (`compliance/services/export_service.py`) uses S3 presigned URLs to generate time-limited download links. However, this is implemented outside `S3Client` — `get_download_url()` constructs a separate `boto3.client()` with hardcoded credentials and calls `generate_presigned_url()` directly. This works for S3 and R2 (which supports S3 presigned URLs identically) but would not work for GCS without modification.

Note: The Django signed-token system used for SBOM/document downloads (`/api/v1/sboms/{id}/download?token=...`) is application-level auth that calls `S3Client.get_file_data()` to fetch bytes server-side — it is not a storage-layer concern and is unaffected by this ADR.

## Decision

**Add native Google Cloud Storage support and make S3 credentials optional to enable cloud workload identity on both GCP and AWS.**

### 1. Storage Backend Abstraction

Extract the common storage operations into a base class that both the existing S3 implementation and a new GCS implementation inherit from:

```python
class ObjectStoreClient:
    """Base class for object storage backends."""

    def put_object(self, bucket_name: str, key: str, data: bytes) -> None: ...
    def get_object(self, bucket_name: str, key: str) -> bytes | None: ...
    def delete_object(self, bucket_name: str, key: str) -> None: ...
    def upload_file(self, bucket_name: str, file_path: str, key: str) -> None: ...
    def download_file(self, bucket_name: str, key: str, file_path: str) -> None: ...
    def generate_presigned_url(self, bucket_name: str, key: str, expires_in: int = 3600) -> str: ...

class S3ObjectStoreClient(ObjectStoreClient): ...
class GCSObjectStoreClient(ObjectStoreClient): ...
```

A configuration flag (`STORAGE_BACKEND=s3|gcs`, defaulting to `s3`) selects which concrete class to instantiate. The existing `S3Client` public API remains unchanged — the abstraction is introduced beneath it so callers are unaffected.

### 2. Native GCS Implementation

The GCS backend uses the `google-cloud-storage` Python library, which picks up Application Default Credentials automatically on GKE:

| Current S3 call | GCS equivalent |
|---|---|
| `bucket.put_object(Key=key, Body=data)` | `bucket.blob(key).upload_from_string(data)` |
| `.Object(key).get()["Body"].read()` | `bucket.blob(key).download_as_bytes()` |
| `.Object(key).delete()` | `bucket.blob(key).delete()` |
| `bucket.upload_file(path, key)` | `bucket.blob(key).upload_from_filename(path)` |
| `bucket.download_file(key, path)` | `bucket.blob(key).download_to_filename(path)` |

The three-bucket model (media, sboms, documents) maps directly to GCS buckets. Bucket names are configured via the existing `AWS_*_STORAGE_BUCKET_NAME` settings (renamed to generic `STORAGE_*_BUCKET_NAME` with the `AWS_*` names kept as fallbacks for backward compatibility).

### 3. S3 Credentials for AWS Workload Identity

Make the `aws_access_key_id` and `aws_secret_access_key` parameters optional when constructing the boto3 resource. When credentials are not provided, boto3 falls through to its default credential chain, which automatically discovers:

- IRSA projected service account tokens on EKS
- EKS Pod Identity credentials
- EC2 instance metadata credentials
- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

This is a one-line change per credential parameter (pass `None` instead of raising when the setting is missing), but it unlocks keyless authentication for every AWS deployment pattern.

### 4. Presigned URL Consolidation

The `get_download_url()` function in `export_service.py` currently bypasses `S3Client` and constructs its own `boto3.client()` to call `generate_presigned_url()`. This must be consolidated into the storage client abstraction so that:

- S3/R2 presigned URLs continue to work via `boto3.client.generate_presigned_url()`
- GCS signed URLs are supported via `google-cloud-storage`'s `blob.generate_signed_url()`

**GCS signed URL complexity:** With Workload Identity, GCS signed URLs require an extra step. The pod's ADC credentials cannot sign URLs directly — they must use `impersonated_credentials` to call the IAM SignBlob API on behalf of a service account. This means the GCS implementation needs the target service account email as configuration, and the service account must have the `iam.serviceAccountTokenCreator` role. This is more complex than S3/R2 where presigned URLs work with any valid credential.

### 5. Testing with fake-gcs-server

[`fake-gcs-server`](https://github.com/fsouza/fake-gcs-server) is a mature, Docker-based GCS emulator. The `google-cloud-storage` Python client supports it natively:

```python
os.environ["STORAGE_EMULATOR_HOST"] = "http://fake-gcs:4443"
client = storage.Client(credentials=AnonymousCredentials(), project="test")
```

This fits into the existing `docker-compose.tests.yml` alongside PostgreSQL, Redis, and Minio:

```yaml
fake-gcs:
  image: fsouza/fake-gcs-server
  command: ["-scheme", "http"]
  ports:
    - "4443:4443"
```

## Migration Strategy

### Phase 1: Backend Abstraction

- Define `ObjectStoreClient` base class in `object_store.py` with `generate_presigned_url()` in the interface
- Refactor `S3Client` to inherit from `ObjectStoreClient` without changing its public API
- Consolidate the presigned URL logic from `export_service.py` into `S3Client.generate_presigned_url()`
- Make S3 credentials optional (fall through to boto3 default chain when not set)
- Add `STORAGE_BACKEND` setting (default: `s3`)

### Phase 2: GCS Implementation

- Add `google-cloud-storage` as an optional dependency
- Implement `GCSObjectStoreClient` satisfying `ObjectStoreClient`
- Implement GCS signed URLs with `impersonated_credentials` for Workload Identity environments
- Add `fake-gcs-server` to `docker-compose.tests.yml`
- Write tests covering GCS put/get/delete/presigned-url for all three bucket types

### Phase 3: Configuration and Documentation

- Add generic `STORAGE_*_BUCKET_NAME` settings with `AWS_*` fallbacks
- Document GCS setup (bucket creation, Workload Identity Federation binding, service account for signed URLs)
- Document AWS keyless setup (IRSA / Pod Identity)
- Add example Kubernetes manifests for both clouds

## Consequences

### Positive

- **Eliminates static credentials on GCP**: Pods authenticate via Workload Identity — no keys to provision, store, or rotate.
- **Unlocks AWS workload identity**: Making credentials optional lets boto3 discover IRSA/Pod Identity tokens automatically. This is a security improvement for existing AWS deployments.
- **Reduced secret sprawl**: Up to six credential values (`ACCESS_KEY_ID` + `SECRET_ACCESS_KEY` × 3 buckets) can be eliminated entirely.
- **Smaller blast radius**: Short-lived, automatically-rotated tokens replace long-lived static keys.
- **Well-encapsulated change**: All storage access is isolated in `object_store.py` (~100 lines). The abstraction affects one file; callers are unchanged.
- **Backward compatible**: Existing S3/R2 deployments with explicit credentials continue to work. The `STORAGE_BACKEND` defaults to `s3` and existing `AWS_*` settings are still respected.
- **Presigned URLs consolidated**: Moving presigned URL generation into the storage client eliminates the ad-hoc boto3 client in `export_service.py` and ensures it works across all backends.

### Negative / Tradeoffs

- **New dependency**: `google-cloud-storage` adds a dependency for GCS users. It should be an optional dependency so S3-only deployments are unaffected.
- **Testing surface**: GCS codepath requires its own test coverage with `fake-gcs-server`, adding a test service to Docker Compose.
- **Configuration complexity**: Two storage backends means two sets of configuration documentation, though the generic `STORAGE_*_BUCKET_NAME` settings reduce duplication.
- **Cloud-specific nuances**: GCS and S3 have subtly different consistency models, error codes, and rate limits. The abstraction must handle these differences without leaking cloud-specific details to callers.
- **GCS signed URL complexity**: Workload Identity environments require `impersonated_credentials` + IAM SignBlob, adding configuration (service account email) and IAM setup that S3/R2 presigned URLs don't need.

## Alternatives Considered

### Comparison Table

| Library | S3/R2 | GCS | Workload Identity | Presigned URLs | Fit for sbomify |
|---|---|---|---|---|---|
| **boto3 + google-cloud-storage** | Yes | Yes | Yes | Yes | Best fit — matches current stack |
| **obstore** | Yes | Yes | Yes | No | Missing presigned URLs |
| **django-storages** | Yes | Yes | Yes | Yes | Doesn't fit sbomify's storage pattern |
| apache-libcloud | Yes | Yes | No | ? | No workload identity |
| cloudpathlib | Yes | Yes | Yes | No | Filesystem API, not blob ops |
| smart-open | Yes | Yes | Yes | No | Streaming API, no delete |
| fsspec / gcsfs / s3fs | Yes | Yes | Yes | No | Data science, heavyweight |

### 1. GCS via S3-Compatible API with HMAC Keys

GCS exposes an S3-compatible endpoint (`storage.googleapis.com`) that works with boto3. Users would configure HMAC keys as `AWS_*_ACCESS_KEY_ID` / `AWS_*_SECRET_ACCESS_KEY`.

**Why rejected:** HMAC keys are static credentials — they have the same rotation burden and blast radius as AWS access keys. This defeats the purpose of Workload Identity. It also doesn't help AWS users who want keyless auth.

### 2. Abstract Storage via django-storages

[django-storages](https://django-storages.readthedocs.io/) supports S3, GCS, Azure, and more with a unified API. It integrates with Django's storage system — `FileField`, `default_storage`, and the `STORAGES` setting. It does support workload identity for both clouds and presigned URLs.

**Why rejected:** sbomify doesn't use Django's file storage API (`FileField`, `default_storage`). The `S3Client` is a thin, purpose-built wrapper (~100 lines) for direct bucket operations — `put_object`, `get`, `delete`. Adopting django-storages would require restructuring the storage layer to use Django's file API, adding a dependency that provides no benefit for sbomify's direct byte-level operations. There is also a maintenance concern — the last release was April 2025 and the most recent commits are from June 2025, meaning the project has seen no activity for ~9 months.

### 3. Unified Object Store via obstore

[obstore](https://github.com/developmentseed/obstore) is a Python library wrapping Apache Arrow's [`object_store`](https://github.com/apache/arrow-rs-object-store) Rust crate via PyO3. It provides a single API for S3, GCS, and Azure with native workload identity support for all three clouds.

obstore's API maps directly to sbomify's storage pattern:

```python
from obstore.store import S3Store, GCSStore

# S3 (also works with Minio and R2)
store = S3Store(bucket="sbomify-sboms", region="us-east-1")

# GCS (picks up ADC / Workload Identity automatically)
store = GCSStore(bucket="sbomify-sboms")

# Same operations regardless of backend
store.put("path/to/object.json", data)
result = store.get("path/to/object.json")
content = result.bytes()
store.delete("path/to/object.json")
```

The underlying `object_store` Rust crate is production-grade — originally developed by the InfluxData IOx team, then donated to the Apache Arrow project. obstore has ~2.5M PyPI downloads/month and a regular release cadence (~16 releases in 18 months).[^obstore]

**Key caveat:** obstore does not support presigned URL generation — it focuses on data-plane operations (put/get/delete). Since sbomify uses presigned URLs for CRA export downloads, obstore cannot be the sole storage dependency. Using both obstore (for data operations) + boto3/google-cloud-storage (for presigned URLs) adds complexity without clear benefit over just using boto3 + google-cloud-storage directly.

[^obstore]: Maintained by [Development Seed](https://developmentseed.org/), backed by the Apache Arrow `object_store` Rust crate (used in production by InfluxDB, crates.io, DataFusion). Compatible with sbomify's Chainguard distroless image. Pre-1.0 API — pin to `>=0.9,<0.10`.

### 4. Keep S3-Only, Document GCS HMAC Workaround

Document how to use GCS's S3-compatible API with HMAC keys as a workaround for GCP users.

**Why rejected:** While low-effort, this locks GCP users into static credentials and doesn't address the core security concern. It also doesn't help AWS users who want workload identity support.

## Relationship to Other ADRs

- **ADR-004 (Immutable Security Artifacts)**: The storage backend abstraction does not affect artifact immutability. Both S3 and GCS backends store and retrieve bytes identically — artifacts remain unchanged regardless of the underlying storage service.

## References

- [GitHub Issue #811: Support Google Cloud Platform (GCS) with Application Default Credentials](https://github.com/sbomify/sbomify/issues/811)
- [GCP Workload Identity Federation](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
- [AWS IRSA (IAM Roles for Service Accounts)](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [AWS EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [google-cloud-storage Python library](https://cloud.google.com/python/docs/reference/storage/latest)
- [Cloudflare R2](https://developers.cloudflare.com/r2/) — sbomify's production object store
- [fake-gcs-server](https://github.com/fsouza/fake-gcs-server) — GCS emulator for testing
- [obstore](https://github.com/developmentseed/obstore) — Rust-backed unified object store for Python
- [Apache Arrow object_store Rust crate](https://github.com/apache/arrow-rs-object-store) — the foundation obstore wraps
