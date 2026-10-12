"""A delete control is offered only to a role its endpoint lets delete.

Every delete action is in the DELETE tier, owners and admins. These controls
followed the manage tier, so a member was offered a delete the API refused,
and the only sign of the refusal was a toast in the corner.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db

ROLES = [("member", False), ("admin", True), ("owner", True)]


@pytest.fixture
def items(team_with_business_plan) -> dict:
    team = team_with_business_plan
    product = Product.objects.create(name="Offer product", team=team)
    component = Component.objects.create(name="Offer component", team=team)
    product.components.add(component)
    documents = Component.objects.create(
        name="Offer documents", team=team, component_type=Component.ComponentType.DOCUMENT
    )
    document = Document.objects.create(
        name="Offer document",
        component=documents,
        document_type=Document.DocumentType.README,
        document_filename="readme.txt",
        content_type="text/plain",
        file_size=1,
        source="manual_upload",
        version="1.0",
    )
    return {
        "team": team,
        "product_id": product.id,
        "component_id": component.id,
        "release_id": Release.objects.create(product=product, name="v1").id,
        "sbom_id": SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.6").id,
        "documents_component_id": documents.id,
        "document_id": document.id,
    }


def _client(team, role: str) -> Client:
    user = get_user_model().objects.create_user(username=f"{role}-offer", email=f"{role}-offer@example.com")
    Member.objects.create(team=team, user=user, role=role)
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


@pytest.mark.parametrize(("role", "offered"), ROLES)
def test_the_component_page_offers_deletion_only_to_a_role_that_can_delete(role, offered, items) -> None:
    client = _client(items["team"], role)

    page = client.get(reverse("core:component_details", kwargs={"component_id": items["component_id"]}))

    assert page.status_code == 200
    assert ("Delete Component" in page.content.decode()) is offered
    if not offered:
        delete = reverse("api-1:delete_component", kwargs={"component_id": items["component_id"]})
        assert client.delete(delete).status_code == 403


def test_the_component_page_asks_the_component_s_workspace_not_the_session_s(items) -> None:
    """Owning the workspace the session points at grants nothing in another one."""
    user = get_user_model().objects.create_user(username="two-workspaces", email="two-workspaces@example.com")
    Member.objects.create(team=items["team"], user=user, role="member")
    own = Team.objects.create(name="Owned elsewhere")
    Member.objects.create(team=own, user=user, role="owner")
    client = Client()
    setup_authenticated_client_session(client, own, user)

    page = client.get(reverse("core:component_details", kwargs={"component_id": items["component_id"]}))

    assert page.status_code == 200
    assert "Delete Component" not in page.content.decode()


@pytest.mark.parametrize(("role", "offered"), ROLES)
def test_the_release_page_offers_deletion_only_to_a_role_that_can_delete(role, offered, items) -> None:
    client = _client(items["team"], role)

    page = client.get(
        reverse("core:release_details", kwargs={"product_id": items["product_id"], "release_id": items["release_id"]})
    )

    assert page.status_code == 200
    assert ("Delete Release" in page.content.decode()) is offered
    if not offered:
        assert (
            client.delete(reverse("api-1:delete_release", kwargs={"release_id": items["release_id"]})).status_code
            == 403
        )


@pytest.mark.parametrize(("role", "offered"), ROLES)
def test_the_documents_table_offers_deletion_only_to_a_role_that_can_delete(role, offered, items) -> None:
    """Editing stays with the manage tier; only the delete moves up."""
    client = _client(items["team"], role)

    table = client.get(
        reverse("documents:documents_table", kwargs={"component_id": items["documents_component_id"]}),
        HTTP_HX_REQUEST="true",
    )

    page = table.content.decode()
    assert table.status_code == 200
    assert "open-edit-document-modal" in page
    assert ("open-delete-document-modal" in page) is offered
    assert ('id="delete-document-modal"' in page) is offered
