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
* A run's own object never spans runs, so reclaiming it is deleting a prefix.

**The findings array is shared.** Whole payloads never repeat: ``assessed_at``
and the scanner's metrics differ on every scan. The findings array is nearly all
of a payload's size, though, and a rescan of an unchanged SBOM reports the same
one, which is how a scanner polling every hour filled the table. The few fields
a scanner restamps on every poll (:data:`VOLATILE_FINDING_FIELDS`, EPSS) are
held per run instead, so the shared array only changes when the findings do. So an
offloaded payload is two objects: the run's own, holding everything but the
findings and naming them in ``findings_ref``, and one shared object per distinct
findings array under :data:`FINDINGS_PREFIX`, keyed by its hash. The row records
both keys, ``result_findings_key`` for the shared one, which is how the daily
sweep knows when no run needs a shared object any more.

A writer holds a shared PostgreSQL advisory lock from storing the findings
until its row names them. The collector takes the exclusive lock before checking
references and deleting an object. It can therefore only delete an unreferenced
object, even if DELETE succeeds and its response is lost. Outside a transaction
the lock belongs to the session, so the offload sweep does not hold a transaction
across storage calls. Inside one it lasts until commit or rollback, including an
outer transaction around a VEX rewrite.

Payloads are serialised with sorted keys and no whitespace, so the same result
dict always produces the same bytes and therefore the same key: re-running the
sweep over a row finds its object already stored instead of writing a second
one. ``verify_offloaded_results`` checks that each offloaded row's own object
and shared findings still exist; it does not re-hash the bytes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from sbomify.logging import getLogger

logger = getLogger(__name__)

#: Prefix for every offloaded result object. Results live in the SBOMS bucket
#: beside the cached release aggregates rather than in a bucket of their own:
#: same lifecycle, same credentials, no new deployment configuration to land
#: before the sweep can run anywhere.
RESULT_PREFIX = "assessment-results/"

#: Shared findings arrays, one object per distinct array. Under the result prefix
#: so the bucket layout stays one tree, and named so no run id can collide with it:
#: the per-run orphan sweep skips this segment, which is not a UUID.
FINDINGS_PREFIX = f"{RESULT_PREFIX}findings/"

#: The key in a run's own object that names its shared findings.
FINDINGS_REF = "findings_ref"

#: The key in a run's own object holding each finding's volatile fields, by position.
FINDINGS_VOLATILE = "findings_volatile"

#: Fields a scanner refreshes on every poll while the finding itself is unchanged.
#: Dependency Track restamps EPSS daily, so leaving these in the shared array
#: would make an unchanged SBOM's findings a new object every day. They stay
#: per run, beside the findings' reference, and are put back on read.
VOLATILE_FINDING_FIELDS = ("epss_score", "epss_percentile")


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


def findings_key_for(findings: bytes) -> str:
    """The shared key a serialised findings array belongs at."""
    return f"{FINDINGS_PREFIX}{hashlib.sha256(findings).hexdigest()}.json"


@dataclass(frozen=True)
class StoredResult:
    """Where :func:`put_split_result` stored a payload."""

    key: str
    findings_key: str = ""


@contextmanager
def _findings_lock(key: str, *, shared: bool = False) -> Iterator[None]:
    """Coordinate publication and collection without opening a transaction.

    In an existing transaction the reference is not visible until it commits,
    so use a transaction lock that outlives this context instead. Session locks
    are released on errors too; losing the connection releases them in Postgres.
    """
    from django.db import connection

    suffix = "_shared" if shared else ""
    transactional = connection.in_atomic_block
    scope = "xact_" if transactional else ""
    lock_name = f"assessment-findings:{key}"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT pg_advisory_{scope}lock{suffix}(hashtextextended(%s, 0))", [lock_name])
    try:
        yield
    finally:
        if not transactional:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT pg_advisory_unlock{suffix}(hashtextextended(%s, 0))", [lock_name])
            except BaseException:
                # Never return a session holding a lock to the connection pool.
                connection.close()
                raise


def ensure_findings_object(findings_key: str, findings: bytes) -> None:
    """Store a shared findings array unless it is already there. Idempotent: the key is its hash."""
    client = _client()
    if not client.object_exists(_bucket(), findings_key):
        client.upload_data_as_file(_bucket(), findings_key, findings)


@contextmanager
def put_split_result(run_id: Any, result: dict[str, Any]) -> Iterator[StoredResult]:
    """Store a payload as the run's own object plus its shared findings.

    The caller must write both keys to the row inside this context, so the
    collector cannot delete the findings before the reference is committed.
    A payload without a findings array is stored whole, with no shared key.
    """
    findings = result.get("findings")
    if not isinstance(findings, list):
        yield StoredResult(key=put_result(run_id, result))
        return

    stable: list[Any] = []
    volatile: list[dict[str, Any]] = []
    for finding in findings:
        if isinstance(finding, dict):
            stable.append({name: value for name, value in finding.items() if name not in VOLATILE_FINDING_FIELDS})
            volatile.append({name: finding[name] for name in VOLATILE_FINDING_FIELDS if name in finding})
        else:
            stable.append(finding)
            volatile.append({})

    findings_bytes = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    findings_key = findings_key_for(findings_bytes)
    remainder = {name: value for name, value in result.items() if name != "findings"}
    remainder[FINDINGS_REF] = findings_key
    if any(volatile):
        remainder[FINDINGS_VOLATILE] = volatile
    with _findings_lock(findings_key, shared=True):
        ensure_findings_object(findings_key, findings_bytes)
        yield StoredResult(key=put_result(run_id, remainder), findings_key=findings_key)


def get_findings(findings_key: str) -> list[Any]:
    """Read a shared findings array. Raises :class:`ResultObjectMissing` if it is gone."""
    raw = _client().get_file_data(_bucket(), findings_key)
    if raw is None:
        raise ResultObjectMissing(f"no object at {findings_key}")
    try:
        loaded = json.loads(raw)
    except ValueError as exc:
        raise ResultObjectMissing(f"object at {findings_key} is not JSON") from exc
    if not isinstance(loaded, list):
        raise ResultObjectMissing(f"object at {findings_key} is not a findings array")
    return loaded


def get_result(key: str) -> dict[str, Any]:
    """Read an offloaded payload back, with its shared findings put back in place.

    Raises :class:`ResultObjectMissing` when either object is absent or unusable,
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
    findings_key = loaded.pop(FINDINGS_REF, None)
    volatile = loaded.pop(FINDINGS_VOLATILE, None)
    if isinstance(findings_key, str) and "findings" not in loaded:
        findings = get_findings(findings_key)
        if isinstance(volatile, list) and len(volatile) == len(findings):
            findings = [
                {**finding, **fields} if isinstance(finding, dict) and isinstance(fields, dict) else finding
                for finding, fields in zip(findings, volatile, strict=True)
            ]
        loaded["findings"] = findings
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


def save_result(run: Any, result: dict[str, Any]) -> None:
    """Persist a rewritten result wherever the run's payload lives now.

    Where it lives is read from the row under its lock, the lock the offload
    sweep's UPDATE waits on before it can apply, never from the
    instance, which may predate an offload. Inline, it is the ordinary save,
    which keeps the summary columns in step. Offloaded, the rewrite is stored as
    a new object under the run's prefix and the row moves to its key, with the
    columns recomputed from the rewrite and the payload column emptied. A row
    that is gone stores nothing. The instance keeps the rewrite in memory, so a
    reader holding it, the finding projection, does not fetch it straight back.
    """
    from django.db import transaction

    model = type(run)
    with transaction.atomic():
        current_key = (
            model.objects.select_for_update().filter(pk=run.pk).values_list("result_object_key", flat=True).first()
        )
        if current_key is None:
            return
        run.result = result
        if not current_key:
            run.save(update_fields=["result"])
            return
        with put_split_result(run.id, result) as stored:
            run._populate_result_columns()
            model.objects.filter(pk=run.pk).update(
                result=None,
                result_object_key=stored.key,
                result_findings_key=stored.findings_key,
                result_summary=run.result_summary,
                result_skipped=run.result_skipped,
            )
            run.result_object_key = stored.key
            run.result_findings_key = stored.findings_key


def delete_result_object(key: str) -> None:
    """Remove one stored payload, for a revision no row ever pointed at."""
    _client().delete_object(_bucket(), key)


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


def delete_orphaned_result_objects(batch_size: int = 1000) -> int:
    """Remove stored payloads whose run is gone. Returns how many were deleted.

    Retention deletes a run's objects only after the row's deletion commits, so
    an object store error in between leaves them with nothing pointing at them,
    and a retry cannot find the row to try again. The key starts with the run
    id, so an id with no row marks an orphan. Every object is written for a row
    that already exists, so a live run's objects are never taken for one.

    The listing is streamed and checked against the table ``batch_size`` run
    ids at a time, so neither the keys nor the ids are ever all held at once.
    """
    client = _client()
    bucket = _bucket()
    deleted = 0
    pending: dict[uuid.UUID, list[str]] = {}
    for key in client.iter_cached_aggregates(RESULT_PREFIX):
        try:
            run_id = uuid.UUID(key[len(RESULT_PREFIX) :].split("/", 1)[0])
        except ValueError:
            continue
        if run_id not in pending and len(pending) >= batch_size:
            deleted += _delete_orphans(client, bucket, pending)
            pending = {}
        pending.setdefault(run_id, []).append(key)
    deleted += _delete_orphans(client, bucket, pending)
    if deleted:
        logger.info(f"[RESULT_STORE] deleted {deleted} orphaned result objects")
    return deleted


def delete_unreferenced_findings_objects(batch_size: int = 500) -> int:
    """Remove shared findings arrays no run names any more. Returns how many were deleted.

    The batch lookup is an optimisation only. Before deleting a candidate,
    take its exclusive lock and recheck references: a writer may have named it
    since the batch was read. No referenced object is deleted or needs repair.
    """
    from sbomify.apps.plugins.models import AssessmentRun

    client = _client()
    bucket = _bucket()
    deleted = 0

    def sweep(keys: list[str]) -> int:
        named = set(
            AssessmentRun.objects.filter(result_findings_key__in=keys)
            .order_by()
            .values_list("result_findings_key", flat=True)
            .distinct()
        )
        removed = 0
        for key in keys:
            if key in named:
                continue
            with _findings_lock(key):
                if AssessmentRun.objects.filter(result_findings_key=key).exists():
                    continue
                client.delete_object(bucket, key)
                removed += 1
        return removed

    pending: list[str] = []
    for key in client.iter_cached_aggregates(FINDINGS_PREFIX):
        pending.append(key)
        if len(pending) >= batch_size:
            deleted += sweep(pending)
            pending = []
    if pending:
        deleted += sweep(pending)
    if deleted:
        logger.info(f"[RESULT_STORE] deleted {deleted} unreferenced shared findings objects")
    return deleted


def _delete_orphans(client: Any, bucket: str, keys_by_run: dict[uuid.UUID, list[str]]) -> int:
    from sbomify.apps.plugins.models import AssessmentRun

    if not keys_by_run:
        return 0
    live = set(AssessmentRun.objects.filter(id__in=list(keys_by_run)).values_list("id", flat=True))
    orphaned = [key for run_id, keys in keys_by_run.items() if run_id not in live for key in keys]
    for key in orphaned:
        client.delete_object(bucket, key)
    return len(orphaned)
