"""Security advisory tools: read the workspace's advisories, draft one, and keep it up to date.

Reads are unambiguous. Drafting is the workflow worth having: an agent that has
just read `list_vulnerabilities` is exactly the thing that should be able to
open an advisory about what it found, and a new advisory is a draft, internal
and revisable, with no tracking id until someone publishes it.

The edits (fields, product statuses, products, timeline updates) follow from
that: an agent keeps shaping its draft, and a published advisory needs the same
work as the fix lands. A published advisory is what customers read on the trust
center, though, and a person makes the public statement. The REST views already
hold an AI agent token's write to one for a person to approve. Any other token
would write it straight through, so these tools refuse that case and point to
the agent token.

Publishing and withdrawing are not exposed, and the registry refuses
``advisory:publish`` and every ``delete`` outright.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from .. import serializers
from ..auth import Principal, require
from ._base import DETAIL_COLLECTION_LIMIT, clamp_page, mcp_tool, not_found, resolve_workspace, run_db, unwrap_view

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class AdvisoryChange(BaseModel):
    """The advisory fields to change. A field left out keeps its value; `cvss_score` null clears the CVSS entry."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=255)
    summary: str | None = Field(None, description="The one-paragraph summary the trust center leads with.")
    description: str | None = None
    severity: str | None = Field(None, description="critical, high, medium, low or none.")
    cvss_score: float | None = None
    cvss_vector: str | None = None


class ProductStatusChange(BaseModel):
    """One product's status on an advisory. Only the fields sent are written; null clears one."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(None, description="exploitable, not_affected, false_positive, in_triage or resolved.")
    justification: str | None = Field(None, description="Why a not_affected product is not affected.")
    response: str | None = Field(
        None, description="can_not_fix, will_not_fix, update, rollback or workaround_available."
    )
    impact_statement: str | None = None
    action_statement: str | None = Field(None, description="What users should do. Shown to readers.")
    recommended_version: str | None = None
    recommended_release_id: str | None = Field(None, description="A release of this product.")
    fixed_version: str | None = Field(None, description="The first version that carries the fix.")
    fixed_release_id: str | None = Field(None, description="A release of this product that carries the fix.")


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
            return serializers.advisory(result.value, detail_limit=DETAIL_COLLECTION_LIMIT)

        return await run_db(query)

    @mcp_tool(mcp, "create_advisory", "advisory:manage", writes=True, idempotent=False)
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
            return serializers.advisory(result.value, detail_limit=DETAIL_COLLECTION_LIMIT)

        return await run_db(call)

    @mcp_tool(mcp, "update_advisory", "advisory:manage", writes=True, idempotent=False)
    async def update_advisory(
        principal: Principal, advisory_id: str, changes: AdvisoryChange, context: str = ""
    ) -> dict[str, Any]:
        """Change an advisory's title, summary, description, severity or CVSS.

        On a draft the change is written at once. On a published advisory it is
        held for a person to approve, which needs an AI agent token: the result
        has `held_for_approval` true and the `proposal`. Say in `context` what
        you changed and why, for the person approving it.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.security_advisories import apis
            from sbomify.apps.security_advisories.schemas import UpdateAdvisorySchema

            payload = UpdateAdvisorySchema(**changes.model_dump(exclude_unset=True), context=context)
            return _write(principal, advisory_id, lambda request: apis.update_advisory(request, advisory_id, payload))

        return await run_db(call)

    @mcp_tool(mcp, "set_advisory_product_status", "advisory:manage", writes=True, idempotent=False)
    async def set_advisory_product_status(
        principal: Principal, advisory_id: str, product_id: str, change: ProductStatusChange, context: str = ""
    ) -> dict[str, Any]:
        """Set how a product on the advisory is affected, and where its fix is.

        Applies to every vulnerability the advisory lists for that product. A
        resolved advisory refuses moving a product back to in_triage or
        exploitable. On a published advisory the change is held for a person to
        approve, as `update_advisory` describes.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.security_advisories import apis
            from sbomify.apps.security_advisories.schemas import ProductStatusUpdateSchema

            payload = ProductStatusUpdateSchema(**change.model_dump(exclude_unset=True), context=context)
            return _write(
                principal,
                advisory_id,
                lambda request: apis.update_product_statuses(request, advisory_id, product_id, payload),
            )

        return await run_db(call)

    @mcp_tool(mcp, "add_advisory_product", "advisory:manage", writes=True, idempotent=False)
    async def add_advisory_product(
        principal: Principal,
        advisory_id: str,
        product_id: str,
        affected_release_ids: list[str] | None = None,
        change: ProductStatusChange | None = None,
        context: str = "",
    ) -> dict[str, Any]:
        """Name another affected product on the advisory, or more of its affected releases.

        `change` sets the new product's status; without it the product starts
        under investigation, which a resolved advisory refuses. On a published
        advisory the change is held for a person to approve, as
        `update_advisory` describes.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.security_advisories import apis
            from sbomify.apps.security_advisories.schemas import AddAdvisoryProductSchema

            payload = AddAdvisoryProductSchema(
                product_id=product_id,
                affected_release_ids=list(affected_release_ids or []),
                context=context,
                **(change.model_dump(exclude_unset=True) if change else {}),
            )
            return _write(
                principal, advisory_id, lambda request: apis.add_advisory_product(request, advisory_id, payload)
            )

        return await run_db(call)

    @mcp_tool(mcp, "post_advisory_update", "advisory:manage", writes=True, idempotent=False)
    async def post_advisory_update(
        principal: Principal, advisory_id: str, kind: str, note: str = "", context: str = ""
    ) -> dict[str, Any]:
        """Add an entry to the advisory's timeline.

        `kind` is "update" for a note that moves nothing, or the remediation
        status it moves to: identified, investigating, fix_in_progress,
        resolved or wont_fix. `note` is Markdown. On a published advisory the
        entry is held for a person to approve, as `update_advisory` describes.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.security_advisories import apis
            from sbomify.apps.security_advisories.schemas import AdvisoryUpdateSchema

            payload = AdvisoryUpdateSchema(kind=kind, note=note, context=context)
            return _write(
                principal, advisory_id, lambda request: apis.post_advisory_update(request, advisory_id, payload)
            )

        return await run_db(call)

    @mcp_tool(mcp, "list_advisory_proposals", "advisory:read")
    async def list_advisory_proposals(principal: Principal, status: str = "", since: str = "") -> dict[str, Any]:
        """The changes this token proposed to published advisories, and what a person decided.

        Newest decision first, at most 100. A rejection carries
        `rejection_reason`, `decision_note` and `next_step`: what was wrong and
        what to do about it. `status` narrows to pending, approved, rejected or
        superseded; `since` (ISO 8601) to what was decided, or sent, after it.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.security_advisories import apis

            resolve_workspace(principal)
            try:
                after = datetime.fromisoformat(since) if since else None
            except ValueError as exc:
                raise ToolError(f"since must be an ISO 8601 date or time, not {since!r}.") from exc
            rows = unwrap_view(apis.list_sent_proposals(principal.request, status, after), action="Listing proposals")
            return {"items": rows["result"]}

        return await run_db(call)


def _write(principal: Principal, advisory_id: str, write: Callable[[Any], tuple[int, Any]]) -> dict[str, Any]:
    """Run one advisory edit through its REST view, as MCP allows it, and answer in one shape.

    The view itself holds an AI agent token's write to a published advisory
    for approval. Any other token's would change what the trust center shows
    with nobody reading it first, so that case is refused here. The advisory
    stays locked from this check to the end of the write, so it cannot be
    published in between.
    """
    from django.db import transaction

    from sbomify.apps.core.authz import credential_channel
    from sbomify.apps.security_advisories.models import SecurityAdvisory
    from sbomify.apps.security_advisories.services import advisories as service

    team = resolve_workspace(principal)
    with transaction.atomic():
        advisory = service._locked_advisory(team, advisory_id)
        if advisory is None:
            raise not_found("Advisory", advisory_id)
        if advisory.status != SecurityAdvisory.Status.DRAFT and credential_channel(principal.request) != "agent":
            raise ToolError(
                "This advisory is published, so a change to it must be approved by a person first. Over MCP that "
                "needs an API token made with the AI agent preset; otherwise make the change in sbomify."
            )
        status, body = write(principal.request)
    if status == 202:
        return {"held_for_approval": True, "proposal": unwrap_view((status, body), action="Proposing the change")}
    unwrap_view((status, body), action="Updating the advisory")
    result = service.get_advisory(team, advisory_id)
    if not result.ok or result.value is None:
        raise ToolError("The advisory was updated but could not be read back.")
    return {
        "held_for_approval": False,
        "advisory": serializers.advisory(result.value, detail_limit=DETAIL_COLLECTION_LIMIT),
    }


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
