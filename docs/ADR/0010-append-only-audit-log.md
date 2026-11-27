# 10. An Append-Only Audit Log Enforced by the Database

Date: 2026-11-25

## Status

Accepted

## Context

Enterprise workspaces need to answer "who did what, when, and from where" for
their own reviews and for auditors: who changed a member's role, who made a
component public, what an AI agent did with the token it was given. sbomify had
structured log lines for a few regulated paths (CRA wizard changes, release
lifecycle, MCP tool calls) but nothing a workspace could read, nothing that
covered ordinary changes, and nothing that could not be edited by whoever
controlled the log sink.

An audit trail is only worth what its integrity is worth. A table the
application can `UPDATE` is a table any bug, compromised admin session or
careless migration can rewrite.

## Decision

**One table, `audit_events`, append-only, enforced by PostgreSQL triggers.**
`UPDATE` and `TRUNCATE` are refused outright. `DELETE` is refused unless the
row is past its workspace's retention window, so the retention purge is the
only delete that can succeed, and it is the same condition the trigger checks.
The ORM guards on the model exist only to fail early with a readable message.

**The database seals each insert.** A `BEFORE INSERT` trigger sets
`occurred_at` from the database clock and links the row into a per-workspace
SHA-256 hash chain (`chain_seq`, `prev_hash`, `entry_hash`). The chain's head
lives in `audit_chain_heads`, one row per workspace that only moves forward and
cannot be deleted, so removing the newest events, or old ones still inside
retention, is detectable too, and sequence numbers never restart. Each row
records its hash format version, so the format can change without
re-defining the hash of rows already written. The triggers do not stop the table owner, who can
disable them; the chain makes what they then did detectable, and running the
app under a non-owner role prevents it. This is the same model as GitLab's and
GitHub's audit streams, plus the tamper evidence of a hash chain.

**Snapshots, not foreign keys.** The actor, target and workspace are copied
into the row. A foreign key would either cascade, deleting the evidence when a
user or workspace is deleted, or block those deletions.

**Coverage does not depend on remembering.** Three sources feed the log:

1. Model signals for a registry of tracked models, which give precise events
   (`member.updated` with the role's old and new value).
2. A middleware fallback: a state-changing request that recorded nothing more
   specific becomes one `request.*` event with its route and status, so a new
   endpoint is audited before anyone adds it to the registry, and refused
   requests are visible.
3. The MCP tool wrapper, which opens the same context for every tool call and
   records each call. An agent is recorded as `actor_type=agent` with the
   person it acts for as `actor_user_id`.

Events are written after the transaction they describe commits, so the log
never claims a change that rolled back. Refusals are written immediately.

**The actor model follows OCSF/CADF:** actor (type, id, label, role at the
time), action, target, outcome, and request context (IP, user agent, request
id, channel, credential kind and id). Never request bodies, artifact content
or secrets: redacted fields are recorded by name only.

**Retention is per workspace, bounded in the database.** 365 days by default,
between 30 and 3650, held by a check constraint so no write path can shorten
the window enough to erase the change that shortened it.

**Access follows the ladder.** Two new actions, `audit_log:read` and
`audit_log:manage`, both `ADMINISTER`. The feature is gated on the Enterprise
plan, or on billing being off for self-hosted deployments. Events are only
recorded for entitled workspaces.

## Consequences

- Every tracked-model save inside a request costs one extra query for an
  update (the previous values) and one cached plan lookup per request.
- A transactional test cannot be flushed with `TRUNCATE` while the truncate
  guard is installed, so `test_settings` leaves that one trigger out; a test
  installs it inside a transaction to prove it holds.
- Reads are recorded only for MCP. Recording every human page view would bury
  the changes the log exists for.
- A workspace that leaves Enterprise keeps its existing events until they
  expire, but records no new ones and cannot read them until it returns.
