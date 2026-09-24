"""The data export carries artifacts only from workspaces the user works in.

A trust-center guest membership is an access grant, not a place the user works:
approving an access request creates it before any NDA is signed. The export
still lists that membership, and leaves the vendor's artifacts out.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.services.data_export import export_user_data
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def own_and_vendor_workspaces(sample_user, team_with_business_plan):
    own = team_with_business_plan
    own_component = Component.objects.create(name="own", team=own)
    SBOM.objects.create(name="own-sbom", component=own_component, format="cyclonedx", format_version="1.6")

    vendor = Team.objects.create(name="Vendor")
    Member.objects.create(team=vendor, user=sample_user, role="guest")
    private = Component.objects.create(name="vendor", team=vendor, visibility=Component.Visibility.PRIVATE)
    SBOM.objects.create(name="vendor-sbom", component=private, format="cyclonedx", format_version="1.6")
    document_component = Component.objects.create(
        name="vendor-docs",
        team=vendor,
        visibility=Component.Visibility.PRIVATE,
        component_type=Component.ComponentType.DOCUMENT,
    )
    Document.objects.create(name="vendor-doc", component=document_component, document_filename="vendor-doc.pdf")
    return own, vendor


def test_export_leaves_out_artifacts_from_guest_workspaces(sample_user, own_and_vendor_workspaces):
    data = export_user_data(sample_user)

    assert {sbom["name"] for sbom in data["sboms"]} == {"own-sbom"}
    assert data["documents"] == []


def test_export_still_lists_the_guest_membership(sample_user, own_and_vendor_workspaces):
    _own, vendor = own_and_vendor_workspaces

    data = export_user_data(sample_user)

    assert {"key": vendor.key, "role": "guest"}.items() <= next(
        workspace for workspace in data["workspaces"] if workspace["key"] == vendor.key
    ).items()


def test_export_endpoint_leaves_out_guest_workspace_artifacts(sample_user, own_and_vendor_workspaces):
    client = Client()
    client.force_login(sample_user)

    response = client.get(reverse("api-1:export_user_data_endpoint"))

    assert response.status_code == 200
    assert "vendor-sbom" not in {sbom["name"] for sbom in response.json()["sboms"]}
