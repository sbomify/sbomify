# MCP server — operations

sbomify serves a [Model Context Protocol](https://modelcontextprotocol.io) endpoint at `/mcp` so AI
agents can query a workspace and publish artifacts using scoped personal access tokens.

**Setting it up as a user?** See the [MCP guide](https://sbomify.com/guides/mcp/) — token scoping,
client configuration, the tool reference, and the security model.

**Why it is built this way?** See [ADR-0008](ADR/0008-mcp-server.md).

This page is the operator reference: the settings that govern the endpoint, and what to do when it
misbehaves. It lives here rather than on the website because these knobs are read by code in this
repository and should change alongside it.

## Settings

| Setting | Purpose |
| --- | --- |
| `APP_BASE_URL` | Its hostname is added to the MCP `Host` allow-list |
| `MCP_ALLOWED_HOSTS` | Comma-separated extra hostnames (staging aliases, extra CNAMEs) |
| `MCP_MAX_UPLOAD_BYTES` | Largest artifact an MCP tool accepts (default: `DATA_UPLOAD_MAX_MEMORY_SIZE`, 20 MB) |
| `MCP_MAX_ARTIFACT_PARSE_BYTES` | Largest stored SBOM `get_sbom_packages` will parse (default 50 MB) |
| `MCP_MAX_RESPONSE_BYTES` | Ceiling on one tool's response (default 1 MB) |

Per-token rate limiting is shared with the REST API (`API_TOKEN_RATE_LIMIT`), with the stricter
`API_TOKEN_HEAVY_RATE_LIMIT` applied to the tools that write. An agent and a CI job sharing a token
share one budget, so give agents their own.

## Logs

Two structured audit streams cover MCP traffic:

- `sbomify.audit.mcp` — one `mcp_tool_call` event per invocation, carrying outcome, tool, token,
  user and workspace. Deliberately never arguments or artifact content; logging those would put
  whole SBOMs in the log.
- `sbomify.audit.token_auth` — the existing token-authentication events. MCP calls appear with an
  `attempted_action` of `mcp <tool_name>`.

## Troubleshooting

**421 Misdirected Request** — the `Host` header is not in the allow-list. The MCP SDK enables
DNS-rebinding protection with a localhost-only default, which rejects every request behind a real
hostname; the allow-list is derived from `APP_BASE_URL`. Set `MCP_ALLOWED_HOSTS` for any additional
hostname that should serve MCP.

Note this check is load-bearing here in a way it is not elsewhere: the MCP app is dispatched before
Django's middleware stack, so `DynamicHostValidationMiddleware` does not cover `/mcp`.

**"Task group is not initialized"** — the ASGI server is not delivering lifespan events. The MCP
session manager's task group is started in `LifespanApp` (`sbomify/asgi.py`), which owns it
exclusively. Gunicorn with `uvicorn_worker.UvicornWorker` drives this correctly; a WSGI server will
not.

**Stale database connections after a Postgres restart** — should not occur. `/mcp` bypasses Django's
handler and therefore its `request_finished` signal, so tools reach the ORM through channels'
`database_sync_to_async`, which calls `close_old_connections` around each call. If you see
`InterfaceError` persisting on `/mcp` while REST requests recover, that wiring is the place to look.

**Empty `tools/list`** — the caller presented no token or an invalid one. Unauthenticated callers are
deliberately offered nothing, since every tool would refuse them anyway.

## Deployment notes

- The server is **stateless** (`stateless_http=True`). Production runs multiple worker processes with
  no session affinity, so a stateful session would break on its second request.
- **No Caddy configuration is needed.** The catch-all `reverse_proxy` already forwards `/mcp`.
- MCP is served only on the canonical application hostname, not on custom tenant domains.
- The `mcp` dependency is pinned `<2`; the v2 line renames the server class.
