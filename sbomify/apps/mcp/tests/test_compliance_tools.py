"""The CRA compliance tools, called for real against real rows.

Each write is checked in the database, each write refuses an id from the
caller's other workspace as absent, and the acts that publish to the trust
center are refused before they reach a view.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core.authz import SCOPE_PRESETS

from .test_protocol import call, mcp_http, parse, structured
from .test_write_tools import call_tool

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _disable_billing(settings):
    settings.BILLING = False


def _assess(product, user, team):
    from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment

    result = get_or_create_assessment(product.id, user, team)
    assert result.ok
    return result.value


@pytest.fixture
def assessment(mcp_owner, product_in_bound_workspace):
    user, bound, _ = mcp_owner
    return _assess(product_in_bound_workspace, user, bound)


@pytest.fixture
def other_assessment(mcp_owner, product_in_other_workspace):
    user, _, other = mcp_owner
    return _assess(product_in_other_workspace, user, other)


def _first_finding(assessment):
    from sbomify.apps.compliance.models import OSCALFinding

    return OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).order_by("pk").first()


def _refusal(response) -> str:
    payload = parse(response)
    assert payload["result"].get("isError") is True, payload
    return json.dumps(payload)


async def _run(token, tool, arguments):
    async with mcp_http() as client:
        return await call_tool(client, token, tool, arguments)


@pytest.mark.asyncio
async def test_start_cra_assessment_creates_once(make_token, product_in_bound_workspace):
    from sbomify.apps.compliance.models import CRAAssessment

    token = await sync_to_async(make_token)(["product:manage", "workspace:manage"])
    first = structured(await _run(token, "start_cra_assessment", {"product_id": product_in_bound_workspace.id}))
    again = structured(await _run(token, "start_cra_assessment", {"product_id": product_in_bound_workspace.id}))

    assert first["id"] == again["id"]
    assert first["current_step"] == 1
    stored = await sync_to_async(CRAAssessment.objects.get)(product=product_in_bound_workspace)
    assert stored.id == first["id"]


@pytest.mark.asyncio
async def test_a_member_cannot_start_a_cra_assessment(mcp_owner, make_token, product_in_bound_workspace):
    """Starting answers with the assessment, and the wizard, reading it included, is owner and admin work."""
    from sbomify.apps.compliance.models import CRAAssessment
    from sbomify.apps.teams.models import Member

    user, bound, _ = mcp_owner
    await sync_to_async(Member.objects.filter(user=user, team=bound).update)(role="member")
    token = await sync_to_async(make_token)(None)

    refusal = _refusal(await _run(token, "start_cra_assessment", {"product_id": product_in_bound_workspace.id}))

    assert "Forbidden" in refusal
    assert not await sync_to_async(CRAAssessment.objects.filter(product=product_in_bound_workspace).exists)()


@pytest.mark.asyncio
async def test_get_cra_assessment_by_product_folds_in_staleness_and_sbom_status(make_token, assessment):
    token = await sync_to_async(make_token)(["product:read"])

    result = structured(await _run(token, "get_cra_assessment", {"product_id": assessment.product_id}))

    assert result["id"] == assessment.id
    assert set(result["staleness"]) >= {"stale_documents", "stale_steps", "has_new_sbom"}
    assert "summary" in result["sbom_status"]


@pytest.mark.asyncio
async def test_get_cra_step_three_names_each_controls_finding(make_token, assessment):
    token = await sync_to_async(make_token)(["product:read"])

    result = structured(await _run(token, "get_cra_step", {"assessment_id": assessment.id, "step": 3}))

    finding = await sync_to_async(_first_finding)(assessment)
    finding_ids = {c["finding_id"] for g in result["data"]["control_groups"] for c in g["controls"]}
    assert finding.id in finding_ids


@pytest.mark.asyncio
async def test_save_cra_step_saves_step_four_and_leaves_the_public_steps_to_a_person(make_token, assessment):
    from sbomify.apps.compliance.models import CRAAssessment
    from sbomify.apps.teams.models import Workspace

    token = await sync_to_async(make_token)(["product:read", "product:manage", "workspace:manage"])
    saved = structured(
        await _run(
            token,
            "save_cra_step",
            {"assessment_id": assessment.id, "step": 4, "data": {"support_email": "support@example.com"}},
        )
    )
    # Sent back in the shape get_cra_step reads it, under user_info.
    as_read = structured(await _run(token, "get_cra_step", {"assessment_id": assessment.id, "step": 4}))["data"]
    as_read["user_info"]["support_url"] = "https://example.com/support"
    await _run(token, "save_cra_step", {"assessment_id": assessment.id, "step": 4, "data": as_read})
    security_txt = await _run(
        token,
        "save_cra_step",
        {
            "assessment_id": assessment.id,
            "step": 3,
            "data": {"vulnerability_handling": {"vdp_url": "https://example.com/vdp"}},
        },
    )
    finish = await _run(token, "save_cra_step", {"assessment_id": assessment.id, "step": 5, "data": {}})

    assert saved["id"] == assessment.id
    assert "public security.txt" in _refusal(security_txt)
    assert "a person finishes it" in _refusal(finish)
    stored = await sync_to_async(CRAAssessment.objects.get)(pk=assessment.id)
    assert stored.support_email == "support@example.com"
    assert stored.support_url == "https://example.com/support"
    assert stored.vdp_url != "https://example.com/vdp"
    assert stored.status != CRAAssessment.WizardStatus.COMPLETE
    team = await sync_to_async(Workspace.objects.get)(pk=assessment.team_id)
    assert not (team.security_txt_config or {}).get("policy_url")


@pytest.mark.asyncio
async def test_saving_step_one_keeps_a_third_party_procedure(make_token, assessment):
    """Step 1 resets an unsent procedure to the category default, which for Class I is self-assessment."""
    from sbomify.apps.compliance.models import CRAAssessment
    from sbomify.apps.teams.models import ContactEntity, ContactProfile

    def manufacturer() -> None:
        # Step 1 refuses to save without a real manufacturer (CRA Annex V item 2).
        profile = ContactProfile.objects.create(name="Maker", team=assessment.team, is_default=True)
        ContactEntity.objects.create(
            profile=profile, name="Example Devices Ltd", email="x@example.com", is_manufacturer=True
        )

    await sync_to_async(manufacturer)()
    await sync_to_async(CRAAssessment.objects.filter(pk=assessment.pk).update)(
        product_category=CRAAssessment.ProductCategory.CLASS_I,
        conformity_assessment_procedure=CRAAssessment.ConformityProcedure.MODULE_H,
        harmonised_standard_applied=True,
    )
    token = await sync_to_async(make_token)(["product:manage", "workspace:manage"])

    structured(
        await _run(
            token,
            "save_cra_step",
            {"assessment_id": assessment.id, "step": 1, "data": {"intended_use": "Home routers"}},
        )
    )

    stored = await sync_to_async(CRAAssessment.objects.get)(pk=assessment.pk)
    assert stored.intended_use == "Home routers"
    assert stored.conformity_assessment_procedure == CRAAssessment.ConformityProcedure.MODULE_H


@pytest.mark.asyncio
async def test_update_cra_finding_keeps_the_notes_it_was_not_sent(make_token, assessment):
    from sbomify.apps.compliance.models import OSCALFinding

    finding = await sync_to_async(_first_finding)(assessment)
    await sync_to_async(OSCALFinding.objects.filter(pk=finding.pk).update)(notes="Reviewed in the design doc")
    token = await sync_to_async(make_token)(["product:manage", "workspace:manage"])

    result = structured(
        await _run(
            token,
            "update_cra_finding",
            {"assessment_id": assessment.id, "finding_id": finding.id, "status": "satisfied"},
        )
    )

    assert result["status"] == "satisfied"
    stored = await sync_to_async(OSCALFinding.objects.get)(pk=finding.pk)
    assert (stored.status, stored.notes) == ("satisfied", "Reviewed in the design doc")


@pytest.mark.asyncio
async def test_add_cra_observation_records_evidence(make_token, assessment):
    from sbomify.apps.compliance.models import OSCALObservation

    finding = await sync_to_async(_first_finding)(assessment)
    token = await sync_to_async(make_token)(["product:manage", "workspace:manage"])

    result = structured(
        await _run(
            token,
            "add_cra_observation",
            {
                "assessment_id": assessment.id,
                "finding_id": finding.id,
                "description": "Checked the update channel signs releases",
                "method": "EXAMINE",
            },
        )
    )

    stored = await sync_to_async(OSCALObservation.objects.get)(pk=result["id"])
    assert stored.finding_id == finding.id


@pytest.mark.asyncio
async def test_generate_cra_document_writes_internal_kinds_only(make_token, assessment):
    from sbomify.apps.compliance.models import CRAGeneratedDocument

    token = await sync_to_async(make_token)(["product:manage", "workspace:manage"])
    with patch("sbomify.apps.core.object_store.StorageClient"):
        made = structured(
            await _run(token, "generate_cra_document", {"assessment_id": assessment.id, "kind": "risk_assessment"})
        )
        public = await _run(token, "generate_cra_document", {"assessment_id": assessment.id, "kind": "vdp"})

    assert made["document_kind"] == "risk_assessment"
    _refusal(public)
    kinds = await sync_to_async(list)(
        CRAGeneratedDocument.objects.filter(assessment=assessment).values_list("document_kind", flat=True)
    )
    assert kinds == ["risk_assessment"]


@pytest.mark.asyncio
async def test_get_cra_export_reads_a_package(make_token, assessment):
    from sbomify.apps.compliance.models import CRAExportPackage

    package = await sync_to_async(CRAExportPackage.objects.create)(
        assessment=assessment,
        storage_key=f"compliance/exports/{assessment.id}/test.zip",
        content_hash="0" * 64,
        manifest={"format_version": "1.0"},
    )
    token = await sync_to_async(make_token)(["product:read"])

    result = structured(await _run(token, "get_cra_export", {"assessment_id": assessment.id, "package_id": package.id}))

    assert (result["id"], result["content_hash"]) == (package.id, "0" * 64)


@pytest.mark.asyncio
async def test_a_cra_report_is_listed_and_read_but_never_written(mcp_owner, make_token, product_in_bound_workspace):
    from sbomify.apps.compliance.services import report_service

    user, bound, _ = mcp_owner
    created = (
        await sync_to_async(report_service.create_report)(
            bound, user, kind="incident", product_id=product_in_bound_workspace.id, aware_at=datetime.now(UTC)
        )
    ).value
    token = await sync_to_async(make_token)(None)

    listed = structured(await _run(token, "list_cra_reports", {}))
    read = structured(await _run(token, "get_cra_report", {"report_id": created.id, "include_srp": True}))
    async with mcp_http() as client:
        names = {
            t["name"] for t in parse(await call(client, "tools/list", token=token.encoded_token))["result"]["tools"]
        }

    assert [row["id"] for row in listed["items"]] == [created.id]
    assert "values" not in listed["items"][0]
    assert read["srp"]["fields"]
    assert not names & {"create_cra_report", "update_cra_report", "record_cra_filing"}


def _other_workspace_calls(other_assessment, finding_id, other_product_id):
    return [
        ("start_cra_assessment", {"product_id": other_product_id}, "No product found"),
        ("save_cra_step", {"assessment_id": other_assessment.id, "step": 4, "data": {}}, "No CRA assessment found"),
        (
            "update_cra_finding",
            {"assessment_id": other_assessment.id, "finding_id": finding_id, "status": "satisfied"},
            "No CRA assessment found",
        ),
        (
            "add_cra_observation",
            {"assessment_id": other_assessment.id, "finding_id": finding_id, "description": "x", "method": "TEST"},
            "No CRA assessment found",
        ),
        (
            "generate_cra_document",
            {"assessment_id": other_assessment.id, "kind": "risk_assessment"},
            "No CRA assessment found",
        ),
    ]


@pytest.mark.asyncio
async def test_every_write_refuses_the_other_workspaces_ids(make_token, other_assessment, product_in_other_workspace):
    from sbomify.apps.compliance.models import OSCALFinding, OSCALObservation

    finding = await sync_to_async(_first_finding)(other_assessment)
    token = await sync_to_async(make_token)(None)

    for tool, arguments, message in _other_workspace_calls(other_assessment, finding.id, product_in_other_workspace.id):
        assert message in _refusal(await _run(token, tool, arguments)), tool

    assert await sync_to_async(OSCALObservation.objects.filter(finding=finding).count)() == 0
    assert (await sync_to_async(OSCALFinding.objects.get)(pk=finding.pk)).status == "unanswered"


@pytest.mark.asyncio
async def test_read_only_token_sees_no_cra_write(make_token):
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        response = await call(client, "tools/list", token=token.encoded_token)

    names = {tool["name"] for tool in parse(response)["result"]["tools"]}
    assert {"get_cra_assessment", "get_cra_step", "get_cra_export", "list_cra_reports", "get_cra_report"} <= names
    assert not names & {
        "start_cra_assessment",
        "save_cra_step",
        "update_cra_finding",
        "add_cra_observation",
        "generate_cra_document",
    }


def test_answering_the_assessment_needs_an_admin_tier_scope():
    """The wizard is owner and admin work, so a token needs an admin-tier scope to change an assessment."""
    from sbomify.apps.mcp import registry

    writes = {
        "start_cra_assessment",
        "save_cra_step",
        "update_cra_finding",
        "add_cra_observation",
        "generate_cra_document",
    }
    assert writes & registry.permitted_by(["product:manage"]) == set()
    assert writes <= registry.permitted_by(["product:manage", "workspace:manage"])
