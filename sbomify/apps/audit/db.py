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
  (``chain_seq``, ``prev_hash``, ``entry_hash``). The chain's head is kept in
  ``audit_chain_heads``, which only moves forward and cannot be deleted. A row
  changed or removed by someone able to disable the triggers (the table owner,
  a superuser), including the newest rows or the whole chain, no longer
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

# Every statement below is a literal: table names and the retention bounds are
# written out rather than formatted in, so nothing assembled at runtime ever
# reaches cursor.execute. test_db_guards checks the written-out values still
# match RETENTION_DEFAULT_DAYS, RETENTION_MIN_DAYS and HASH_VERSION.

# The hash format every new row is sealed with. A row records the version it
# was sealed under, so changing what the hash covers means adding a v2 function
# beside this one, never editing v1: an edit would silently re-define the hash
# of every row already written. ``test_canonical_v1_is_frozen`` holds that line.
HASH_VERSION = 1

# The fields an entry's hash covers, in order. Everything except the hash
# itself. ``occurred_at`` is rendered in UTC with a fixed format and ``metadata``
# as jsonb text, so the digest does not depend on the session's TimeZone or on
# key order.
CANONICAL_SQL = """
CREATE OR REPLACE FUNCTION audit_events_canonical_v1(e audit_events) RETURNS text
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

# Dispatches on the version a row was sealed with.
DIGEST_SQL = """
CREATE OR REPLACE FUNCTION audit_events_digest(e audit_events) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT encode(sha256(convert_to(
    CASE e.hash_version
      WHEN 1 THEN audit_events_canonical_v1(e)
    END, 'UTF8')), 'hex')
$$;
"""

# The chain's head lives in its own row per workspace, not in the newest
# event. Reading it from the events themselves meant a workspace whose every
# event had expired started again at 1, re-using sequence numbers an export or
# a SIEM had already seen, and that deleting the newest events left nothing
# behind to notice. The head only moves forward: ``last_seq`` with every
# insert, ``purged_through_seq`` with every delete the retention guard allows.
SEAL_SQL = """
CREATE OR REPLACE FUNCTION audit_events_seal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  head_seq bigint;
  head_hash text;
BEGIN
  INSERT INTO audit_chain_heads (workspace_id, last_seq, last_hash, purged_through_seq)
  VALUES (NEW.workspace_id, 0, '', 0)
  ON CONFLICT (workspace_id) DO NOTHING;

  -- The row lock is what serialises writers to one workspace's chain. It is
  -- held to the end of a short transaction: events are written after the
  -- change they describe has committed.
  SELECT last_seq, last_hash INTO head_seq, head_hash
    FROM audit_chain_heads
   WHERE workspace_id = NEW.workspace_id
     FOR UPDATE;

  NEW.occurred_at := clock_timestamp();
  NEW.hash_version := 1;
  NEW.chain_seq := head_seq + 1;
  NEW.prev_hash := head_hash;
  NEW.entry_hash := audit_events_digest(NEW);

  UPDATE audit_chain_heads
     SET last_seq = NEW.chain_seq, last_hash = NEW.entry_hash
   WHERE workspace_id = NEW.workspace_id;
  RETURN NEW;
END
$$;
"""

REFUSE_SQL = """
CREATE OR REPLACE FUNCTION audit_events_refuse() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: % is not permitted', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END
$$;
"""

GUARD_DELETE_SQL = """
CREATE OR REPLACE FUNCTION audit_events_guard_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  retention integer;
BEGIN
  SELECT w.audit_log_retention_days INTO retention
    FROM workspaces_workspaces w
   WHERE w.id = OLD.workspace_id;
  retention := GREATEST(COALESCE(retention, 365), 30);
  IF OLD.occurred_at >= now() - make_interval(days => retention) THEN
    RAISE EXCEPTION 'audit event % is inside its % day retention window and cannot be deleted',
      OLD.event_id, retention
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  -- Remember how far retention has reached, so a gap at the old end of the
  -- chain can be told apart from one cut by hand.
  UPDATE audit_chain_heads
     SET purged_through_seq = GREATEST(purged_through_seq, OLD.chain_seq)
   WHERE workspace_id = OLD.workspace_id;
  RETURN OLD;
END
$$;
"""

GUARD_HEAD_SQL = """
CREATE OR REPLACE FUNCTION audit_chain_heads_guard_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.workspace_id <> OLD.workspace_id
     OR NEW.last_seq < OLD.last_seq
     OR NEW.purged_through_seq < OLD.purged_through_seq
     OR (NEW.last_seq = OLD.last_seq AND NEW.last_hash <> OLD.last_hash) THEN
    RAISE EXCEPTION 'audit chain heads only move forward'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END
$$;
"""

TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS audit_events_seal ON audit_events;
CREATE TRIGGER audit_events_seal BEFORE INSERT ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_events_seal();

DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;
CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_events_refuse();

DROP TRIGGER IF EXISTS audit_events_guard_delete ON audit_events;
CREATE TRIGGER audit_events_guard_delete BEFORE DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_events_guard_delete();

DROP TRIGGER IF EXISTS audit_chain_heads_guard_update ON audit_chain_heads;
CREATE TRIGGER audit_chain_heads_guard_update BEFORE UPDATE ON audit_chain_heads
  FOR EACH ROW EXECUTE FUNCTION audit_chain_heads_guard_update();

DROP TRIGGER IF EXISTS audit_chain_heads_no_delete ON audit_chain_heads;
CREATE TRIGGER audit_chain_heads_no_delete BEFORE DELETE ON audit_chain_heads
  FOR EACH ROW EXECUTE FUNCTION audit_events_refuse();
"""

TRUNCATE_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events;
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
  FOR EACH STATEMENT EXECUTE FUNCTION audit_events_refuse();

DROP TRIGGER IF EXISTS audit_chain_heads_no_truncate ON audit_chain_heads;
CREATE TRIGGER audit_chain_heads_no_truncate BEFORE TRUNCATE ON audit_chain_heads
  FOR EACH STATEMENT EXECUTE FUNCTION audit_events_refuse();
"""

# Only for test databases, which Django flushes with TRUNCATE. It drops the
# trigger rather than merely not creating it, so a database built by the
# migration (which always installs it) ends up in the state the setting asks for.
ALLOW_TRUNCATE_SQL = """
DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events;
DROP TRIGGER IF EXISTS audit_chain_heads_no_truncate ON audit_chain_heads;
"""

UNINSTALL_SQL = """
DROP TRIGGER IF EXISTS audit_chain_heads_no_truncate ON audit_chain_heads;
DROP TRIGGER IF EXISTS audit_chain_heads_no_delete ON audit_chain_heads;
DROP TRIGGER IF EXISTS audit_chain_heads_guard_update ON audit_chain_heads;
DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events;
DROP TRIGGER IF EXISTS audit_events_guard_delete ON audit_events;
DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;
DROP TRIGGER IF EXISTS audit_events_seal ON audit_events;
DROP FUNCTION IF EXISTS audit_chain_heads_guard_update();
DROP FUNCTION IF EXISTS audit_events_guard_delete();
DROP FUNCTION IF EXISTS audit_events_refuse();
DROP FUNCTION IF EXISTS audit_events_seal();
DROP FUNCTION IF EXISTS audit_events_digest(audit_events);
DROP FUNCTION IF EXISTS audit_events_canonical_v1(audit_events);
"""


def install_statements(*, block_truncate: bool = True) -> list[str]:
    statements = [CANONICAL_SQL, DIGEST_SQL, SEAL_SQL, REFUSE_SQL, GUARD_DELETE_SQL, GUARD_HEAD_SQL, TRIGGERS_SQL]
    statements.append(TRUNCATE_TRIGGER_SQL if block_truncate else ALLOW_TRUNCATE_SQL)
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
    # What is wrong with the chain as a whole: entries missing at either end.
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.broken and not self.problems


VERIFY_SQL = """
SELECT chain_seq,
       entry_hash = audit_events_digest(e) AS hash_ok,
       prev_hash,
       entry_hash,
       lag(entry_hash) OVER w AS expected_prev,
       lag(chain_seq) OVER w AS previous_seq
  FROM audit_events e
 WHERE workspace_id = %s
WINDOW w AS (ORDER BY chain_seq)
 ORDER BY chain_seq
"""

HEAD_SQL = "SELECT last_seq, last_hash, purged_through_seq FROM audit_chain_heads WHERE workspace_id = %s"


def verify_chain(workspace_id: int) -> ChainReport:
    """Recompute every entry's hash, check each links to the one before, and check both ends.

    Entries may be missing from the old end only as far as retention has
    deleted them, which the chain head records. The newest entry must be the
    one the head says was written last. Anything else missing, edited or
    reordered is reported.
    """
    if connection.vendor != "postgresql":
        return ChainReport(checked=0, first_seq=None, last_seq=None, broken=())

    broken: list[int] = []
    first_seq: int | None = None
    last_seq: int | None = None
    last_hash = ""
    checked = 0
    with connection.cursor() as cursor:
        cursor.execute(HEAD_SQL, [workspace_id])
        head = cursor.fetchone()
        cursor.execute(VERIFY_SQL, [workspace_id])
        for seq, hash_ok, prev_hash, entry_hash, expected_prev, previous_seq in cursor.fetchall():
            checked += 1
            if first_seq is None:
                first_seq = seq
            last_seq, last_hash = seq, entry_hash
            if not hash_ok:
                broken.append(seq)
            elif previous_seq is not None and (previous_seq != seq - 1 or prev_hash != expected_prev):
                broken.append(seq)

    problems: list[str] = []
    if head is None:
        if checked:
            problems.append("the chain head is missing")
    else:
        head_seq, head_hash, purged_through = head
        expected_first = purged_through + 1
        if first_seq is None:
            if head_seq > purged_through:
                problems.append(f"entries {expected_first} to {head_seq} are missing")
        else:
            if first_seq > expected_first:
                problems.append(f"entries {expected_first} to {first_seq - 1} are missing, inside retention")
            if last_seq != head_seq or last_hash != head_hash:
                problems.append(f"the newest entries are missing: the chain was written up to {head_seq}")
    return ChainReport(
        checked=checked, first_seq=first_seq, last_seq=last_seq, broken=tuple(broken), problems=tuple(problems)
    )
