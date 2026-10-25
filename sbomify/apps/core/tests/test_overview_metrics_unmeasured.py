"""The workspace Overview must not report an unmeasured state as zero either.

The Overview's security cards read the same component snapshot the product page
does — the newest SBOM per component — so a component whose newest SBOM has no
completed scan contributes nothing. Scanning is asynchronous, so the cards drop
to 0 the moment an SBOM is uploaded and stay there until the scan finishes.

This is the same defect fixed on product details, on the page a reader lands on
first. The VEX review card is deliberately excluded: it counts submissions
waiting in the approval queue, which scanning does not affect, so its zero is
always honest.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _clean_security_result() -> dict[str, Any]:
    return {
        "findings": [],
        "summary": {"total_findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
        "metadata": {"scanner": "osv-scanner"},
    }


def _sbom(component: Component, version: str, filename: str) -> SBOM:
    return SBOM.objects.create(
        component=component,
        name=component.name,
        format="cyclonedx",
        format_version="1.6",
        version=version,
        sbom_filename=filename,
    )


def _scan(sbom: SBOM) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        category="security",
        status="completed",
        result=_clean_security_result(),
        result_summary=_clean_security_result()["summary"],
    )


@pytest.fixture
def workspace(sample_team_with_owner_member: Member):
    member = sample_team_with_owner_member
    # The Overview redirects into plan selection until the workspace has one.
    member.team.has_selected_billing_plan = True
    member.team.save(update_fields=["has_selected_billing_plan"])
    product = Product.objects.create(team=member.team, name="gateway")
    component = Component.objects.create(team=member.team, name="firmware", component_type=Component.ComponentType.BOM)
    product.components.add(component)
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)
    return client, member.team, component


def _page(client: Client) -> str:
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 200
    return response.content.decode()


def test_an_unscanned_workspace_does_not_claim_zero(workspace) -> None:
    client, _team, component = workspace
    _sbom(component, "2.0", "new.json")

    html = _page(client)

    assert "Not scanned yet" in html


def test_one_scanned_component_does_not_vouch_for_an_unscanned_one(workspace) -> None:
    """A single assessed component must not restore the confident zero for the
    rest of the workspace, which is where the product-page fix originally fell
    short."""
    client, team, scanned_component = workspace
    _scan(_sbom(scanned_component, "1.0", "scanned.json"))
    unscanned = Component.objects.create(team=team, name="bootloader", component_type=Component.ComponentType.BOM)
    _sbom(unscanned, "1.0", "unscanned.json")

    html = _page(client)

    assert "Not scanned yet" in html


def test_a_fully_scanned_workspace_reports_its_real_zero(workspace) -> None:
    client, _team, component = workspace
    _scan(_sbom(component, "1.0", "old.json"))

    html = _page(client)

    # A measured zero is a real answer and still reads as one.
    assert "Not scanned yet" not in html


def test_the_vex_review_card_counts_pending_submissions_and_links_to_the_queue(workspace) -> None:
    from sbomify.apps.vulnerability_scanning.models import VexSubmission

    client, team, component = workspace
    _sbom(component, "2.0", "new.json")
    for status in (VexSubmission.Status.PENDING, VexSubmission.Status.PENDING, VexSubmission.Status.APPROVED):
        VexSubmission.objects.create(
            team=team,
            component=component,
            status=status,
            kind=VexSubmission.Kind.DECISIONS,
            channel=VexSubmission.Channel.AGENT,
            document=b"{}",
            document_format="decisions",
        )

    html = _page(client)

    assert "Components with stale SBOMs" not in html
    label = html.index("VEX submissions awaiting review")
    card = html[html.rindex("<dl", 0, label) : html.index("</dl>", label)]
    # One approved submission is history, not work: only the two pending count.
    value = re.search(r"<dd[^>]*>\s*([\d,]+)", card)
    assert value is not None and value.group(1) == "2"
    assert "Not scanned yet" not in card
    review_url = reverse("vulnerability_scanning:vulnerability_scans", args=[team.key]) + "?view=review"
    assert f'href="{review_url}"' in card
