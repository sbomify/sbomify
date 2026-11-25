# Audit log

Every workspace on the Enterprise plan (and every workspace on a deployment with
billing switched off) keeps an append-only record of what its members, the AI
agents acting for them, and its CI pipelines did. Owners and admins read it under
**Settings > Audit log**, export it as CSV or JSON Lines, and choose how long it
is kept. The design decisions are in [ADR-010](ADR/0010-append-only-audit-log.md).

## What is recorded

| Source | Actions | Example |
| --- | --- | --- |
| A change to a tracked model | `<target>.created`, `<target>.updated`, `<target>.deleted` | `product.updated` with `{"changes": {"name": {"from": "A", "to": "B"}}}` |
| Signing in and out | `auth.signed_in`, `auth.signed_out` | one event in each workspace the person is an internal member of |
| An MCP tool call, read or write | `agent.tool_call` | `{"tool": "create_contact_profile", "writes": true}` |
| Exporting the log | `audit_log.exported` | the format and the filters used |
| Any other state-changing request | `request.post`, `request.put`, `request.patch`, `request.delete` | the route, the status, and the `*_action` field of the settings form submitted |

The tracked models are listed in `TRACKED` in `sbomify/apps/audit/signals.py`:
the workspace itself, members, invitations, parties, API tokens, products,
components, the links between them, artifacts, documents, releases, trusted
publishers, advisories and integrations. An update is recorded only when a
watched field changes, so housekeeping writes such as a token's last-used time
are not. Fields whose value is a secret or long free text (an integration's
credentials, a product's description) are recorded by name only.

A request that changes state and records nothing more specific becomes a
`request.*` event, so a new endpoint is covered before anyone adds it to
`TRACKED`. Refusals (401 and 403) are recorded with outcome `denied`, other
errors with `failure`. Request bodies are never recorded.

Reads are not recorded, except through MCP, where every tool call is: an
agent's reads are part of what it did on someone's behalf.

Changes made outside a request or a tool call (background tasks, migrations,
management commands) are not user activity and are not recorded.

## Each event

| Field | Meaning |
| --- | --- |
| `event_id` | A UUID, stable across exports |
| `occurred_at` | Set by the database clock on insert |
| `action`, `outcome` | What happened, and `success`, `failure` or `denied` |
| `actor.type` | `user`, `agent` (MCP, or a REST call with an AI agent token) or `bot` (OIDC trusted publishing) |
| `actor.user_id`, `actor.label`, `actor.role` | The person, or the person an agent acts for, as they were at the time |
| `channel` | `web`, `api`, `mcp` or `ci` |
| `credential.kind`, `credential.id` | `session`, `pat`, `oauth` or `oidc`, and the token id. Never the token itself |
| `target.type`, `target.id`, `target.label` | What it was done to, with its name at the time |
| `request` | Request id, client IP, user agent, method, path and status |
| `metadata` | Field changes and anything specific to the action |
| `chain.seq`, `chain.prev_hash`, `chain.entry_hash` | The event's place in the workspace's hash chain |

The actor and target are copies, not foreign keys, so an event still reads
correctly after its subject is renamed or deleted, and deleting a person or a
workspace does not delete the record of what they did.

## Immutability

The guarantees are enforced by PostgreSQL triggers on `audit_events`, installed
by `sbomify/apps/audit/db.py`, so they hold for every path to the table,
including raw SQL:

- `UPDATE` and `TRUNCATE` are refused.
- `DELETE` is refused for any event still inside its workspace's retention
  window.
- On insert, the database stamps `occurred_at` and links the event into a
  per-workspace SHA-256 hash chain. An application cannot backdate an event.

The table owner can still disable triggers. Run the application as a role that
does not own the table to close that. Whether or not you do, the hash chain
makes an edited or removed event detectable:

```python
from sbomify.apps.audit.db import verify_chain

report = verify_chain(workspace_id)
report.ok, report.broken  # chain_seq of every entry that does not verify
```

The oldest surviving entry may point at a predecessor that retention removed;
that is not reported.

## Retention

Each workspace keeps events for `audit_log_retention_days`, 365 by default,
between 30 and 3650. The bounds are a database check constraint, so no path can
set a window short enough to erase the change that set it. Changing retention
is itself recorded as `workspace.updated`.

`purge_expired_audit_events` runs daily at 03:30 UTC and deletes exactly what
the delete trigger allows. Events of a deleted workspace are kept for the
default 365 days.

## API

Served on v1 and v2 at the same paths under `/api/v1/audit/` and `/api/v2/audit/`. Session or personal access token; the caller must be an
owner or admin, and a scoped token needs `audit_log:read` (or `audit_log:manage`
to change retention). A workspace without the audit log answers `402`.

```text
GET /api/v2/audit/{workspace_key}/events?action=product&outcome=denied&since=2026-01-01T00:00:00Z&limit=50
GET /api/v2/audit/{workspace_key}/events?cursor=<next_cursor>
GET /api/v2/audit/{workspace_key}/events/export?format=csv
GET /api/v2/audit/{workspace_key}/events/export?format=jsonl
GET /api/v2/audit/{workspace_key}/retention
PUT /api/v2/audit/{workspace_key}/retention   {"retention_days": 730}
```

Filters: `action` (exact, or a prefix such as `product`), `actor` (a user id or
part of an email), `target_type`, `target_id`, `outcome`, `since`, `until`,
`search`. Lists are newest first; pass `next_cursor` back as `cursor` for the
next page. One export holds at most 100,000 events; narrow the dates for more.
JSON Lines is one event per line, in the same shape as the list endpoint, for
SIEM collectors.

## Adding to it

- A new model people change in a workspace: add a `Tracked` entry. Put fields
  whose value is safe to show in `fields` and secrets or long text in
  `redacted`.
- A notable event that is not a model change: call
  `sbomify.apps.audit.recorder.record(action, workspace=..., target=...)`.
- Never write to `audit_events` any other way, and never add a migration that
  updates or deletes its rows. The database will refuse.
