"""Which uniqueness violation an IntegrityError actually is.

``create_release`` is idempotent on a name collision — two CI jobs tagging the
same release both insert, and the loser is handed the existing row rather than a
400 that fails its build. A version collision under a *different* name is a real
conflict and must not be swallowed that way. So the two have to be told apart
from the exception, and getting it backwards breaks one case or the other.

The drivers make that harder than it looks. Postgres names the constraint;
SQLite names the columns; and Postgres also puts the offending **values** in the
message, which is what a substring match is most likely to trip over.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from sbomify.apps.core.apis import _is_release_name_conflict, _is_release_version_conflict


def _integrity_error(message: str, constraint_name: str | None = None) -> IntegrityError:
    """An IntegrityError shaped like the one a driver raises.

    ``constraint_name`` rides on a ``diag`` attached to ``__cause__``, which is
    where psycopg puts it and where the detection prefers to read it from.
    SQLite supplies none, so leaving it out is that case.
    """
    exc = IntegrityError(message)
    if constraint_name is not None:
        cause = Exception(message)
        cause.diag = type("Diag", (), {"constraint_name": constraint_name})()  # type: ignore[attr-defined]
        cause.pgcode = "23505"  # type: ignore[attr-defined]
        exc.__cause__ = cause
    return exc


# Captured verbatim from psycopg against Postgres 17, by provoking each
# collision on a real table. Written down rather than provoked here because the
# point is the exact text — a paraphrase of it would pin nothing, and the trap
# these guard is a substring of the values in the DETAIL line. The constraint
# hash is Django's and is not matched on.
PG_NAME_COLLISION = (
    'duplicate key value violates unique constraint "core_releases_product_id_name_6c5eebca_uniq"\n'
    "DETAIL:  Key (product_id, name)=(abc123def456, Version 1.0) already exists.\n"
)
PG_VERSION_COLLISION = (
    'duplicate key value violates unique constraint "unique_product_version_when_not_empty"\n'
    "DETAIL:  Key (product_id, version)=(abc123def456, 1.0) already exists.\n"
)
SQLITE_NAME_COLLISION = "UNIQUE constraint failed: core_releases.product_id, core_releases.name"
SQLITE_VERSION_COLLISION = "UNIQUE constraint failed: core_releases.product_id, core_releases.version"


@pytest.mark.parametrize(
    "name",
    ["Version 1.0", "conversion", "v2-version", "VERSION"],
    ids=["spaced", "substring", "hyphenated", "uppercase"],
)
def test_a_release_name_containing_version_is_not_a_version_conflict(name: str) -> None:
    """The trap: Postgres puts the release *name* in the error message.

    A release called "Version 1.0" is an ordinary thing to call a release, and a
    bare ``"version" in message`` test makes its name collision look like a
    version collision. That branch runs first, so the caller would get
    ``400 A release with this version already exists`` — naming the wrong field,
    and losing the idempotent 200 that keeps two CI jobs tagging the same
    release from failing each other's build.

    SQLite never puts values in its message, so no amount of testing there
    catches this.
    """
    message = (
        'duplicate key value violates unique constraint "core_releases_product_id_name_6c5eebca_uniq"\n'
        f"DETAIL:  Key (product_id, name)=(abc123def456, {name}) already exists.\n"
    )
    exc = _integrity_error(message, constraint_name="core_releases_product_id_name_6c5eebca_uniq")

    assert not _is_release_version_conflict(exc)
    assert _is_release_name_conflict(exc)


@pytest.mark.parametrize(
    ("message", "constraint_name", "is_version"),
    [
        (PG_VERSION_COLLISION, "unique_product_version_when_not_empty", True),
        (PG_NAME_COLLISION, "core_releases_product_id_name_6c5eebca_uniq", False),
        (SQLITE_VERSION_COLLISION, None, True),
        (SQLITE_NAME_COLLISION, None, False),
    ],
    ids=["postgres version", "postgres name", "sqlite version", "sqlite name"],
)
def test_each_driver_and_collision_is_classified(message: str, constraint_name: str | None, is_version: bool) -> None:
    """Both drivers, both collisions.

    The SQLite version row is the case the constraint-name-only check missed
    entirely: SQLite names the columns, so a duplicate version fell through to
    the generic handler and the caller was told "Internal server error".
    """
    exc = _integrity_error(message, constraint_name)

    assert _is_release_version_conflict(exc) is is_version


def test_an_unrelated_integrity_error_is_neither() -> None:
    """A foreign key or a NOT NULL must surface as itself.

    Both helpers detect positively for this reason: rewriting an unrelated
    failure into "already exists" would report a bug as a duplicate.
    """
    exc = _integrity_error(
        'insert or update on table "core_releases" violates foreign key constraint '
        '"core_releases_product_id_fk"\nDETAIL:  Key (product_id)=(nope) is not present in table "sboms_products".\n'
    )

    assert not _is_release_version_conflict(exc)
    assert not _is_release_name_conflict(exc)
