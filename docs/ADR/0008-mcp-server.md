# 8. MCP Server Mounted in the Django App

Date: 2026-07-27

## Status

Accepted

## Context

sbomify exposes roughly 140 REST endpoints across 14 Django Ninja routers. That
surface is built for the web UI and for CI integrations, both of which know
exactly which call they want to make. AI agents do not: they arrive with a
question ("what is the vulnerability posture of the latest release of product
X?") and have to discover the path to an answer.

The Model Context Protocol (MCP) is the emerging standard for exposing tools to
AI agents, supported by Claude Code, Claude Desktop, and other clients. Adding
an MCP server lets an agent reach sbomify data directly, with the user's own
permissions, instead of the user copy-pasting between a browser and a chat
window.

The decisive enabler already existed. `sbomify/apps/core/authz.py` provides a
single `can(actor, action, resource)` decision point over a 32-action
vocabulary, and `AccessToken` already carries a workspace pin (`team`), action
scopes (`scopes`), and an expiry. Critically, `can()` evaluates the token's
scope *before* the role check, so scope can only ever narrow access. An MCP
server that authenticates with a personal access token therefore inherits
least-privilege enforcement without inventing a second permission model: the
riskiest part of the work was already done and battle-tested.

## Decision

### Mount the MCP server inside the Django app, at `/mcp`

The server is a new Django app (`sbomify/apps/mcp/`) whose FastMCP instance is
exposed as a streamable-HTTP ASGI app and dispatched from `sbomify/asgi.py`. It
runs in the existing container, in the existing deploy, sharing models,
services, and `can()` in-process.

The alternative, a standalone server calling the public REST API, was
rejected because it would duplicate authentication plumbing over HTTP, drift
from the API it wraps, and need its own release train. ADR-001's monolith
argument applies unchanged.

### Authenticate with existing scoped personal access tokens

Clients send `Authorization: Bearer <PAT>`. The MCP app cannot reuse ninja's
`PersonalAccessTokenAuth` directly (that expects a Django `HttpRequest`, while
the MCP app is Starlette), so `sbomify/apps/mcp/auth.py` calls the same
lower-level `get_user_and_token_record` and builds a stub `HttpRequest`
carrying `user`, `access_token_record`, and `token_team`. Every tool then calls
`can()` with that stub.

OAuth 2.1 with protected-resource metadata (RFC 9728) is the direction the MCP
spec is heading and would enable one-click install. It is deferred: bearer PATs
are well-supported by current clients and reuse a token model operators already
understand and can audit via `last_used_at`.

### Let token scopes shape the advertised tool list

Each tool declares the `can()` action it requires
(`sbomify/apps/mcp/registry.py`). `tools/list` is filtered to the actions the
caller's token permits, so an agent holding a `read_only` token never sees
`upload_sbom`. This is an ergonomics decision, not a security boundary: every
invocation is still authorized by `can()` against the concrete resource, and a
client calling a tool it was never shown is refused exactly as the REST API
would refuse it. Hiding impossible tools stops agents burning turns on calls
that cannot succeed.

### Hand-write ~20 task-oriented tools rather than generating them

Generating one tool per REST endpoint would be nearly free and always in sync,
but it produces ~140 low-level tools with verbose schemas, which measurably
degrades tool-selection accuracy and floods the agent's context. The curated set
is shaped around questions agents actually ask; `get_release_risk_report`, for
instance, composes release, artifacts, vulnerability counts, and compliance
status into a single compact response.

Output shaping (`sbomify/apps/mcp/serializers.py`) is part of this decision, not
polish: nulls are omitted, lists are always paginated with explicit
`total`/`has_more`, and artifact bodies are never inlined.

### Publishing tools call the existing view functions

`upload_sbom`, `upload_vex`, `create_release`, and `tag_artifact_to_release`
invoke the REST view functions directly (Django Ninja's decorators return the
undecorated function). The upload path carries multi-version schema validation,
CBOM auto-detection, PURL qualifier extraction, the duplicate guard, S3 upload
with orphan cleanup, workspace broadcast, and VEX re-application. A parallel
implementation would drift within a release. ADR-004 holds: artifacts are stored
byte-for-byte as supplied, and the tools deliberately do not re-encode JSON.

### Treat the endpoint as a prompt-injection surface

This is the material way MCP differs from the REST API: the caller is a language
model, and much of what it reads is attacker-influenced. Package names inside a
transitive dependency's SBOM, or the text of an uploaded document, reach the
model verbatim, and the model is authenticated as a real user with real
permissions.

Scopes are the boundary, but a boundary alone assumes the token is correctly
scoped. The additional layers, in `sbomify/apps/mcp/limits.py` and the registry:

* **No destructive tools exist.** `registry.register` refuses any `*:delete` or
  `*:administer` action outright, so the tool surface cannot grow one by
  accident. An injected "delete everything" has nothing to call, regardless of
  what the token permits. Deletion stays a human action.
* **Resource caps** on uploads, on artifacts parsed from storage, and on
  response size, so a coerced agent cannot exhaust memory or storage.
* **A separate write throttle** (`AccessTokenHeavyRateThrottle`), matching what
  the REST API applies to uploads.
* **A per-call audit trail** (`mcp_tool_call`), carrying outcome, tool, token,
  user, and workspace, never arguments or artifact content, which would put the
  SBOM in the log.
* **Provenance marking**: artifact-derived text is truncated per field, and the
  server instructions tell the model to treat it as data rather than
  instructions.
* **Nothing is advertised to an unauthenticated caller.** `tools/list` without a
  valid token returns an empty list: every tool would refuse anyway, and an
  empty list tells a misconfigured client exactly what is wrong.

The honest limit: none of this prevents an injection from making an agent
*report* something misleading. It bounds what the agent can *do*. Users should
treat agent summaries of third-party artifact content with the same suspicion as
the artifact itself.

`sbomify/apps/mcp/tests/test_security.py` encodes these as adversarial tests and
is the first place to extend when a tool is added.

## Consequences

### Operational constraints this imposes

* **Stateless HTTP is mandatory.** Production runs two gunicorn workers across
  two replicas, four processes with no session affinity, so a stateful MCP
  session would break on its second request. The server sets
  `stateless_http=True, json_response=True`.
* **The session manager must be started during ASGI lifespan.** Its anyio task
  group is entered in `LifespanApp` in `sbomify/asgi.py`; without it every
  request fails with "Task group is not initialized". `LifespanApp` is the sole
  owner: the MCP Starlette app declares its own lifespan, which we
  deliberately never drive.
* **Every tool must be `async`.** In mcp 1.28 a synchronous tool function is
  called directly on the event loop with no thread offload, where Django ORM
  access raises `SynchronousOnlyOperation`. Tools wrap ORM work in
  `sync_to_async`.
* **Host allow-listing.** The SDK enables DNS-rebinding protection by default
  with a localhost-only allow-list, which 421s every request behind a real
  hostname. `sbomify/apps/mcp/server.py` derives the allow-list from
  `APP_BASE_URL`, extendable via `MCP_ALLOWED_HOSTS`. Since the MCP app bypasses
  Django middleware, `DynamicHostValidationMiddleware` does not cover `/mcp`, so
  this check is worth keeping rather than disabling. Custom tenant domains are
  excluded: MCP is served only on the canonical host.
* **Throttling is re-applied in the MCP layer.** `AccessTokenRateThrottle` is
  bound to the `NinjaAPI` object, which `/mcp` bypasses.
* **The `mcp` dependency is pinned below 2.0.** The v2 line renames the server
  class (`FastMCP` → `MCPServer`) and was still a release candidate when this
  was written. Migrating is tracked as follow-up work.

### Deliberately out of scope

* **Cross-workspace dependency search** ("which components ship log4j?"): the
  obvious high-value tool, but `SBOM` stores metadata only; the `licenses` and
  `packages_licenses` fields were removed, so package data lives solely in the
  S3 artifact. Answering this per query would mean fetching and parsing every
  SBOM in the workspace. It needs an indexed package table first, which is its
  own project. `get_sbom_packages` covers the single-SBOM case.
* **Triage, CRA compliance steps, control status, and workspace
  administration.** The initial surface is reads, artifact publishing, and
  contact-profile management.
* **Deletion of anything.** Structurally excluded, per the injection discussion
  above, not merely unimplemented.
* **MCP resources and prompts.** Tools only, for now.

### Costs

The tool set is hand-maintained, so a new capability needs a deliberate decision
about whether an agent should have it. A cost, but also the point. Tools that
wrap REST views inherit their response shapes, so a breaking change there
surfaces in MCP; the scope-enforcement test matrix in
`sbomify/apps/mcp/tests/` is what catches it.
