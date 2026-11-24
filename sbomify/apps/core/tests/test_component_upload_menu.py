"""The component menu offers one upload item per artifact type the component takes.

A BOM component takes SBOMs, CBOMs and VEX, so it gets an item for each, and
each one opens the shared uploader with its type selected. A document component
takes documents only. Every item stays with the roles that can upload.
"""

from __future__ import annotations

import re
from html import unescape

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member, Workspace

pytestmark = pytest.mark.django_db

TYPED_ITEMS = {
    "Upload SBOM…": "$dispatch('open-upload', { bomType: 'sbom' })",
    "Upload CBOM…": "$dispatch('open-upload', { bomType: 'cbom' })",
    "Upload VEX…": "$dispatch('open-upload', { bomType: 'vex' })",
}
DOCUMENT_ITEM = "Upload document…"
RETIRED_ITEM = "Upload artifact…"


def _page(team: Workspace, role: str, component_type: str) -> str:
    component = Component.objects.create(name="Upload target", team=team, component_type=component_type)
    user = get_user_model().objects.create_user(username=f"{role}-uploader", email=f"{role}-uploader@example.com")
    Member.objects.create(team=team, user=user, role=role)
    client = Client()
    setup_authenticated_client_session(client, team, user)
    response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))
    assert response.status_code == 200
    return unescape(response.content.decode())


def _menu_item(page: str, label: str) -> str:
    """The opening tag of the menu row holding ``label``."""
    row = re.search(rf"(<button[^>]*>)\s*(?:<i[^>]*></i>\s*)?{re.escape(label)}\s*</button>", page)
    assert row, f"no menu row for {label}"
    return row.group(1)


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_a_bom_component_offers_one_upload_per_type(team_with_business_plan: Workspace, role: str) -> None:
    page = _page(team_with_business_plan, role, "bom")

    for label, dispatch in TYPED_ITEMS.items():
        item = _menu_item(page, label)
        assert 'role="menuitem"' in item
        assert dispatch in item
    assert RETIRED_ITEM not in page
    assert DOCUMENT_ITEM not in page
    # The CI/CD dialog's pointer to manual upload names the items that exist.
    assert "For a one-off upload, use the component menu." in page


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_a_document_component_offers_only_a_document_upload(team_with_business_plan: Workspace, role: str) -> None:
    page = _page(team_with_business_plan, role, "document")

    item = _menu_item(page, DOCUMENT_ITEM)
    assert "$dispatch('open-upload')" in item
    for label in TYPED_ITEMS:
        assert label not in page
    assert RETIRED_ITEM not in page
    # The document uploader is told it takes no BOM types, so a typed request never opens it.
    assert 'x-data="uploadDialog({ bomTypes: false })"' in page


@pytest.mark.parametrize("component_type", ["bom", "document"])
def test_a_role_that_cannot_upload_is_offered_no_upload(
    team_with_business_plan: Workspace, component_type: str
) -> None:
    page = _page(team_with_business_plan, "operator", component_type)

    for label in [*TYPED_ITEMS, DOCUMENT_ITEM, RETIRED_ITEM]:
        assert label not in page
