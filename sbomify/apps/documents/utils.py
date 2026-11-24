"""Helpers shared by the document upload API and the document services.

Kept out of the API layer so the service layer can use them without importing
django-ninja routers.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast

from django.db import IntegrityError

from sbomify.apps.documents.models import DOCUMENT_UNIQUE_CONSTRAINT, Document

DUPLICATE_DOCUMENT_DETAIL = "Document '{name}' with version '{version}' already exists for this component"

# Read from the field so a column change cannot leave this behind. The cast is
# for the type checker only: the field is a CharField and always declares one.
VERSION_MAX_LENGTH: int = cast(int, Document._meta.get_field("version").max_length)


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


def fits_as_fixed_point(value: Decimal) -> bool:
    """Whether the value could render inside the column at all.

    Read off the exponent rather than measured from the rendered string:
    ``format(Decimal("1E-999999999"), "f")`` builds a gigabyte of zeroes before
    anything could measure it, and ``Decimal("1E+999999999") + Decimal("0.1")``
    raises ``Overflow`` before that. Both fit the field as written, so the guard
    has to come before the arithmetic.
    """
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):  # "n", "N" or "F": NaN and Infinity
        return False
    integer_digits = max(value.adjusted() + 1, 1)
    fractional_digits = max(-exponent, 0)
    return integer_digits + fractional_digits <= VERSION_MAX_LENGTH


def normalize_decimal_version(value: Decimal) -> str:
    """Render a decimal version the way the NDA allocator always has: "1.10" -> "1.1".

    Formatted with ``f`` rather than ``str``: ``str(Decimal)`` switches to
    scientific notation for large values, and stripping trailing zeroes from
    "1E+30" eats the exponent and returns "1E+3", a different number. Zeroes are
    only ever stripped from a fractional part, so an integral value keeps its
    magnitude too ("100" stays "100").
    """
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def bump_decimal_version(current: str) -> str | None:
    """The next 0.1 step from a version string, or ``None`` if it cannot be counted on.

    Callers guess the next version this way, and every one of them has to survive
    a version string a user chose. Non-numeric is the obvious case; the ones that
    bite are numeric: "NaN" and "Infinity" parse but never move, and
    "1E+999999999" parses, fits the column, and raises ``Overflow`` on the
    addition. ``None`` means "pick another way", not "invalid".
    """
    try:
        value = Decimal(current)
    except InvalidOperation:
        return None

    if not value.is_finite() or not fits_as_fixed_point(value):
        return None

    bumped = value + Decimal("0.1")
    if not fits_as_fixed_point(bumped):
        return None

    return normalize_decimal_version(bumped)


def next_free_document_version(component_id: str, name: str, candidate: str) -> str:
    """``candidate``, or the next version free for this component and name.

    A version allocator that guesses can land on a pair the component already
    holds, which the uniqueness constraint rejects. The company NDA allocator
    does exactly that: it reads the newest NDA's version and adds 0.1, so an
    out-of-order upload (or a version the duplicate migration suffixed) can point
    it at a version already in use. Numeric candidates keep counting in the same
    0.1 steps, anything else gets a numeric suffix.

    One query, then arithmetic. The walk always terminates: the decimal path stops
    as soon as a step fails to advance or outgrows the column, and the suffix path
    is bounded by the number of versions actually in use. Every result fits
    ``VERSION_MAX_LENGTH``, so the caller's insert cannot fail on length.
    """
    taken = set(Document.objects.filter(component_id=component_id, name=name).values_list("version", flat=True))
    # A candidate the column cannot hold is no more usable than a taken one: the
    # caller builds it by arithmetic on an existing version, so it can overflow.
    if candidate not in taken and len(candidate) <= VERSION_MAX_LENGTH:
        return candidate

    try:
        value = Decimal(candidate)
    except InvalidOperation:
        value = None

    # Decimal parses "NaN" and "Infinity" too, and adding to either returns it
    # unchanged, so a version like that would count forever. Only a finite decimal
    # can be counted on from; everything else gets the suffix.
    if value is not None and value.is_finite() and fits_as_fixed_point(value):
        current = candidate
        while True:
            value += Decimal("0.1")
            if not fits_as_fixed_point(value):
                break
            bumped = normalize_decimal_version(value)
            # A finite value can still fail to move: past the context precision
            # (28 digits by default) adding 0.1 rounds straight back. It can also
            # round up into a longer fixed-point string than the column holds.
            # Either way it falls through to the suffix, which truncates and is
            # bounded by the number of versions actually in use.
            if bumped == current or len(bumped) > VERSION_MAX_LENGTH:
                break
            if bumped not in taken:
                return bumped
            current = bumped

    # Truncated to fit: a candidate can already be at max_length, and a version
    # the column cannot hold would just fail the insert we are trying to avoid.
    suffix = 2
    while True:
        tail = f" ({suffix})"
        suffixed = candidate[: VERSION_MAX_LENGTH - len(tail)] + tail
        if suffixed not in taken:
            return suffixed
        suffix += 1
