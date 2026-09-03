"""Compact response shaping for MCP tools.

Hand-shaping output is the main reason these tools exist rather than an
auto-generated wrapper over the REST API. The REST schemas are built for a web
UI that renders whatever it is given; an agent pays context tokens for every
field it is handed and reasons worse when buried in irrelevant ones.

Rules applied here:

* Omit nulls and empty collections rather than emitting ``"field": null``.
* Emit dates as plain ISO-8601 strings.
* Never inline artifact bodies — return identifiers the agent can fetch.
* Every list is wrapped by ``paginated()`` so the agent always knows whether it
  is seeing everything.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from .limits import untrusted

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from sbomify.apps.core.models import Release, ReleaseArtifact
    from sbomify.apps.documents.models import Document
    from sbomify.apps.sboms.models import SBOM, Component, Product


def _stamp(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def compact(data: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is ``None`` or an empty list/dict/string."""
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def paginated(items: list[Any], *, page: int, page_size: int, total: int) -> dict[str, Any]:
    """Wrap a page of results with the counts an agent needs to decide next steps."""
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
    }


def page_queryset(queryset: QuerySet[Any], page: int, page_size: int) -> tuple[list[Any], int]:
    """Slice ``queryset`` for ``page``, returning the rows and the total count."""
    total = queryset.count()
    start = (page - 1) * page_size
    return list(queryset[start : start + page_size]), total


def product(obj: Product, *, detail: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": obj.id,
        "name": obj.name,
        "is_public": obj.is_public,
        "created_at": _stamp(obj.created_at),
    }
    if detail:
        data |= {
            "description": obj.description,
            "release_date": _stamp(obj.release_date),
            "end_of_support": _stamp(obj.end_of_support),
            "end_of_life": _stamp(obj.end_of_life),
        }
    return compact(data)


def component(obj: Component, *, detail: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": obj.id,
        "name": obj.name,
        "type": obj.component_type,
        "visibility": obj.visibility,
        "created_at": _stamp(obj.created_at),
    }
    if detail:
        data |= {
            "is_global": obj.is_global,
            "supplier_name": obj.supplier_name,
            "lifecycle_phase": obj.lifecycle_phase,
            "release_date": _stamp(obj.release_date),
            "end_of_support": _stamp(obj.end_of_support),
            "end_of_life": _stamp(obj.end_of_life),
        }
    return compact(data)


def release(obj: Release, *, detail: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": obj.id,
        "name": obj.name,
        "version": obj.version,
        "product_id": obj.product_id,
        "is_latest": obj.is_latest,
        "is_prerelease": obj.is_prerelease,
        "created_at": _stamp(obj.created_at),
    }
    if detail:
        data |= {
            "description": obj.description,
            "released_at": _stamp(obj.released_at),
        }
    return compact(data)


def sbom(obj: SBOM, *, detail: bool = False) -> dict[str, Any]:
    """SBOM *metadata* only.

    The document itself can hold tens of thousands of packages; it is never
    inlined. Agents reach package data through ``get_sbom_packages``, which
    filters and paginates.
    """
    data: dict[str, Any] = {
        "id": obj.id,
        # name and version are lifted verbatim out of the uploaded document
        # (metadata.component.* / the SPDX document name), so they are as
        # supplier-controlled as a package name and bounded the same way.
        "name": untrusted(obj.name, limit=256),
        "version": untrusted(obj.version, limit=128),
        "format": obj.format,
        "format_version": obj.format_version,
        "bom_type": obj.bom_type,
        "component_id": obj.component_id,
        "created_at": _stamp(obj.created_at),
    }
    if detail:
        data |= {
            "filename": obj.sbom_filename,
            "source": obj.source,
            "sha256": obj.sha256_hash,
            "has_crypto_assets": obj.has_crypto_assets,
            "is_signed": bool(obj.signature_url or obj.signature_blob_key),
        }
    return compact(data)


def document(obj: Document, *, detail: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": obj.id,
        # Supplied by the uploader alongside the file, not typed into the app —
        # bounded like every other artifact-adjacent string.
        "name": untrusted(obj.name, limit=256),
        "version": untrusted(obj.version, limit=128),
        "type": obj.document_type,
        "component_id": obj.component_id,
        "created_at": _stamp(obj.created_at),
    }
    if detail:
        data |= {
            "description": untrusted(obj.description, limit=2000),
            "filename": untrusted(obj.document_filename, limit=256),
            "content_type": obj.content_type,
            "file_size": obj.file_size,
            "sha256": obj.sha256_hash,
        }
    return compact(data)


def release_artifact(obj: ReleaseArtifact) -> dict[str, Any]:
    # No "artifact_id": obj.id is the release-artifact junction row's own pk,
    # which no tool accepts as input — emitting it under that name invites an
    # agent to feed it to get_sbom_packages and hit a misleading not-found.
    # sbom_id / document_id are the real artifact identifiers.
    return compact(
        {
            "type": obj.artifact_type,
            "name": obj.artifact_name,
            "sbom_id": obj.sbom_id,
            "document_id": obj.document_id,
            "auto_pinned": obj.auto_pinned,
        }
    )
