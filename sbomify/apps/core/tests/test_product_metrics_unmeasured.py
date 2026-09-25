"""A product's security cards must not report an unmeasured state as zero.

The stat cards sum the newest SBOM per component. A component whose newest SBOM
has no completed scan contributes nothing, so the cards drop to 0 the moment an
SBOM is uploaded and stay there until the scan finishes. Scanning is
asynchronous, so that is the normal state after every upload, and it is exactly
when a release pinned to the older, scanned SBOM still shows its findings.

Reading "Open vulnerabilities 0" on a product whose shipped release carries 22
is worse than reading nothing: it is a clean bill of health on the page a user
acts on, for a window whose length is set by the scan queue.
"""

from __future__ import annotations

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


@pytest.fixture
def product_with_component(sample_team_with_owner_member: Member):
    member = sample_team_with_owner_member
    product = Product.objects.create(team=member.team, name="gateway")
    component = Component.objects.create(team=member.team, name="firmware", component_type=Component.ComponentType.BOM)
    product.components.add(component)
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)
    return client, product, component


def _page(client: Client, product: Product) -> str:
    response = client.get(reverse("core:product_details", args=[product.id]))
    assert response.status_code == 200
    return response.content.decode()


def test_an_unscanned_product_does_not_claim_zero(product_with_component) -> None:
    client, product, component = product_with_component
    SBOM.objects.create(
        component=component,
        name="firmware",
        format="cyclonedx",
        format_version="1.6",
        version="2.0",
        sbom_filename="new.json",
    )

    html = _page(client, product)

    assert "No completed scan yet" in html


def test_a_scanned_product_reports_its_real_count(product_with_component) -> None:
    client, product, component = product_with_component
    sbom = SBOM.objects.create(
        component=component,
        name="firmware",
        format="cyclonedx",
        format_version="1.6",
        version="1.0",
        sbom_filename="old.json",
    )
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        category="security",
        status="completed",
        result=_clean_security_result(),
        result_summary=_clean_security_result()["summary"],
    )

    html = _page(client, product)

    # A measured zero is a real answer and still reads as one.
    assert "No completed scan yet" not in html
