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

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.urls import reverse

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.models import Component, User
from sbomify.apps.core.views.component_item import ComponentItemPublicView
from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
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


def _sbom(team: Team, visibility: str, component_name: str = "Platform") -> SBOM:
    component = Component.objects.create(
        name=component_name,
        team=team,
        visibility=visibility,
        component_type=Component.ComponentType.BOM,
    )
    return SBOM.objects.create(
        name=f"{component_name} sbom",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=f"{component_name}.cdx.json",
    )


def _visit_sbom(sbom: SBOM, user: User | None = None, item_type: str = "sboms"):
    """The same route, for the artifact table the other half of the branch reads."""
    client = Client()
    if user is not None:
        client.force_login(user)
    return client.get(
        reverse(
            "core:component_item_public",
            kwargs={"component_id": sbom.component.id, "item_type": item_type, "item_id": sbom.id},
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


def test_a_pending_request_still_asks_for_an_outstanding_nda(team, sample_user):
    """Pending usually means waiting on the workspace, but not when an NDA is owed.

    The signature can be given while the request is open, and the component page
    has always offered it, so the artifact gate must not be the one place that
    reports the reader has nothing to do.
    """
    _require_nda(team)
    document = _document(team, Component.Visibility.GATED)
    AccessRequest.objects.create(team=team, user=sample_user, status=AccessRequest.Status.PENDING)

    response = _visit(document, sample_user)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Please sign the NDA to view this document." in content
    assert "Sign NDA" in content


def test_a_pending_request_with_no_nda_required_has_nothing_to_do(team, sample_user):
    document = _document(team, Component.Visibility.GATED)
    AccessRequest.objects.create(team=team, user=sample_user, status=AccessRequest.Status.PENDING)

    response = _visit(document, sample_user)

    assert response.status_code == 403
    content = response.content.decode()
    assert "Your access request is being reviewed." in content
    assert "Sign NDA" not in content


def test_a_stale_signature_still_owes_the_current_nda(team, sample_user):
    """A new NDA version leaves the old signatures live, by design.

    Reading liveness alone reported the reader as done with a document they had
    never seen, so the gate told them to wait while the signature it wanted was
    never going to arrive.
    """
    from sbomify.apps.documents.access_models import NDASignature

    old_nda = _document(team, Component.Visibility.PRIVATE, component_name="NDA v1")
    document = _document(team, Component.Visibility.GATED)
    request = AccessRequest.objects.create(team=team, user=sample_user, status=AccessRequest.Status.PENDING)
    NDASignature.objects.create(
        access_request=request,
        nda_document=old_nda,
        nda_content_hash="0" * 64,
        signed_name="Test User",
        ip_address="203.0.113.1",
    )
    # The workspace has since replaced it.
    current_nda = _document(team, Component.Visibility.PRIVATE, component_name="NDA v2")
    team.branding_info = {**(team.branding_info or {}), "company_nda_document_id": current_nda.id}
    team.save(update_fields=["branding_info"])

    response = _visit(document, sample_user)

    assert response.status_code == 403
    assert "Please sign the NDA to view this document." in response.content.decode()


def test_an_artifact_from_another_component_keeps_that_components_answer(team, sample_user):
    """Approval here could never release something this component does not hold.

    The detail services authorize the artifact's own component, so a private id
    borrowed from elsewhere used to draw a Request Access page for the gated
    component named in the URL.
    """
    gated = _document(team, Component.Visibility.GATED)
    elsewhere = _document(team, Component.Visibility.PRIVATE, component_name="Internal Only")

    response = Client().get(
        reverse(
            "core:component_item_public",
            kwargs={
                "component_id": gated.component.id,
                "item_type": "documents",
                "item_id": elsewhere.id,
            },
        )
    )

    assert response.status_code == 403
    assert "Request Access" not in response.content.decode()


def test_the_gate_wears_the_workspace_brand(team):
    """It is the workspace's own Trust Center page, not an sbomify error page."""
    team.branding_info = {**(team.branding_info or {}), "brand_color": "#C2410C", "branding_enabled": True}
    team.save(update_fields=["branding_info"])
    document = _document(team, Component.Visibility.GATED)

    response = _visit(document)

    assert response.status_code == 403
    content = response.content.decode()
    assert "--brand-color: #C2410C" in content
    assert "Gating Co" in content


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


class TestTheOtherHalfOfTheBranch:
    """Documents are one of two artifact tables this route serves.

    ``sboms``, ``vex`` and ``cbom`` all read the SBOM table through
    ``get_sbom_detail`` and ``sbom_belongs_to_component``, so every rule the
    document tests above pin has a second implementation behind it. Covered here
    so a regression cannot leave gated SBOM links on the generic Forbidden page
    while document links still pass.
    """

    def test_a_gated_sbom_is_withheld_behind_the_same_gate(self, team):
        sbom = _sbom(team, Component.Visibility.GATED)

        response = _visit_sbom(sbom)

        assert response.status_code == 403
        content = response.content.decode()
        assert "Please request access to view this SBOM." in content
        assert _request_access_url(team) in content
        assert sbom.name not in content

    @pytest.mark.parametrize(("item_type", "subject"), [("vex", "VEX"), ("cbom", "CBOM")])
    def test_a_gated_bom_is_named_in_the_readers_own_words(self, team, item_type, subject):
        """The three SBOM-backed paths differ only in what they call the artifact."""
        sbom = _sbom(team, Component.Visibility.GATED)

        response = _visit_sbom(sbom, item_type=item_type)

        assert response.status_code == 403
        assert f"Please request access to view this {subject}." in response.content.decode()

    def test_an_sbom_from_another_component_keeps_that_components_answer(self, team):
        """``sbom_belongs_to_component``, the mirror of the document check."""
        gated = _sbom(team, Component.Visibility.GATED)
        elsewhere = _sbom(team, Component.Visibility.PRIVATE, component_name="Internal Platform")

        response = Client().get(
            reverse(
                "core:component_item_public",
                kwargs={
                    "component_id": gated.component.id,
                    "item_type": "sboms",
                    "item_id": elsewhere.id,
                },
            )
        )

        assert response.status_code == 403
        assert "Request Access" not in response.content.decode()

    def test_an_sbom_id_that_names_nothing_is_still_not_found(self, team):
        gated = _sbom(team, Component.Visibility.GATED)

        response = Client().get(
            reverse(
                "core:component_item_public",
                kwargs={
                    "component_id": gated.component.id,
                    "item_type": "sboms",
                    "item_id": "doesnotexist",
                },
            )
        )

        assert response.status_code == 404
        assert "Request Access" not in response.content.decode()

    def test_reader_with_a_grant_sees_the_sbom(self, team, sample_user):
        sbom = _sbom(team, Component.Visibility.GATED)
        Member.objects.create(team=team, user=sample_user, role="owner")

        response = _visit_sbom(sbom, sample_user)

        assert response.status_code == 200
        assert sbom.name in response.content.decode()

    def test_public_sbom_is_unaffected(self, team):
        sbom = _sbom(team, Component.Visibility.PUBLIC)

        response = _visit_sbom(sbom)

        assert response.status_code == 200
        assert sbom.name in response.content.decode()


class TestADenialAnAccessRequestCannotLift:
    """The gate answers for the refusal the fetch hit, not for a second opinion.

    ``can`` gates a scoped API token's actions before it consults visibility at
    all, and approving a request never widens a token's scopes, so a scope
    refusal has to keep its own generic 403: a Request Access page there would
    send the reader to ask for something that was never the problem.

    Exercised on the helper rather than through the route, because this HTML
    page carries no bearer auth today (``PersonalAccessTokenAuth`` is a Ninja
    security class, and nothing in ``MIDDLEWARE`` reads a token). The check is
    here so that stays true of the gate if it ever does.
    """

    def _reader(self, scopes: list[str] | None = None, with_token: bool = False):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.session = {}
        if with_token:
            request.access_token_record = SimpleNamespace(scopes=scopes)
        return request

    def test_a_token_outside_its_scope_keeps_its_own_refusal(self, team):
        document = _document(team, Component.Visibility.GATED)

        denial = ComponentItemPublicView._gated_denial(
            self._reader(scopes=SCOPE_PRESETS["publish"], with_token=True), document.component
        )

        assert denial is None

    def test_a_read_scoped_token_is_still_only_denied_by_the_gate(self, team):
        """Narrowing to reads leaves the refusal exactly where it was."""
        document = _document(team, Component.Visibility.GATED)

        denial = ComponentItemPublicView._gated_denial(
            self._reader(scopes=SCOPE_PRESETS["read_only"], with_token=True), document.component
        )

        assert denial is not None
        assert denial.reason == "gated_requires_authentication"

    def test_the_same_reader_carrying_no_token_gets_the_gate(self, team):
        document = _document(team, Component.Visibility.GATED)

        denial = ComponentItemPublicView._gated_denial(self._reader(), document.component)

        assert denial is not None
        assert denial.reason == "gated_requires_authentication"


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

    # Both assignments of the two names, because which one the scan reaches
    # first is the database's collation to decide, and only one of these two
    # orderings puts the gated component there. Pinning just one would pass on
    # whichever backend happened to sort the public name first.
    @pytest.mark.parametrize(
        ("public_name", "gated_name"),
        [("Policy Docs", "Policy-Docs"), ("Policy-Docs", "Policy Docs")],
    )
    def test_a_slug_collision_still_resolves_to_the_public_component(self, team, public_name, gated_name):
        """Component names are unique; the slugs derived from them are not.

        "Policy Docs" and "Policy-Docs" are two components sharing one URL, so
        letting gated components answer it puts them in a contest they were not
        in before. The public one keeps the slug: a link that worked must not
        start opening something else.
        """
        public_doc = _document(team, Component.Visibility.PUBLIC, component_name=public_name)
        gated_doc = _document(team, Component.Visibility.GATED, component_name=gated_name)
        assert public_doc.component.slug == gated_doc.component.slug

        response = Client(HTTP_HOST="trust.example.com").get(f"/component/{public_doc.component.slug}/")

        assert response.status_code == 200
        content = response.content.decode()
        assert public_name in content
        assert "Request Access" not in content

    def test_a_gated_component_takes_a_slug_no_public_one_answers(self, team):
        _document(team, Component.Visibility.PUBLIC, component_name="Policy Docs")
        gated_doc = _document(team, Component.Visibility.GATED, component_name="Vendor-Reviews")

        response = Client(HTTP_HOST="trust.example.com").get(f"/component/{gated_doc.component.slug}/")

        assert response.status_code == 200
        assert "Request Access" in response.content.decode()

    def test_a_shadowed_gated_component_points_back_at_itself(self, team):
        """Public wins the slug, so the id is the shadowed component's only way home.

        Rebuilding the component's computed slug for the gate's back link and
        its NDA action would send the reader to the public component that owns
        that slug, undoing the id they arrived on.
        """
        public_doc = _document(team, Component.Visibility.PUBLIC, component_name="Policy Docs")
        gated_doc = _document(team, Component.Visibility.GATED, component_name="Policy-Docs")
        assert public_doc.component.slug == gated_doc.component.slug

        response = Client(HTTP_HOST="trust.example.com").get(
            f"/components/{gated_doc.component.id}/documents/{gated_doc.id}/"
        )

        assert response.status_code == 403
        content = response.content.decode()
        assert f"/component/{gated_doc.component.id}/" in content
        assert f"/component/{gated_doc.component.slug}/" not in content

    def test_a_slug_collision_cannot_open_a_gated_artifact(self, team):
        """Whichever component the slug lands on, the artifact keeps its own gate.

        Access is checked against the artifact's own component rather than the
        one the URL resolved to, so a collision cannot be used to read a gated
        document through a public component's URL.
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
