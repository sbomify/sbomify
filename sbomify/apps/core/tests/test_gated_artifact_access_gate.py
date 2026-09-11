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
from django.core.cache import cache
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


def test_an_artifact_id_that_names_nothing_is_still_not_found(team):
    """The gate stands in for a withheld artifact, never for an absent one."""
    document = _document(team, Component.Visibility.GATED)

    response = Client().get(
        reverse(
            "core:component_item_public",
            kwargs={
                "component_id": document.component.id,
                "item_type": "documents",
                "item_id": "doesnotexist",
            },
        )
    )

    assert response.status_code == 404
    assert "Request Access" not in response.content.decode()


class TestOnACustomDomain:
    """The Trust Center a reader actually visits is the workspace's own domain.

    That is where every link on it is a slug rather than an id, which is the
    routing this branch fixed, so the gate has to work there too.
    """

    @pytest.fixture(autouse=True)
    def _app_base_url(self, settings):
        settings.APP_BASE_URL = "http://app.sbomify.com"

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    @pytest.fixture
    def team(self):
        workspace = Team.objects.create(
            name="Gating Co",
            billing_plan="business",
            custom_domain="trust.example.com",
            custom_domain_validated=True,
        )
        workspace.is_public = True
        workspace.save(update_fields=["is_public"])
        return workspace

    def test_the_gate_is_served_from_the_slug_url(self, team):
        document = _document(team, Component.Visibility.GATED)

        response = Client(HTTP_HOST="trust.example.com").get(
            f"/components/{document.component.slug}/documents/{document.id}/"
        )

        assert response.status_code == 403
        content = response.content.decode()
        assert "Please request access to view this document." in content
        # The way back is the clean component URL, not the /public/ one.
        assert f"/component/{document.component.slug}/" in content
        assert "/public/component/" not in content

    def test_a_slug_collision_cannot_open_a_gated_artifact(self, team):
        """Component names are unique; the slugs derived from them are not.

        "Policy Docs" and "Policy-Docs" are two components sharing one custom
        domain URL, and since gated components now answer that URL too, a
        collision can cross visibilities. It buys nothing: access is checked
        against the artifact's own component, not against whichever component
        the slug landed on, so the gated document stays withheld either way.
        """
        public_doc = _document(team, Component.Visibility.PUBLIC, component_name="Policy Docs")
        gated_doc = _document(team, Component.Visibility.GATED, component_name="Policy-Docs")
        assert public_doc.component.slug == gated_doc.component.slug

        response = Client(HTTP_HOST="trust.example.com").get(
            f"/components/{public_doc.component.slug}/documents/{gated_doc.id}/"
        )

        assert response.status_code == 403
        assert gated_doc.name not in response.content.decode()

    def test_the_app_domain_redirects_before_gating(self, team):
        """A gated artifact takes the same route to the custom domain a public one does."""
        document = _document(team, Component.Visibility.GATED)

        response = Client().get(
            reverse(
                "core:component_item_public",
                kwargs={
                    "component_id": document.component.id,
                    "item_type": "documents",
                    "item_id": document.id,
                },
            )
        )

        assert response.status_code == 302
        assert response["Location"] == (
            f"http://trust.example.com/components/{document.component.slug}/documents/{document.id}/"
        )
