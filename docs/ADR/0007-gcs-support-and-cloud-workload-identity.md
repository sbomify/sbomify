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

All object storage access is isolated in `sbomify/apps/core/object_store.py` (~100 lines). The `S3Client` class provides a small surface area for uploading, downloading, fetching, and deleting objects (including helpers that work with both raw data and files). No presigned URLs, multipart uploads, or streaming are used. Three separate bucket configurations exist: `AWS_MEDIA_*`, `AWS_SBOMS_*`, and `AWS_DOCUMENTS_*` (documents falls back to the sboms bucket if unset).

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

### 4. Testing with fake-gcs-server

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

- Define `ObjectStoreClient` base class in `object_store.py`
- Refactor `S3Client` to inherit from `ObjectStoreClient` without changing its public API
- Make S3 credentials optional (fall through to boto3 default chain when not set)
- Add `STORAGE_BACKEND` setting (default: `s3`)

### Phase 2: GCS Implementation

- Add `google-cloud-storage` as an optional dependency
- Implement `GCSObjectStoreClient` satisfying `ObjectStoreClient`
- Add `fake-gcs-server` to `docker-compose.tests.yml`
- Write tests covering GCS put/get/delete for all three bucket types

### Phase 3: Configuration and Documentation

- Add generic `STORAGE_*_BUCKET_NAME` settings with `AWS_*` fallbacks
- Document GCS setup (bucket creation, Workload Identity Federation binding)
- Document AWS keyless setup (IRSA / Pod Identity)
- Add example Kubernetes manifests for both clouds

## Consequences

### Positive

- **Eliminates static credentials on GCP**: Pods authenticate via Workload Identity — no keys to provision, store, or rotate.
- **Unlocks AWS workload identity**: Making credentials optional lets boto3 discover IRSA/Pod Identity tokens automatically. This is a security improvement for existing AWS deployments.
- **Reduced secret sprawl**: Up to six credential values (`ACCESS_KEY_ID` + `SECRET_ACCESS_KEY` × 3 buckets) can be eliminated entirely.
- **Smaller blast radius**: Short-lived, automatically-rotated tokens replace long-lived static keys.
- **Well-encapsulated change**: All storage access is isolated in `object_store.py` (~100 lines). The abstraction affects one file; callers are unchanged.
- **Backward compatible**: Existing S3 deployments with explicit credentials continue to work. The `STORAGE_BACKEND` defaults to `s3` and existing `AWS_*` settings are still respected.

### Negative / Tradeoffs

- **New dependency**: `google-cloud-storage` adds a dependency for GCS users. It should be an optional dependency so S3-only deployments are unaffected.
- **Testing surface**: GCS codepath requires its own test coverage with `fake-gcs-server`, adding a test service to Docker Compose.
- **Configuration complexity**: Two storage backends means two sets of configuration documentation, though the generic `STORAGE_*_BUCKET_NAME` settings reduce duplication.
- **Cloud-specific nuances**: GCS and S3 have subtly different consistency models, error codes, and rate limits. The abstraction must handle these differences without leaking cloud-specific details to callers.

## Alternatives Considered

### 1. GCS via S3-Compatible API with HMAC Keys

GCS exposes an S3-compatible endpoint (`storage.googleapis.com`) that works with boto3. Users would configure HMAC keys as `AWS_*_ACCESS_KEY_ID` / `AWS_*_SECRET_ACCESS_KEY`.

**Why rejected:** HMAC keys are static credentials — they have the same rotation burden and blast radius as AWS access keys. This defeats the purpose of Workload Identity. It also doesn't help AWS users who want keyless auth.

### 2. Abstract Storage via django-storages

[django-storages](https://django-storages.readthedocs.io/) supports S3, GCS, Azure, and more with a unified API. It integrates with Django's storage system — `FileField`, `default_storage`, and the `STORAGES` setting. When configured, any model field using `FileField` transparently routes uploads/downloads to the configured cloud backend.

django-storages does support workload identity for both clouds. GCS works with Application Default Credentials out of the box (the underlying `google-cloud-storage` library handles ADC). For AWS IRSA, boto3's default credential chain works correctly as long as no explicit credentials are set in django-storages settings — boto3 discovers `AWS_ROLE_ARN` + `AWS_WEB_IDENTITY_TOKEN_FILE` and uses `RefreshableCredentials` internally. A previously reported credential refresh bug ([django-storages #1493](https://github.com/jschneier/django-storages/issues/1493)) primarily affects chained role assumption or environments where temporary credentials are pre-resolved into environment variables, not standard IRSA/Pod Identity setups.

**Why rejected:** sbomify doesn't use Django's file storage API (`FileField`, `default_storage`). The `S3Client` is a thin, purpose-built wrapper (~100 lines) for direct bucket operations — `put_object`, `get`, `delete`. Adopting django-storages would require restructuring the storage layer to use Django's file API, adding a dependency that provides no benefit for sbomify's direct byte-level operations. There is also a maintenance concern — the last release was April 2025 and the most recent commits are from June 2025, meaning the project has seen no activity for ~9 months.

### 3. Unified Object Store via obstore

[obstore](https://github.com/developmentseed/obstore) is a Python library wrapping Apache Arrow's [`object_store`](https://github.com/apache/arrow-rs-object-store) Rust crate via PyO3. It provides a single API for S3, GCS, and Azure with native workload identity support for all three clouds.

#### What it does

obstore's API maps directly to sbomify's storage pattern:

```python
from obstore.store import S3Store, GCSStore

# S3 (also works with Minio)
store = S3Store(bucket="sbomify-sboms", region="us-east-1")

# GCS (picks up ADC / Workload Identity automatically)
store = GCSStore(bucket="sbomify-sboms")

# Same operations regardless of backend
store.put("path/to/object.json", data)
result = store.get("path/to/object.json")
content = result.bytes()
store.delete("path/to/object.json")
```

No separate client libraries needed — no boto3, no google-cloud-storage. The Rust layer handles authentication natively: IRSA/Pod Identity for AWS, ADC/Workload Identity Federation for GCP. Explicit credentials can still be passed for Minio or non-cloud environments.

#### Who is behind it

**[Development Seed](https://developmentseed.org/)** — a Washington DC-based geospatial and data engineering company founded in 2003. Their clients include NASA, UNICEF, USAID, and the World Bank. They have 500+ public GitHub repositories and open source is core to their business, not a side project.

#### The Rust foundation

The underlying `object_store` Rust crate is not experimental. It was originally developed by the InfluxData IOx team, then donated to the Apache Arrow project. It is used in production by InfluxDB, crates.io, and DataFusion. Apache Software Foundation governance. This is the same crate that powers the Rust data ecosystem's cloud storage layer.

obstore is a thin PyO3 wrapper over this crate. The heavy lifting — connection pooling, credential refresh, retry logic, multipart uploads — is all handled by battle-tested Rust code.

#### Maintenance and adoption

- **Release cadence**: ~16 releases in 18 months (Oct 2024 – Mar 2026). Latest: 0.9.2 (March 11, 2026)
- **PyPI downloads**: ~2.5 million/month
- **GitHub**: 717 stars, 31 forks, 41 open issues
- **Notable dependents**: NVIDIA's [multi-storage-client](https://github.com/NVIDIA/multi-storage-client), [Vortex](https://github.com/vortex-data/vortex) (2.8k stars), [icechunk](https://github.com/earth-mover/icechunk). The Zarr/xarray ecosystem is actively integrating it
- **Breaking changes** are purposeful and declining in scope — 0.9.0 only dropped Python 3.9 support

#### Caveats for sbomify

- **Sync vs async usage under ASGI.** obstore embeds its own Tokio runtime, so its sync API (`store.put()`, `store.get()`, etc.) is safe to call from synchronous code paths: Django sync views, management commands, and Dramatiq workers. sbomify is deployed as ASGI (Gunicorn + `UvicornWorker`), but Django runs sync views in a threadpool, so the sync API works from those views. However, do **not** call the sync API from within an async context (async Django views, ASGI middleware, startup/shutdown hooks) — use the async methods (`store.put_async()`, `store.get_async()`) there instead.
- **Instantiate once, not per-request.** Each store instance has its own connection pool. Create the store at module level or as a singleton — not per-request.
- **No presigned URL generation.** obstore focuses on data-plane operations. If sbomify ever needs presigned URLs, the provider's SDK (boto3 or google-cloud-storage) would be needed for that specific operation.
- **`obstore.Bytes` is not `bytes`.** `store.get(...).bytes()` returns an `obstore.Bytes` object, not Python `bytes`. It supports the buffer protocol (`memoryview`, `==` comparison with `bytes`) but `isinstance(data, bytes)` returns `False`. The wrapper class in `object_store.py` should call `bytes(data)` before returning, so the rest of the codebase never sees `obstore.Bytes`. This keeps the obstore dependency fully contained.
- **Pre-1.0 API.** Pin to `>=0.9,<0.10` and read the changelog on upgrades. The API appears to be converging — breaking changes between 0.8 and 0.9 were minimal.
- **Development uses Minio.** obstore supports S3-compatible endpoints via `endpoint` and `allow_http` options, so Minio works out of the box.
- **Chainguard distroless compatible.** Verified working in sbomify's Chainguard production image. The wheel is a single ~4MB `.so` that statically links all Rust dependencies including TLS (via rustls, not OpenSSL). No system library dependencies beyond glibc.

#### What this would look like for sbomify

Replacing the current `S3Client` with obstore would simplify `object_store.py` significantly — one implementation instead of maintaining separate S3 and GCS classes. The three-bucket model maps directly: create three store instances (media, sboms, documents) at module level, configured by `STORAGE_BACKEND` and bucket name settings. Adding Azure support in the future would be a configuration change, not a code change.

### 4. Other Storage Abstraction Libraries

Several Python libraries provide cloud storage abstractions:

- **[apache-libcloud](https://libcloud.apache.org/)**: Supports S3 and GCS but requires explicit key/secret at construction time — no native ADC or IRSA support.
- **[cloudpathlib](https://cloudpathlib.drivendata.org/)**: `pathlib`-style API (`S3Path`, `GSPath`). Delegates credentials to the underlying SDK. Designed for filesystem-like access patterns with local caching, not the in-memory byte operations sbomify uses.
- **[smart-open](https://github.com/piskvorky/smart_open)**: Streaming file-like interface for reading/writing. No delete operation. Designed for large file streaming, not blob put/get/delete.
- **[fsspec](https://filesystem-spec.readthedocs.io/) / gcsfs / s3fs**: Filesystem abstraction primarily used in the data science ecosystem (Dask, pandas). Heavier than needed for simple blob operations.

**Why rejected:** All of these target different use cases (filesystem abstractions, streaming, data science pipelines). None are a natural fit for sbomify's pattern of storing and retrieving raw bytes by key with simple put/get/delete operations.

### 5. Keep S3-Only, Document GCS HMAC Workaround

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
- [fake-gcs-server](https://github.com/fsouza/fake-gcs-server) — GCS emulator for testing
- [obstore](https://github.com/developmentseed/obstore) — Rust-backed unified object store for Python
- [Apache Arrow object_store Rust crate](https://github.com/apache/arrow-rs-object-store) — the foundation obstore wraps
