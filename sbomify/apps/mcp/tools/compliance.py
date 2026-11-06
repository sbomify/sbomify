"""CRA compliance tools: the conformity assessment wizard and Article 14 reports.

Every tool delegates to the compliance REST view, so the billing gate, the
owner-and-admin role check and the stale-assessment guard apply as they do over
REST.

Some acts stay with a person in sbomify, because they publish to the trust
center or attest to something:

- generating the VDP, security.txt or EU Declaration of Conformity, which a
  public product's trust center serves as soon as they exist. Refreshing stale
  documents and building an export regenerate them, so neither is a tool;
- saving step 3, which fills empty slots of the workspace's public
  security.txt from its vulnerability-handling answers;
- finishing the wizard (step 5), which puts the Declaration of Conformity on
  the trust center;
- signing the declaration or an export, and creating, editing or filing an
  Article 14 report, which authz treats as the same outward act as publishing
  an advisory (``cra_report:manage`` is refused at registration).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal
from ._base import clamp_page, mcp_tool, not_found, resolve_workspace, run_db
from .catalog import _lookup_product

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

FindingStatus = Literal["satisfied", "not-satisfied", "not-applicable", "unanswered"]

# The kinds no trust center serves. The other three (vdp, security_txt,
# declaration_of_conformity) are public the moment they are generated.
InternalDocumentKind = Literal[
    "risk_assessment",
    "user_instructions",
    "decommissioning_guide",
    "early_warning",
    "full_notification",
    "final_report",
]

# The wizard is owner and admin work, so its writes declare an admin-tier scope:
# a token scoped for day-to-day product work does not answer a conformity
# assessment.
_ASSESSOR = ("workspace:manage",)

# Steps a person saves in sbomify. Step 3 writes into the public security.txt,
# step 5 publishes the Declaration of Conformity.
_PERSON_STEPS = {
    3: "Step 3 fills the workspace's public security.txt, so a person saves it in sbomify. "
    "Answer its controls with update_cra_finding and add_cra_observation.",
    5: "Finishing the assessment publishes its EU Declaration of Conformity on the trust center, "
    "so a person finishes it in sbomify.",
}


def _unwrap(result: tuple[int, Any], *, action: str) -> Any:
    """A compliance view's ``(status, payload)`` as JSON data, or a ``ToolError``.

    The compliance views answer errors as ``{"error": ...}``, not the
    ``{"detail": ...}`` that ``unwrap_view`` reads, so its message would be lost.
    """
    status, payload = result
    if isinstance(payload, list):
        payload = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in payload]
    elif hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    if status >= 400:
        detail = payload.get("error") if isinstance(payload, dict) else payload
        raise ToolError(f"{action} failed ({status}): {detail}")
    return payload


def _lookup_assessment(principal: Principal, assessment_id: str) -> None:
    from sbomify.apps.compliance.models import CRAAssessment

    if not CRAAssessment.objects.filter(pk=assessment_id, team=resolve_workspace(principal)).exists():
        raise not_found("CRA assessment", assessment_id)


def _lookup_finding(principal: Principal, assessment_id: str, finding_id: str) -> Any:
    from sbomify.apps.compliance.models import OSCALFinding

    _lookup_assessment(principal, assessment_id)
    finding = (
        OSCALFinding.objects.filter(pk=finding_id, assessment_result__cra_assessment=assessment_id)
        .only("notes", "justification")
        .first()
    )
    if finding is None:
        raise not_found("finding", finding_id)
    return finding


def _lookup_report(principal: Principal, report_id: str) -> None:
    from sbomify.apps.compliance.models import CRAReport

    if not CRAReport.objects.filter(pk=report_id, team=resolve_workspace(principal)).exists():
        raise not_found("CRA report", report_id)


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "start_cra_assessment", "product:manage", writes=True, idempotent=True)
    async def start_cra_assessment(principal: Principal, product_id: str) -> dict[str, Any]:
        """Start the CRA conformity assessment for a product, or return the one it already has.

        A product has one assessment. The answer carries its id and progress;
        read each of its five steps with `get_cra_step`.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.compliance import apis

            _lookup_product(principal, product_id)
            result: dict[str, Any] = _unwrap(
                apis.create_or_get_assessment(principal.request, product_id), action="Starting the CRA assessment"
            )
            return result

        return await run_db(call)

    @mcp_tool(mcp, "get_cra_assessment", "product:read")
    async def get_cra_assessment(
        principal: Principal, assessment_id: str | None = None, product_id: str | None = None
    ) -> dict[str, Any]:
        """Where a product's CRA assessment stands: progress, what is stale, and its SBOMs' BSI status.

        Pass exactly one of `assessment_id` or `product_id`. `staleness` names
        documents and steps that changed data has made out of date, and
        `sbom_status` says per component whether its SBOM meets BSI TR-03183-2.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.compliance import apis
            from sbomify.apps.compliance.models import CRAAssessment

            if bool(assessment_id) == bool(product_id):
                raise ToolError("Pass exactly one of assessment_id or product_id.")
            mine = CRAAssessment.objects.filter(team=resolve_workspace(principal))
            mine = mine.filter(pk=assessment_id) if assessment_id else mine.filter(product_id=product_id)
            pk = mine.values_list("pk", flat=True).first()
            if pk is None:
                if assessment_id:
                    raise not_found("CRA assessment", assessment_id)
                raise ToolError(
                    f"No CRA assessment for product {product_id!r} in this workspace. "
                    "Start one with start_cra_assessment."
                )

            request = principal.request
            data: dict[str, Any] = _unwrap(apis.get_assessment(request, pk), action="Reading the CRA assessment")
            data["staleness"] = _unwrap(apis.check_staleness(request, pk), action="Checking staleness")
            sbom_status = _unwrap(apis.get_sbom_status(request, pk), action="Reading SBOM status")
            data["sbom_status"] = serializers.cut(sbom_status, "components")
            return data

        return await run_db(query)

    @mcp_tool(mcp, "get_cra_step", "product:read")
    async def get_cra_step(principal: Principal, assessment_id: str, step: int) -> dict[str, Any]:
        """Read one step of a CRA assessment with the data it holds.

        Steps: 1 product profile and classification, 2 SBOM compliance
        (BSI TR-03183-2), 3 security controls (Annex I) and vulnerability
        handling, 4 user information and documents, 5 the summary and export
        readiness. Step 3 lists every control with its `finding_id`, which
        `update_cra_finding` takes.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.compliance import apis

            _lookup_assessment(principal, assessment_id)
            context: dict[str, Any] = _unwrap(
                apis.get_step_context(principal.request, assessment_id, step), action=f"Reading step {step}"
            )
            data = context.get("data")
            if isinstance(data, dict) and isinstance(data.get("components"), list):
                serializers.cut(data, "components")
            return context

        return await run_db(query)

    @mcp_tool(mcp, "save_cra_step", "product:manage", also_requires=_ASSESSOR, writes=True, idempotent=True)
    async def save_cra_step(
        principal: Principal, assessment_id: str, step: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Save fields of CRA assessment step 1, 2 or 4.

        `data` holds the step's fields as `get_cra_step` returns them; only the
        fields you send change. Step 2 takes `waivers` (BSI finding id to
        `{"justification": ...}`, for tooling limitations only). Step 3 feeds
        the public security.txt and step 5 publishes the Declaration of
        Conformity, so a person saves those in sbomify; answer step 3's
        controls with `update_cra_finding` instead.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.compliance import apis
            from sbomify.apps.compliance.schemas import StepDataSchema

            if step in _PERSON_STEPS:
                raise ToolError(_PERSON_STEPS[step])
            _lookup_assessment(principal, assessment_id)
            result: dict[str, Any] = _unwrap(
                apis.save_step_data(principal.request, assessment_id, step, StepDataSchema(data=data)),
                action=f"Saving step {step}",
            )
            return result

        return await run_db(call)

    @mcp_tool(mcp, "update_cra_finding", "product:manage", also_requires=_ASSESSOR, writes=True, idempotent=True)
    async def update_cra_finding(
        principal: Principal,
        assessment_id: str,
        finding_id: str,
        status: FindingStatus,
        notes: str | None = None,
        justification: str | None = None,
    ) -> dict[str, Any]:
        """Answer one CRA control: whether the product satisfies it, with notes.

        `finding_id` comes from step 3 of `get_cra_step`. A Part I control
        marked not-applicable needs a `justification` (CRA Art. 13(4)). Notes
        and justification you leave out keep their current text.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.compliance import apis
            from sbomify.apps.compliance.schemas import FindingUpdateSchema

            finding = _lookup_finding(principal, assessment_id, finding_id)
            payload = FindingUpdateSchema(
                status=status,
                notes=finding.notes if notes is None else notes,
                justification=finding.justification if justification is None else justification,
            )
            result: dict[str, Any] = _unwrap(
                apis.update_finding(principal.request, assessment_id, finding_id, payload),
                action="Updating the finding",
            )
            return result

        return await run_db(call)

    @mcp_tool(mcp, "add_cra_observation", "product:manage", also_requires=_ASSESSOR, writes=True, idempotent=False)
    async def add_cra_observation(
        principal: Principal,
        assessment_id: str,
        finding_id: str,
        description: str,
        method: Literal["EXAMINE", "INTERVIEW", "TEST"],
        evidence_document_id: str | None = None,
    ) -> dict[str, Any]:
        """Record evidence for one CRA control: what was checked and how.

        `method` is EXAMINE (reviewed an artifact), INTERVIEW (asked someone)
        or TEST (ran something). `evidence_document_id` links a document
        already uploaded to one of the workspace's components.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.compliance import apis
            from sbomify.apps.compliance.schemas import ObservationCreateSchema

            _lookup_finding(principal, assessment_id, finding_id)
            payload = ObservationCreateSchema(
                description=description, method=method, evidence_document_id=evidence_document_id
            )
            result: dict[str, Any] = _unwrap(
                apis.create_observation(principal.request, assessment_id, finding_id, payload),
                action="Recording the observation",
            )
            return result

        return await run_db(call)

    @mcp_tool(mcp, "generate_cra_document", "product:manage", also_requires=_ASSESSOR, writes=True, idempotent=False)
    async def generate_cra_document(
        principal: Principal, assessment_id: str, kind: InternalDocumentKind
    ) -> dict[str, Any]:
        """Generate one of a CRA assessment's internal documents from its current data.

        Each call writes a new version. The VDP, security.txt and the
        Declaration of Conformity are published on the trust center when
        generated, so a person generates those in sbomify.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.compliance import apis

            _lookup_assessment(principal, assessment_id)
            result: dict[str, Any] = _unwrap(
                apis.generate_document(principal.request, assessment_id, kind), action="Generating the document"
            )
            return result

        return await run_db(call)

    @mcp_tool(mcp, "get_cra_export", "product:read")
    async def get_cra_export(principal: Principal, assessment_id: str, package_id: str) -> dict[str, Any]:
        """One export package of a CRA assessment: its files, integrity hash and signature.

        The newest package is under `last_export` in step 5 of `get_cra_step`.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.compliance import apis

            _lookup_assessment(principal, assessment_id)
            result: dict[str, Any] = _unwrap(
                apis.get_export(principal.request, assessment_id, package_id), action="Reading the export"
            )
            return result

        return await run_db(query)

    @mcp_tool(mcp, "list_cra_reports", "cra_report:read")
    async def list_cra_reports(principal: Principal, page: int = 1, page_size: int = 25) -> dict[str, Any]:
        """List the workspace's CRA Article 14 reports, open ones with the soonest deadline first.

        Each report's field values are left out; `get_cra_report` has them.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.compliance import apis

            resolve_workspace(principal)
            rows: list[dict[str, Any]] = _unwrap(apis.list_cra_reports(principal.request), action="Listing reports")
            safe_page, safe_size = clamp_page(page, page_size)
            start = (safe_page - 1) * safe_size
            items = [{k: v for k, v in row.items() if k != "values"} for row in rows[start : start + safe_size]]
            return serializers.paginated(items, page=safe_page, page_size=safe_size, total=len(rows))

        return await run_db(query)

    @mcp_tool(mcp, "get_cra_report", "cra_report:read")
    async def get_cra_report(
        principal: Principal, report_id: str, include_srp: bool = False, srp_stage: str = ""
    ) -> dict[str, Any]:
        """One CRA Article 14 report with its field values, filings and next deadline.

        `include_srp` adds the report laid out as ENISA's Single Reporting
        Platform asks for it, field by field with what is still missing, for
        `srp_stage` (early_warning, notification or final_report; the next due
        stage when left empty).
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.compliance import apis

            _lookup_report(principal, report_id)
            request = principal.request
            data: dict[str, Any] = _unwrap(apis.get_cra_report(request, report_id), action="Reading the report")
            if include_srp:
                data["srp"] = _unwrap(
                    apis.get_cra_report_srp(request, report_id, stage=srp_stage), action="Reading the SRP layout"
                )
            return data

        return await run_db(query)
