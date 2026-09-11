"""The public artifact page of a gated component offers the access gate.

A gated component is published — the Trust Center lists it, and its component
page renders "Request Access" alongside a table of the documents it holds.
Opening one of those rows without a grant used to render the generic error
page, so a reader who had just been told to request access hit "Forbidden"
with nowhere to go. It now serves the same gate the document download does.
"""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, User
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def team():
    workspace = Team.objects.create(name="Gating Co", billing_plan="business")
    workspace.is_public = True
    workspace.save(update_fields=["is_public"])
    return workspace


def _document(team: Team, visibility: str) -> Document:
    component = Component.objects.create(
        name="Policy Docs",
        team=team,
        visibility=visibility,
        component_type=Component.ComponentType.DOCUMENT,
    )
    return Document.objects.create(
        component=component,
        name="SOC 2 Type II",
        document_filename="soc2.pdf",
        content_type="application/pdf",
        source="manual_upload",
    )


def _visit(document: Document, user: User | None = None):
    client = Client()
    if user is not None:
        client.force_login(user)
    return client.get(
        reverse(
            "core:component_item_public",
            kwargs={
                "component_id": document.component.id,
                "item_type": "documents",
                "item_id": document.id,
            },
        )
    )


def test_anonymous_reader_gets_the_request_access_gate(team):
    document = _document(team, Component.Visibility.GATED)

    response = _visit(document)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Request Access" in content
    assert reverse("documents:request_access", kwargs={"team_key": team.key}) in content
    # The gate stands in for the document, so its contents stay withheld.
    assert document.name not in content


def test_signed_in_reader_without_a_grant_gets_the_gate(team, sample_user):
    document = _document(team, Component.Visibility.GATED)

    response = _visit(document, sample_user)

    assert response.status_code == 403
    assert "Request Access" in response.content.decode()


def test_reader_with_a_grant_sees_the_document(team, sample_user):
    document = _document(team, Component.Visibility.GATED)
    Member.objects.create(team=team, user=sample_user, role="owner")

    response = _visit(document, sample_user)

    assert response.status_code == 200
    assert document.name in response.content.decode()


def test_public_document_is_unaffected(team):
    document = _document(team, Component.Visibility.PUBLIC)

    response = _visit(document)

    assert response.status_code == 200
    assert document.name in response.content.decode()
