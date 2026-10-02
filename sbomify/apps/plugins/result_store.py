"""Object storage for assessment result payloads.

``AssessmentRun.result`` is a document, not a queryable value: multiple MB of
scanner output, read on demand, never grouped or filtered on by the database. The
small slices anything aggregates over were denormalised into ``result_summary``
and ``result_skipped`` precisely so readers would stop touching it.

Every other document in this system already lives in object storage: ingested
SBOMs, uploaded documents, VEX artifacts, signatures, and generated artifacts
including the cached release aggregates. This module is the same treatment for
the one that did not.

**Keys are content-addressed under the run's own prefix**, mirroring
``StorageClient._upload_sbom_artifact``, which names an SBOM's artifacts
``<sbom_id>/<hash><suffix>``. Two properties follow from that shape and both
matter:

* A rewritten result (the VEX re-annotation path) hashes differently and lands
  as a new object. Nothing is ever overwritten, so the bytes an object holds
  always match the hash it is named for, and an old revision stays readable and
  verifiable.
* Objects never span runs, so reclaiming one is deleting a prefix. Sharing
  identical payloads between runs would have been the other option, and it does
  not pay here: ``AssessmentResult.assessed_at`` is a per-run timestamp inside
  the payload, so two otherwise identical scans an hour apart differ in their
  bytes and would not share an object anyway.

Payloads are serialised with sorted keys and no whitespace, so the same result
dict always produces the same bytes and therefore the same key. Do not change
that without reading ``verify_offloaded_results``: the hash in the key is what
that command checks the payload against.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.conf import settings

from sbomify.logging import getLogger

logger = getLogger(__name__)

#: Prefix for every offloaded result object. Results live in the SBOMS bucket
#: beside the cached release aggregates rather than in a bucket of their own:
#: same lifecycle, same credentials, no new deployment configuration to land
#: before the sweep can run anywhere.
RESULT_PREFIX = "assessment-results/"


class ResultObjectMissing(RuntimeError):
    """An offloaded payload could not be read back.

    Raised rather than returning ``None`` because the two are not the same
    answer, and confusing them is the worst failure this design can have: a run
    whose payload is unreachable must never read as a run that found nothing.
    "No vulnerabilities" and "we cannot show you what was found" are different
    claims about a customer's software.

    Callers on a rendering path should catch this and say so. The counts they
    show do not depend on it: ``result_summary`` stays in the database, so a
    missing object costs the findings list and nothing else.
    """


def serialise_result(result: dict[str, Any]) -> bytes:
    """Canonical bytes for a result payload.

    Sorted keys and no whitespace, so the same dict always hashes to the same
    key and re-running the sweep over a row it has already done is a no-op
    rather than a second object.
    """
    return json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")


def object_key_for(run_id: Any, payload: bytes) -> str:
    """The key a payload belongs at, for a given run."""
    return f"{RESULT_PREFIX}{run_id}/{hashlib.sha256(payload).hexdigest()}.json"


def _client() -> Any:
    from sbomify.apps.core.object_store import StorageClient

    return StorageClient("SBOMS")


def _bucket() -> str:
    return str(settings.AWS_SBOMS_STORAGE_BUCKET_NAME)


def put_result(run_id: Any, result: dict[str, Any]) -> str:
    """Store a result payload and return its key. Idempotent.

    The existence check is not only an optimisation: it is what makes the sweep
    safe to interrupt and re-run at any point. A key already present holds the
    same bytes by construction, because the key is their hash.
    """
    payload = serialise_result(result)
    key = object_key_for(run_id, payload)
    client = _client()
    if client.object_exists(_bucket(), key):
        return key
    client.upload_data_as_file(_bucket(), key, payload)
    return key


def get_result(key: str) -> dict[str, Any]:
    """Read an offloaded payload back.

    Raises :class:`ResultObjectMissing` when the object is absent or unusable,
    never returning an empty result for it.
    """
    raw = _client().get_file_data(_bucket(), key)
    if raw is None:
        raise ResultObjectMissing(f"no object at {key}")
    try:
        loaded = json.loads(raw)
    except ValueError as exc:
        raise ResultObjectMissing(f"object at {key} is not JSON") from exc
    if not isinstance(loaded, dict):
        raise ResultObjectMissing(f"object at {key} is not a result object")
    return loaded


def result_object_exists(key: str) -> bool:
    """Whether an offloaded payload is still readable, without fetching it."""
    return bool(_client().object_exists(_bucket(), key))


def load_result(run: Any) -> dict[str, Any] | None:
    """The run's result, wherever it currently lives.

    ``None`` means the run has no result — it is pending, or it failed before
    producing one. An offloaded payload that cannot be read raises
    :class:`ResultObjectMissing` instead, so the two stay distinguishable.

    This is deliberately an explicit call rather than a property on the model.
    Reading a result can now be a network round trip, and a transparent
    attribute would let a loop over a queryset become one request per row
    without anything in the code saying so. Every S3 read should be visible at
    its call site.
    """
    inline = getattr(run, "result", None)
    if inline is not None:
        return inline if isinstance(inline, dict) else None
    key = getattr(run, "result_object_key", "") or ""
    if not key:
        return None
    return get_result(key)


def delete_result_objects(run_id: Any) -> int:
    """Remove every stored payload for a run. Returns how many were deleted.

    By prefix rather than by key, because a run that was re-annotated after
    being offloaded has more than one revision stored and the row only records
    the current one. Nothing else can reference these objects: the prefix is the
    run id.
    """
    client = _client()
    bucket = _bucket()
    keys = client.list_cached_aggregates(f"{RESULT_PREFIX}{run_id}/")
    for key in keys:
        client.delete_object(bucket, key)
    return len(keys)
