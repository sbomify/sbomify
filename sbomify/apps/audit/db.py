"""The database-side controls that make ``audit_events`` append-only.

Everything that makes the audit trail trustworthy lives here, in SQL, so that
it holds for every path that reaches the table: the ORM, ``bulk_create``, raw
SQL, a Django shell, ``psql``. Python code cannot opt out of it.

* ``UPDATE`` is refused for every row, always.
* ``TRUNCATE`` is refused, always.
* ``DELETE`` is refused unless the row is older than its workspace's retention
  window (``workspaces_workspaces.audit_log_retention_days``, never below
  ``RETENTION_MIN_DAYS``). That is the TTL: the purge task deletes exactly what
  the trigger lets it, and nothing else can delete anything.
* ``INSERT`` is sealed: the trigger stamps ``occurred_at`` with the database
  clock and links the row into its workspace's SHA-256 hash chain
  (``chain_seq``, ``prev_hash``, ``entry_hash``). A row changed or removed by
  someone able to disable the triggers (the table owner, a superuser) no longer
  verifies, and ``verify_chain`` says where.

The table owner can still ``ALTER TABLE ... DISABLE TRIGGER``; PostgreSQL gives
no way to stop that. Running the application under a role that does not own
the table closes that gap, and the hash chain is what makes it visible when it
is not closed.

The same statements are installed by the migration and, for a test database
built with ``--nomigrations``, by a ``post_migrate`` handler. Every statement
is idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import connection

from .models import RETENTION_DEFAULT_DAYS, RETENTION_MIN_DAYS

TABLE = "audit_events"
WORKSPACE_TABLE = "workspaces_workspaces"

# The fields an entry's hash covers, in order. Everything except the hash
# itself. ``occurred_at`` is rendered in UTC with a fixed format and ``metadata``
# as jsonb text, so the digest does not depend on the session's TimeZone or on
# key order.
CANONICAL_SQL = f"""
CREATE OR REPLACE FUNCTION audit_events_canonical(e {TABLE}) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT json_build_array(
    e.event_id::text,
    e.workspace_id,
    e.chain_seq,
    to_char(e.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    e.action,
    e.outcome,
    e.actor_type,
    e.actor_user_id,
    e.actor_label,
    e.actor_role,
    e.channel,
    e.credential_kind,
    e.credential_id,
    e.target_type,
    e.target_id,
    e.target_label,
    host(e.ip_address),
    e.user_agent,
    e.request_id,
    e.http_method,
    e.path,
    e.status_code,
    e.metadata::jsonb::text,
    e.prev_hash
  )::text
$$;
"""

SEAL_SQL = f"""
CREATE OR REPLACE FUNCTION audit_events_seal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  last_seq bigint;
  last_hash text;
BEGIN
  -- One writer per workspace chain at a time. Held to the end of the
  -- transaction, which is short: events are written after the change commits.
  PERFORM pg_advisory_xact_lock(hashtextextended('sbomify.audit:' || NEW.workspace_id::text, 0));

  SELECT chain_seq, entry_hash INTO last_seq, last_hash
    FROM {TABLE}
   WHERE workspace_id = NEW.workspace_id AND chain_seq IS NOT NULL
   ORDER BY chain_seq DESC
   LIMIT 1;

  NEW.occurred_at := clock_timestamp();
  NEW.chain_seq := COALESCE(last_seq, 0) + 1;
  NEW.prev_hash := COALESCE(last_hash, '');
  NEW.entry_hash := encode(sha256(convert_to(audit_events_canonical(NEW), 'UTF8')), 'hex');
  RETURN NEW;
END
$$;
"""

REFUSE_SQL = f"""
CREATE OR REPLACE FUNCTION audit_events_refuse() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '{TABLE} is append-only: % is not permitted', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END
$$;
"""

GUARD_DELETE_SQL = f"""
CREATE OR REPLACE FUNCTION audit_events_guard_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  retention integer;
BEGIN
  SELECT w.audit_log_retention_days INTO retention
    FROM {WORKSPACE_TABLE} w
   WHERE w.id = OLD.workspace_id;
  retention := GREATEST(COALESCE(retention, {RETENTION_DEFAULT_DAYS}), {RETENTION_MIN_DAYS});
  IF OLD.occurred_at >= now() - make_interval(days => retention) THEN
    RAISE EXCEPTION 'audit event % is inside its % day retention window and cannot be deleted',
      OLD.event_id, retention
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN OLD;
END
$$;
"""

TRIGGERS_SQL = f"""
DROP TRIGGER IF EXISTS audit_events_seal ON {TABLE};
CREATE TRIGGER audit_events_seal BEFORE INSERT ON {TABLE}
  FOR EACH ROW EXECUTE FUNCTION audit_events_seal();

DROP TRIGGER IF EXISTS audit_events_no_update ON {TABLE};
CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON {TABLE}
  FOR EACH ROW EXECUTE FUNCTION audit_events_refuse();

DROP TRIGGER IF EXISTS audit_events_guard_delete ON {TABLE};
CREATE TRIGGER audit_events_guard_delete BEFORE DELETE ON {TABLE}
  FOR EACH ROW EXECUTE FUNCTION audit_events_guard_delete();
"""

TRUNCATE_TRIGGER_SQL = f"""
DROP TRIGGER IF EXISTS audit_events_no_truncate ON {TABLE};
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON {TABLE}
  FOR EACH STATEMENT EXECUTE FUNCTION audit_events_refuse();
"""

UNINSTALL_SQL = """
DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events;
DROP TRIGGER IF EXISTS audit_events_guard_delete ON audit_events;
DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;
DROP TRIGGER IF EXISTS audit_events_seal ON audit_events;
DROP FUNCTION IF EXISTS audit_events_guard_delete();
DROP FUNCTION IF EXISTS audit_events_refuse();
DROP FUNCTION IF EXISTS audit_events_seal();
DROP FUNCTION IF EXISTS audit_events_canonical(audit_events);
"""


def install_statements(*, block_truncate: bool = True) -> list[str]:
    statements = [CANONICAL_SQL, SEAL_SQL, REFUSE_SQL, GUARD_DELETE_SQL, TRIGGERS_SQL]
    if block_truncate:
        statements.append(TRUNCATE_TRIGGER_SQL)
    return statements


def install(schema_editor: Any = None, *, block_truncate: bool = True) -> None:
    """Install (or refresh) the guards. A no-op on anything but PostgreSQL."""
    conn = schema_editor.connection if schema_editor is not None else connection
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as cursor:
        for statement in install_statements(block_truncate=block_truncate):
            cursor.execute(statement)


def uninstall(schema_editor: Any = None) -> None:
    conn = schema_editor.connection if schema_editor is not None else connection
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as cursor:
        cursor.execute(UNINSTALL_SQL)


@dataclass(frozen=True)
class ChainReport:
    """What ``verify_chain`` found for one workspace."""

    checked: int
    first_seq: int | None
    last_seq: int | None
    # chain_seq of every entry whose hash, link or position does not verify.
    broken: tuple[int, ...]

    @property
    def ok(self) -> bool:
        return not self.broken


VERIFY_SQL = """
SELECT chain_seq,
       entry_hash = encode(sha256(convert_to(audit_events_canonical(e), 'UTF8')), 'hex') AS hash_ok,
       prev_hash,
       lag(entry_hash) OVER w AS expected_prev,
       lag(chain_seq) OVER w AS previous_seq
  FROM audit_events e
 WHERE workspace_id = %s
WINDOW w AS (ORDER BY chain_seq)
 ORDER BY chain_seq
"""


def verify_chain(workspace_id: int) -> ChainReport:
    """Recompute every entry's hash and check each links to the one before.

    The oldest surviving entry is allowed to point at a predecessor that is no
    longer there, because retention removes entries from the old end. Anything
    else missing, edited or reordered is reported.
    """
    if connection.vendor != "postgresql":
        return ChainReport(checked=0, first_seq=None, last_seq=None, broken=())

    broken: list[int] = []
    first_seq: int | None = None
    last_seq: int | None = None
    checked = 0
    with connection.cursor() as cursor:
        cursor.execute(VERIFY_SQL, [workspace_id])
        for seq, hash_ok, prev_hash, expected_prev, previous_seq in cursor.fetchall():
            checked += 1
            if first_seq is None:
                first_seq = seq
            last_seq = seq
            if not hash_ok:
                broken.append(seq)
            elif previous_seq is not None and (previous_seq != seq - 1 or prev_hash != expected_prev):
                broken.append(seq)
    return ChainReport(checked=checked, first_seq=first_seq, last_seq=last_seq, broken=tuple(broken))
