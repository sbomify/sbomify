"""The Overview's "What to fix first" panel must not vouch for scans it never ran.

The panel's fallback is the reassuring one, so every state that reaches it is
read as "scanned and clean". A workspace holding documents alone reaches it: it
has artifacts, so it is past the first-visit takeover, and it has no BOM
component, so nothing is pending a scan either. Telling that workspace its
completed scans found nothing, on a compliance surface, is worse than telling it
nothing at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.documents.models import Document
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db

NOTHING_TO_SCAN = "Nothing to scan yet"
ALL_CLEAR = "No open vulnerabilities to review"
AWAITING_SCAN = "Waiting for security scans"


def _clean_result() -> dict[str, Any]:
    return {
        "findings": [],
        "summary": {"total_findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
        "metadata": {"scanner": "osv-scanner"},
    }


@pytest.fixture
def client_for(sample_team_with_owner_member: Member):
    member = sample_team_with_owner_member
    # The Overview redirects into plan selection until the workspace has one.
    member.team.has_selected_billing_plan = True
    member.team.save(update_fields=["has_selected_billing_plan"])
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)
    cache.clear()
    return client, member.team


def _page(client: Client) -> str:
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 200
    return response.content.decode()


def test_a_documents_only_workspace_is_not_told_its_scans_came_back_clean(client_for) -> None:
    client, team = client_for
    component = Component.objects.create(name="Policies", team=team, component_type="document")
    Document.objects.create(name="Architecture", component=component)

    html = _page(client)

    assert NOTHING_TO_SCAN in html
    assert ALL_CLEAR not in html


def test_a_scanned_workspace_still_gets_its_all_clear(client_for) -> None:
    """The honest zero is the point of the panel and must survive the new branch."""
    client, team = client_for
    component = Component.objects.create(name="api", team=team)
    sbom = SBOM.objects.create(name="api", component=component, format="cyclonedx", sbom_filename="api.json")
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        category="security",
        status="completed",
        result=_clean_result(),
        result_summary=_clean_result()["summary"],
    )

    html = _page(client)

    assert ALL_CLEAR in html
    assert NOTHING_TO_SCAN not in html


def test_an_uploaded_but_unscanned_sbom_still_reads_as_pending(client_for) -> None:
    """A BOM component is scannable the moment it exists, so this state belongs
    to the waiting branch rather than the new one."""
    client, team = client_for
    component = Component.objects.create(name="api", team=team)
    SBOM.objects.create(name="api", component=component, format="cyclonedx", sbom_filename="api.json")

    html = _page(client)

    assert AWAITING_SCAN in html
    assert NOTHING_TO_SCAN not in html
    assert ALL_CLEAR not in html


def test_a_document_alongside_a_bom_component_does_not_suppress_the_real_state(client_for) -> None:
    """Documents are irrelevant to the distinction: what matters is whether any
    BOM component exists to scan."""
    client, team = client_for
    documents = Component.objects.create(name="Policies", team=team, component_type="document")
    Document.objects.create(name="Architecture", component=documents)
    Component.objects.create(name="api", team=team)

    html = _page(client)

    assert AWAITING_SCAN in html
    assert NOTHING_TO_SCAN not in html
