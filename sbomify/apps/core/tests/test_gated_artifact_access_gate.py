"""The public artifact page of a gated component offers the access gate.

A gated component is published — the Trust Center lists it, and its component
page renders "Request Access" alongside a table of the documents it holds.
Opening one of those rows without a grant used to render the generic error
page, so a reader who had just been told to request access hit "Forbidden"
with nowhere to go. It now serves the gate instead.

Which gate depends on where the reader stands in the access flow. Telling
someone whose request is already pending to request it again, or telling a
first-time reader their request was rejected, is the same dead end wearing a
friendlier face, so each state is covered here.
"""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, User
from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def team():
    workspace = Team.objects.create(name="Gating Co", billing_plan="business")
    workspace.is_public = True
    workspace.save(update_fields=["is_public"])
    return workspace


def _document(team: Team, visibility: str, component_name: str = "Policy Docs") -> Document:
    component = Component.objects.create(
        name=component_name,
        team=team,
        visibility=visibility,
        component_type=Component.ComponentType.DOCUMENT,
    )
    return Document.objects.create(
        component=component,
        name=f"{component_name} file",
        document_filename="soc2.pdf",
        content_type="application/pdf",
        source="manual_upload",
    )


def _require_nda(team: Team) -> Document:
    """Give the workspace a company-wide NDA, so gated access needs a signature."""
    nda = _document(team, Component.Visibility.PRIVATE, component_name="Company NDA")
    team.branding_info = {**(team.branding_info or {}), "company_nda_document_id": nda.id}
    team.save(update_fields=["branding_info"])
    return nda


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


def _request_access_url(team: Team) -> str:
    return reverse("documents:request_access", kwargs={"team_key": team.key})


def test_anonymous_reader_is_asked_to_request_access(team):
    document = _document(team, Component.Visibility.GATED)

    response = _visit(document)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Please request access to view this document." in content
    assert _request_access_url(team) in content
    # The gate stands in for the document, so its contents stay withheld.
    assert document.name not in content


def test_signed_in_reader_who_has_never_asked_is_asked_to_request_access(team, sample_user):
    """Not "pending or rejected": this reader has made no request at all."""
    document = _document(team, Component.Visibility.GATED)

    response = _visit(document, sample_user)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Please request access to view this document." in content
    assert "pending" not in content.lower()
    assert _request_access_url(team) in content


def test_a_pending_request_is_reported_as_under_review_with_nothing_to_do(team, sample_user):
    document = _document(team, Component.Visibility.GATED)
    AccessRequest.objects.create(team=team, user=sample_user, status=AccessRequest.Status.PENDING)

    response = _visit(document, sample_user)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Your access request is being reviewed." in content
    # Asking again is not the next step, so the page must not offer it.
    assert _request_access_url(team) not in content


def test_a_rejected_request_may_be_made_again(team, sample_user):
    document = _document(team, Component.Visibility.GATED)
    AccessRequest.objects.create(team=team, user=sample_user, status=AccessRequest.Status.REJECTED)

    response = _visit(document, sample_user)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Your access request was not approved." in content
    assert _request_access_url(team) in content


def test_revoked_access_reads_as_withdrawn_rather_than_rejected(team, sample_user):
    document = _document(team, Component.Visibility.GATED)
    AccessRequest.objects.create(team=team, user=sample_user, status=AccessRequest.Status.REVOKED)

    response = _visit(document, sample_user)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Your access to this workspace was withdrawn." in content
    assert _request_access_url(team) in content


def test_an_unsigned_nda_asks_for_the_signature_not_for_another_request(team, sample_user):
    """An approved reader who has not signed the NDA is not waiting on anyone."""
    _require_nda(team)
    document = _document(team, Component.Visibility.GATED)
    AccessRequest.objects.create(team=team, user=sample_user, status=AccessRequest.Status.APPROVED)

    response = _visit(document, sample_user)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Please sign the NDA to view this document." in content
    assert "Sign NDA" in content
    assert _request_access_url(team) not in content
    # The component page owns the signing flow, so that is where it sends them.
    assert reverse("core:component_details_public", kwargs={"component_id": document.component.id}) in content


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
