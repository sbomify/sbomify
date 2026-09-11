"""Helpers shared by the document upload API and the document services.

Kept out of the API layer so the service layer can use them without importing
django-ninja routers.
"""

from __future__ import annotations

from django.db import IntegrityError

from sbomify.apps.documents.models import DOCUMENT_UNIQUE_CONSTRAINT, Document

DUPLICATE_DOCUMENT_DETAIL = "Document '{name}' with version '{version}' already exists for this component"


def duplicate_document_detail(name: str, version: str) -> str:
    """The single wording every path uses to report a duplicate document."""
    return DUPLICATE_DOCUMENT_DETAIL.format(name=name, version=version)


def document_version_exists(component_id: str, name: str, version: str, exclude_id: str | None = None) -> bool:
    """Whether the component already holds this name/version pair.

    Checked before the S3 upload so the common case never stores an object for a
    row that cannot be written. The unique constraint remains the real guard —
    under READ COMMITTED two concurrent uploads can both pass this check.
    """
    queryset = Document.objects.filter(component_id=component_id, name=name, version=version)
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    return queryset.exists()


def is_duplicate_document_error(exc: IntegrityError) -> bool:
    """Check if an IntegrityError is for the document uniqueness constraint.

    Postgres path: checks diag.constraint_name, then SQLSTATE 23505 with the
    constraint name in the message.
    SQLite path: checks for "UNIQUE constraint failed" with the relevant columns.
    """
    cause = exc.__cause__
    if cause is not None:
        # PostgreSQL diagnostics first (most precise)
        diag = getattr(cause, "diag", None)
        if diag is not None and getattr(diag, "constraint_name", None) == DOCUMENT_UNIQUE_CONSTRAINT:
            return True

        if getattr(cause, "pgcode", None) == "23505":
            return DOCUMENT_UNIQUE_CONSTRAINT in str(exc).lower()

    msg = str(exc).lower()

    # Postgres fallback (no __cause__ or missing diag)
    if DOCUMENT_UNIQUE_CONSTRAINT in msg:
        return True

    # SQLite: "UNIQUE constraint failed: <db_table>.component_id, <db_table>.name, ..."
    # Derive the table from the model so it can't drift from db_table.
    table = Document._meta.db_table
    return "unique constraint failed" in msg and all(
        f"{table}.{col}" in msg for col in ("component_id", "name", "version")
    )
