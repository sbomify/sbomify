# MCP server operations

sbomify serves a [Model Context Protocol](https://modelcontextprotocol.io) endpoint at `/mcp` so AI
agents can query a workspace and publish artifacts using scoped personal access tokens.

**Why is it built this way?** See [ADR-0009](ADR/0009-mcp-server.md).

Connecting a client is below. The rest of this page is the operator reference: the settings that
govern the endpoint, and what to do when it misbehaves. Those knobs are read by code in this
repository and should change alongside it.

## Connecting a client

The endpoint is `/mcp` under `APP_BASE_URL`, so `https://<your sbomify host>/mcp`, or `http://` on a
deployment whose `APP_BASE_URL` is plain HTTP. It speaks streamable HTTP. Authenticate with a
personal access token, sent as a bearer token.

1. Create a token under Settings, Access tokens. Scope it to one workspace and to the actions the
   agent actually needs. Scopes are not advisory: a token with no write scope is never shown
   `upload_artifact`, and would be refused if it called it anyway.
2. Point the client at the endpoint. For a client that reads `mcpServers` configuration:

   ```json
   {
     "mcpServers": {
       "sbomify": {
         "url": "https://app.sbomify.com/mcp",
         "headers": { "Authorization": "Bearer YOUR_TOKEN" }
       }
     }
   }
   ```

3. Ask the agent to list its tools. `tools/list` is filtered by the token's scopes, so what comes
   back is the reference for that token. The tools cover the workspace and its products,
   components, releases, artifacts, documents, vulnerabilities, assessments, advisories, contact
   profiles, suppliers, lifecycle events, security controls, CRA assessments and licenses.

Give each agent its own token. Rate limits are per token, so an agent that shares one with CI shares
its budget.

No tool deletes anything. Destructive actions are refused at registration, so "delete our SBOMs" has
nothing to call.

Some writes stay with a person in sbomify, because they publish, attest or administer:

- publishing an advisory, and changing product or component visibility;
- generating the VDP, security.txt or Declaration of Conformity, saving CRA step 3 (it fills the
  public security.txt) and finishing the assessment;
- Article 14 reports, filings with ENISA, and signing a declaration or an export;
- recording lifecycle events and support definitions, which are permanent and public over TEA;
- uploading an artifact's signature or provenance, which CI does once per artifact;
- approving VEX submissions, advisory changes and access requests;
- workspace administration: control statuses and evidence, catalog changes and plugin settings.

Some tools that are offered still need an admin-tier scope (`workspace:manage`) and an owner or admin
role: supplier writes, creating or editing a contact profile, and the CRA wizard writes.

### Signing in instead of using a token

A client that speaks MCP OAuth, such as Claude Code, can connect with no token to copy. In Claude
Code that is `claude mcp add --transport http sbomify https://<your sbomify host>/mcp`, then
Authenticate in `/mcp`: a browser opens on the sbomify sign-in page, and the session is connected.

The client calls `/mcp`, gets a `401` pointing at `/.well-known/oauth-protected-resource/mcp`, and
signs the person in through the Keycloak realm. An OAuth session reads whatever the person's role
lets them read and writes nothing. Writes still need a personal access token. The person must have
signed in to sbomify in the browser once, so their account exists.

The realm needs three things. The development bootstrap (`bin/keycloak-bootstrap.sh`) sets them; a
production realm needs an operator to set them:

| What | Why |
| --- | --- |
| A client scope `mcp`, with an audience mapper adding `<APP_BASE_URL>/mcp` to the access token | `/mcp` accepts only a token whose `aud` names it, so a token issued to the web app is refused |
| `mcp` as a realm optional client scope | A client registered on the fly may only ask for the realm's default scopes |
| A client registration policy that admits the clients to allow | Claude Code registers with an `http://localhost:<port>/callback` redirect |

The kind stack under `deploy/local` has its own realm bootstrap, which sets none of these up yet, so
MCP OAuth does not work there. Use a personal access token on that stack.

## Settings

| Setting | Purpose |
| --- | --- |
| `APP_BASE_URL` | Its hostname is added to the MCP `Host` allow-list |
| `MCP_ALLOWED_HOSTS` | Comma-separated extra hostnames (staging aliases, extra CNAMEs) |
| `MCP_MAX_UPLOAD_BYTES` | Largest artifact an MCP tool accepts (default: `DATA_UPLOAD_MAX_MEMORY_SIZE`, 100 MB) |
| `MCP_MAX_ARTIFACT_PARSE_BYTES` | Largest stored artifact `get_artifact_packages` will parse (default 25 MB). Parsing takes two to four times an SBOM's size in memory; a document built of so many small parts that it would take more than eight times this is refused too |
| `MCP_MAX_RESPONSE_BYTES` | Ceiling on one tool's response (default 1 MB) |
| `MCP_MAX_REQUEST_BYTES` | Largest request body from a token that cannot upload artifacts; a larger one is refused before it is read (default 1 MiB) |
| `MCP_MAX_CONCURRENT_REQUESTS` | MCP requests one worker process runs at once; more wait up to 5 s, then get a 503 with `Retry-After` (default 8) |
| `MCP_MAX_CONCURRENT_UPLOADS` | Of those, requests whose body is over `MCP_MAX_REQUEST_BYTES` or of unstated size, such as `upload_artifact`; more wait the same way (default 2) |

Per-token rate limiting is shared with the REST API (`API_TOKEN_RATE_LIMIT`), with the stricter
`API_TOKEN_HEAVY_RATE_LIMIT` applied to the tools that write. An agent and a CI job sharing a token
share one budget, so give agents their own.

Every `/mcp` request is authenticated and charged once, from its headers, before its body is read,
so a malformed call costs the same as a valid one. A token over its budget gets a 429 with
`Retry-After`.

## Logs

Two structured audit streams cover MCP traffic:

- `sbomify.audit.mcp`: one `mcp_tool_call` event per invocation, carrying outcome, tool, token,
  user and workspace. Deliberately never arguments or artifact content; logging those would put
  whole SBOMs in the log. A request refused before its credential resolves (no bearer token, an
  unknown or expired one, or an address over its budget) gets one event too, with the client
  address and no token fields. So does an authenticated call the server rejects before any tool
  runs (unparseable JSON, an unknown tool, arguments that fail the tool's schema, a body over its
  size cap or too slow to arrive): outcome `invalid_request`, tool `request`, and the error code
  (or `body_too_large`, `body_timeout`) as the detail, never the input.
- `sbomify.audit.token_auth`: the existing token-authentication events. MCP requests appear with an
  `attempted_action` of `mcp request`; the `mcp_tool_call` event names the tool.

## Troubleshooting

**421 Misdirected Request**: the `Host` header is not in the allow-list. The MCP SDK enables
DNS-rebinding protection with a localhost-only default, which rejects every request behind a real
hostname; the allow-list is derived from `APP_BASE_URL`. Set `MCP_ALLOWED_HOSTS` for any additional
hostname that should serve MCP.

Note this check is load-bearing here in a way it is not elsewhere: the MCP app is dispatched before
Django's middleware stack, so `DynamicHostValidationMiddleware` does not cover `/mcp`.

**"Task group is not initialized"**: the ASGI server is not delivering lifespan events. The MCP
session manager's task group is started in `LifespanApp` (`sbomify/asgi.py`), which owns it
exclusively. Gunicorn with `uvicorn_worker.UvicornWorker` drives this correctly; a WSGI server will
not.

**Stale database connections after a Postgres restart**: should not occur. `/mcp` bypasses Django's
handler and therefore its `request_finished` signal, so tools reach the ORM through channels'
`database_sync_to_async`, which calls `close_old_connections` around each call. If you see
`InterfaceError` persisting on `/mcp` while REST requests recover, that wiring is the place to look.

**413 on a tool call**: the request body is over `MCP_MAX_REQUEST_BYTES` and the token cannot upload
artifacts. Only an upload needs a body that large.

**429 with `Retry-After`**: the token, or for a request without a usable token its address, is over
its rate limit. The body was not read.

**401 on every call**: the caller presented no token, or one that is unknown, expired or revoked. The
body was not read. A client that speaks MCP OAuth starts its sign-in from this 401.

**408 on a tool call**: the request body took longer than 30 seconds to arrive, or 300 seconds from a
token that may upload. A request holds one of the worker's slots while its body arrives, so the
server stops waiting.

## Deployment notes

- The server is **stateless** (`stateless_http=True`). Production runs multiple worker processes with
  no session affinity, so a stateful session would break on its second request.
- **No Caddy configuration is needed.** The catch-all `reverse_proxy` already forwards `/mcp`.
- MCP is served only on the canonical application hostname, not on custom tenant domains.
- The `mcp` dependency is pinned `<2`; the v2 line renames the server class.
