"""Security advisory tools: read the workspace's advisories, draft a new one.

Three of the eight internal advisory endpoints are exposed, which is a decision
rather than an oversight.

Reads are unambiguous. Drafting is the workflow worth having: an agent that has
just read `list_vulnerabilities` is exactly the thing that should be able to
open an advisory about what it found, and a new advisory is a draft, internal
and revisable, with no tracking id until someone publishes it.

Publishing, withdrawing and posting timeline updates are not exposed. Each one
changes what customers read on the trust center, and the authz model already
treats outward-facing changes as a different class from routine work: visibility
is carved up to ADMINISTER for the same reason. A person makes the public
statement. `delete` is refused by the registry for every resource, so no
decision was available there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal, require
from ._base import clamp_page, mcp_tool, not_found, resolve_workspace, run_db, unwrap_view

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

#: Publication states, for the ``publication_status`` filter. Held here rather
#: than imported so this module keeps its Django imports lazy, like every other
#: tool module; ``test_advisories`` holds it to the model's own choices.
PUBLICATION_STATES = ("draft", "published", "withdrawn")


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "list_advisories", "advisory:read")
    async def list_advisories(
        principal: Principal,
        search: str | None = None,
        publication_status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List the workspace's security advisories, newest first.

        `search` matches the title, the workspace's tracking id, and any CVE the
        advisory cites. `publication_status` narrows to draft, published or
        withdrawn, which is separate from `remediation_status`: one says whether
        customers can read it, the other says where the fix is.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.security_advisories.services import advisories as service

            team = resolve_workspace(principal)
            # A token scope only narrows; the role still has to permit the read.
            # advisory:read is READ_INTERNAL, which excludes bot, and an
            # unscoped token (every OIDC one) passes the registry filter
            # untouched, so without this there is no authorization left.
            require(principal, "advisory:read", team)
            wanted = _publication_state(publication_status)
            safe_page, safe_size = clamp_page(page, page_size)
            # Filtered and sliced in the database. Projecting the whole
            # workspace to show twenty-five rows meant a four-way prefetch and a
            # timeline build per advisory, discarded.
            result = service.list_advisories_page(
                team,
                search or "",
                status=wanted,
                offset=(safe_page - 1) * safe_size,
                limit=safe_size,
            )
            if not result.ok or result.value is None:
                raise ToolError(result.error or "Could not list advisories.")

            rows, total = result.value
            return serializers.paginated(
                [serializers.advisory(row) for row in rows],
                page=safe_page,
                page_size=safe_size,
                total=total,
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_advisory", "advisory:read")
    async def get_advisory(principal: Principal, advisory_id: str) -> dict[str, Any]:
        """One advisory in full: its vulnerabilities, references and timeline.

        Accepts the tracking id as well as the internal id, because the tracking
        id is what the advisory is published under and what a person quotes.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.security_advisories.services import advisories as service

            team = resolve_workspace(principal)
            require(principal, "advisory:read", team)
            result = service.get_advisory(team, advisory_id)
            if not result.ok or result.value is None:
                # The service scopes to the workspace and reports another
                # workspace's advisory as absent, which is the uniform
                # not-found every other tool gives.
                raise not_found("Advisory", advisory_id)
            return serializers.advisory(result.value, detail=True)

        return await run_db(query)

    @mcp_tool(mcp, "create_advisory", "advisory:manage", writes=True)
    async def create_advisory(
        principal: Principal,
        title: str,
        severity: str = "",
        description: str = "",
        identifier: str = "",
        cvss_score: float | None = None,
        cvss_vector: str = "",
        product_ids: list[str] | None = None,
        affected_release_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Open a draft security advisory.

        The result is a draft: internal, editable, and carrying no tracking id
        until a person publishes it. This tool cannot publish, withdraw, or post
        an update to one, because those are what customers see.

        `identifier` is the CVE or other id the advisory is about.
        `affected_release_ids` must name releases of the products in
        `product_ids`; ids from another workspace name nothing rather than
        attaching something the caller cannot see.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.security_advisories import apis
            from sbomify.apps.security_advisories.schemas import CreateAdvisorySchema
            from sbomify.apps.security_advisories.services import advisories as service

            # Resolved once and reused: the view checks advisory:manage itself,
            # so this is here to fail a workspace-less token the way every read
            # does rather than through the view's 403.
            team = resolve_workspace(principal)
            payload = CreateAdvisorySchema(
                title=title,
                severity=severity,
                description=description,
                identifier=identifier,
                cvss_score=cvss_score,
                cvss_vector=cvss_vector,
                product_ids=list(product_ids or []),
                affected_release_ids=list(affected_release_ids or []),
            )
            created = unwrap_view(apis.create_advisory(principal.request, payload), action="Advisory creation")

            # Re-read through the service so create and get answer in the same
            # shape. The view returns the REST contract, where "status" is the
            # publication state; the projection uses that name for remediation.
            # Serializing the view's output directly would swap the two axes
            # with nothing to notice it.
            result = service.get_advisory(team, str(created.get("id", "")))
            if not result.ok or result.value is None:
                raise ToolError("Advisory was created but could not be read back.")
            return serializers.advisory(result.value, detail=True)

        return await run_db(call)


def _publication_state(value: str | None) -> str | None:
    """The requested publication state, or ``None`` for every state.

    An unrecognised value is named rather than ignored: a filter that quietly
    matches nothing would have the agent report an empty workspace.
    """
    if value is None:
        return None
    wanted = value.strip().lower()
    if wanted not in PUBLICATION_STATES:
        raise ToolError(f"Unknown publication_status {value!r}; expected one of {', '.join(PUBLICATION_STATES)}.")
    return wanted
