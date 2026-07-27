# MCP server

sbomify exposes a [Model Context Protocol](https://modelcontextprotocol.io)
server so AI agents can query your workspace and publish artifacts using your
own permissions. It is served by the main app at `/mcp` over streamable HTTP.

Design rationale lives in [ADR-0008](ADR/0008-mcp-server.md).

## Setup

### 1. Create a scoped token

Create a personal access token in **Workspace settings → Access tokens**. Pick
the narrowest access scope the agent needs:

| Scope preset | What the agent can do |
| --- | --- |
| `read_only` | Read products, components, releases, SBOMs, documents, vulnerabilities, assessments |
| `publish` | The read-only release tools plus uploading SBOMs and cutting/tagging releases |
| `full` | Everything, including VEX publishing |

Start with `read_only`. Give the agent a **dedicated** token — one token per
consumer keeps `last_used_at` attributable and shrinks the blast radius if it
leaks. See [access-tokens.md](access-tokens.md).

### 2. Register the server with your client

#### Claude Code

```bash
claude mcp add --transport http sbomify https://app.sbomify.com/mcp \
  --header "Authorization: Bearer $SBOMIFY_TOKEN"
```

#### Clients using a JSON config file

```json
{
  "mcpServers": {
    "sbomify": {
      "type": "http",
      "url": "https://app.sbomify.com/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN_HERE" }
    }
  }
}
```

Self-hosted: replace the host with your own. MCP is served only on the canonical
app hostname, not on custom tenant domains.

### 3. Check it works

```bash
curl -sS -X POST https://app.sbomify.com/mcp \
  -H "Authorization: Bearer $SBOMIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

You should get back the tools your token's scopes permit.

## Tools

The tool list you see is filtered to what your token can actually invoke — a
`read_only` token is never shown `upload_sbom`. This is convenience, not the
security boundary: every call is independently authorized, so widening what a
client asks for does not widen what it gets.

### Reading

| Tool | Purpose |
| --- | --- |
| `get_workspace_summary` | Workspace name and object counts — the usual starting point |
| `list_products` / `get_product` | Products, with identifiers, links and components |
| `list_components` / `get_component` | Components and their recent artifacts |
| `list_releases` / `get_release` | Releases and their tagged artifacts |
| `list_sboms` / `get_sbom` | SBOM metadata (not the document itself) |
| `get_sbom_packages` | Packages an SBOM declares — paginated, with `name_filter` |
| `list_documents` | Documents attached to a component |
| `get_assessments` | Compliance/licence assessment results (NTIA, etc.) |
| `get_vulnerability_summary` | Severity counts, filterable by product/component/release |
| `list_vulnerabilities` | Individual findings, traceable to component and SBOM |
| `get_release_risk_report` | Release + artifacts + vulnerabilities + compliance in one call |

### Contact profiles

Contact profiles are the reusable supplier/author records that populate the
supplier fields of generated SBOMs — the ones NTIA minimum-elements checks look
for. `list_contact_profiles` and `get_contact_profile` need only
`workspace:read`; the rest are writes.

| Tool | Required scope |
| --- | --- |
| `list_contact_profiles` / `get_contact_profile` | `workspace:read` |
| `create_contact_profile` | `workspace:manage` |
| `update_contact_profile` | `workspace:manage` |
| `assign_contact_profile` | `component:manage` |

Neither `workspace:manage` nor `component:manage` is in the `read_only` or
`publish` presets, so a token must be scoped for profile management explicitly.
Editing entity details (addresses, per-contact emails) and deleting profiles are
not exposed over MCP.

### Publishing

| Tool | Required scope |
| --- | --- |
| `upload_sbom` | `artifact:publish` |
| `upload_vex` | `artifact:publish_vex` |
| `create_release` | `release:create` |
| `tag_artifact_to_release` | `release:tag` |

Uploaded artifacts are stored byte-for-byte as supplied (ADR-004).

## Security model

The MCP endpoint is a higher-risk surface than the REST API for one reason: the
caller is an LLM, and an LLM's inputs are often attacker-influenced. A package
name inside a dependency's SBOM, or the text of an uploaded document, can carry
instructions aimed at the agent reading them — and the agent is authenticated as
you.

The defences layer as follows, strongest first:

1. **Token scopes are the boundary.** `can()` checks the token's scopes before
   the role check, so nothing said in a prompt can widen what a token may do. A
   read-only token that is told to publish is refused.
2. **Destructive tools do not exist.** No `*:delete` or `*:administer` action is
   registered, and the registry refuses to accept one. "Delete all our SBOMs"
   has no tool to reach for, whatever the token permits. Deletion stays a human
   action in the web UI or REST API.
3. **Resource caps.** Uploads are capped (default 20 MB), stored artifacts are
   size-checked before parsing, responses are capped, and every list paginates.
4. **Separate write throttle.** Mutating tools carry the stricter per-token
   budget the REST API applies to uploads, on top of the global one.
5. **Audit trail.** Every tool call emits a structured `mcp_tool_call` event with
   outcome, tool, token, user and workspace — never arguments or artifact
   content. Combined with the existing `token_auth` events, an abuse pattern is
   reconstructable.
6. **Provenance marking.** Artifact-derived text is truncated per field, and the
   server instructions tell the model to treat it as data, never instructions.

**What this does not do:** it cannot stop a sufficiently persuasive injection
from making an agent *report* something misleading to you. Treat agent summaries
of third-party artifact content the way you would treat the artifact itself.

Practical advice: give agents `read_only` tokens unless they specifically need
to publish, and use a separate short-lived token for any agent that does.

## Notes and limits

- **Workspace scoping.** A workspace-pinned token acts only in that workspace.
  Legacy tokens with no workspace fall back to your default workspace; rotate
  them.
- **Large SBOMs.** `get_sbom_packages` always paginates (max 100 per page). To
  check for a specific dependency, pass `name_filter` rather than paging
  through everything.
- **No cross-workspace dependency search yet.** Asking "which components ship
  log4j?" would require parsing every SBOM in object storage on each query;
  package data is not indexed in the database. Use `get_sbom_packages` per SBOM
  until an index exists.
- **Vulnerability numbers match the dashboards.** Counts merge findings across
  scan providers (so an SBOM scanned by both OSV and Dependency-Track is not
  double-counted), drop provider bookkeeping rows, and exclude findings already
  dispositioned via VEX. Pass `include_suppressed: true` to
  `list_vulnerabilities` to see suppressed findings with their VEX state.
- **Unknown ids are errors, not empty results.** Passing a component or product
  id that does not exist, or belongs to another workspace, raises a not-found
  rather than reporting zero vulnerabilities.
- **Rate limiting.** MCP calls share the per-token budget with the REST API
  (`API_TOKEN_RATE_LIMIT`). Agents are chattier than CI, so watch for 429s if a
  token is shared between the two.
- **Duplicate uploads.** Re-uploading an SBOM with the same version and format
  fails as a duplicate. That is expected behaviour, not a transient error worth
  retrying.

## Operating

| Setting | Purpose |
| --- | --- |
| `APP_BASE_URL` | Its hostname is added to the MCP `Host` allow-list |
| `MCP_ALLOWED_HOSTS` | Comma-separated extra hostnames (staging aliases, extra CNAMEs) |
| `MCP_MAX_UPLOAD_BYTES` | Largest artifact an MCP tool accepts (default 20 MB) |
| `MCP_MAX_ARTIFACT_PARSE_BYTES` | Largest stored SBOM `get_sbom_packages` will parse (default 50 MB) |
| `MCP_MAX_RESPONSE_BYTES` | Ceiling on one tool's response (default 1 MB) |

Audit events are emitted on the `sbomify.audit.mcp` logger as `mcp_tool_call`,
alongside the existing `sbomify.audit.token_auth` events.

If MCP requests return **421 Misdirected Request**, the `Host` header is not in
the allow-list — set `MCP_ALLOWED_HOSTS`.

If they return **"Task group is not initialized"**, the ASGI server is not
running lifespan events. The MCP session manager is started in `LifespanApp`
(`sbomify/asgi.py`); gunicorn with `uvicorn_worker.UvicornWorker` drives this
correctly.
