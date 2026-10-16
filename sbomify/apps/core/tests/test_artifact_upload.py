"""The upload picker: Spotlight's upload actions end on a component's upload dialog.

Uploads happen on a component page. These pin the three outcomes that keep the
next step visible (no candidate, one, many) and the gate that keeps the page
from offering a link the upload API would refuse.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils.html import escape

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.services.artifact_upload import FORBIDDEN_MESSAGE, UPLOAD_KINDS, upload_targets
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member, Workspace

pytestmark = pytest.mark.django_db

UPLOAD_URL = reverse("core:artifact_upload")
BOM_KINDS = ("sbom", "cbom", "vex")


def _client(team: Workspace, role: str) -> Client:
    user = get_user_model().objects.create_user(username=f"{role}-uploader", email=f"{role}-uploader@example.com")
    Member.objects.create(team=team, user=user, role=role)
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


def _bom(team: Workspace, name: str, *, with_sbom: bool = False) -> Component:
    component = Component.objects.create(team=team, name=name, component_type=Component.ComponentType.BOM)
    if with_sbom:
        SBOM.objects.create(name=name, component=component, format="cyclonedx", format_version="1.6")
    return component


def _document(team: Workspace, name: str) -> Component:
    return Component.objects.create(team=team, name=name, component_type=Component.ComponentType.DOCUMENT)


@pytest.fixture
def team(sample_team_with_owner_member) -> Workspace:
    return sample_team_with_owner_member.team


@pytest.fixture
def member_client(team) -> Client:
    return _client(team, "member")


def _detail(component: Component, fragment: str) -> str:
    return f"{reverse('core:component_details', args=[component.id])}#{fragment}"


class TestOneComponent:
    @pytest.mark.parametrize("kind", BOM_KINDS)
    def test_a_single_bom_component_opens_its_dialog(self, team, member_client, kind):
        component = _bom(team, "Payments")
        _document(team, "Policies")

        response = member_client.get(UPLOAD_URL, {"type": kind})

        assert response.status_code == 302
        assert response["Location"] == _detail(component, f"upload-{kind}")

    def test_a_single_document_component_opens_the_document_uploader(self, team, member_client):
        component = _document(team, "Policies")
        _bom(team, "Payments")

        response = member_client.get(UPLOAD_URL, {"type": "document"})

        assert response.status_code == 302
        assert response["Location"] == _detail(component, "upload-artifact")


class TestManyComponents:
    def test_vex_lists_bom_components_with_an_sbom_first(self, team, member_client):
        alpha = _bom(team, "Alpha")
        zulu = _bom(team, "Zulu", with_sbom=True)
        _document(team, "Policies")
        product = Product.objects.create(team=team, name="Storefront")
        product.components.add(zulu)

        response = member_client.get(UPLOAD_URL, {"type": "vex"})

        assert response.status_code == 200
        rows = response.context["rows"]
        assert [row["name"] for row in rows] == ["Zulu", "Alpha"]
        assert rows[0]["products"] == ["Storefront"]
        body = response.content.decode()
        assert _detail(zulu, "upload-vex") in body
        assert _detail(alpha, "upload-vex") in body
        assert "Policies" not in body
        assert body.count("No SBOM yet") == 1
        assert "Upload VEX" in body

    def test_sbom_keeps_name_order_and_does_not_ask_for_an_sbom(self, team, member_client):
        _bom(team, "Zulu", with_sbom=True)
        _bom(team, "Alpha")

        response = member_client.get(UPLOAD_URL, {"type": "sbom"})

        assert [row["name"] for row in response.context["rows"]] == ["Alpha", "Zulu"]
        assert "No SBOM yet" not in response.content.decode()

    def test_the_filter_is_on_the_page_and_the_copy_has_no_dashes(self, team, member_client):
        _bom(team, "Alpha")
        _bom(team, "Zulu")

        body = member_client.get(UPLOAD_URL, {"type": "cbom"}).content.decode()

        assert 'id="upload-target-search"' in body
        assert "Filter components" in body
        page = body[body.index('id="artifact-upload-page"') :]
        assert "—" not in page
        assert "–" not in page


class TestNoComponents:
    def test_no_bom_component_offers_to_create_one(self, team, member_client):
        _document(team, "Policies")

        response = member_client.get(UPLOAD_URL, {"type": "vex"})

        assert response.status_code == 200
        body = response.content.decode()
        assert "No components yet" in body
        assert UPLOAD_KINDS["vex"].empty_message in body
        assert f"{reverse('core:component_new')}?type=bom" in body
        assert "#upload-" not in body

    def test_document_with_only_bom_components_is_empty(self, team, member_client):
        _bom(team, "Payments")

        response = member_client.get(UPLOAD_URL, {"type": "document"})

        assert response.status_code == 200
        body = response.content.decode()
        assert UPLOAD_KINDS["document"].empty_message in body
        assert f"{reverse('core:component_new')}?type=document" in body

    def test_the_new_component_form_opens_on_the_requested_type(self, member_client):
        body = member_client.get(reverse("core:component_new"), {"type": "document"}).content.decode()

        assert "componentType: 'document'" in body


class TestIsolation:
    def test_another_workspaces_components_never_appear(self, team, member_client):
        other = Workspace.objects.create(name="Elsewhere")
        _bom(other, "Foreign")
        _bom(team, "Home")
        _bom(team, "Second")

        body = member_client.get(UPLOAD_URL, {"type": "sbom"}).content.decode()

        assert "Foreign" not in body

    def test_another_workspaces_component_does_not_trigger_the_redirect(self, team, member_client):
        other = Workspace.objects.create(name="Elsewhere")
        _bom(other, "Foreign")

        response = member_client.get(UPLOAD_URL, {"type": "sbom"})

        assert response.status_code == 200
        assert "No components yet" in response.content.decode()


class TestAccess:
    @pytest.mark.parametrize("query", [{}, {"type": "aibom"}, {"type": ""}])
    def test_a_missing_or_unknown_type_is_not_found(self, member_client, query):
        assert member_client.get(UPLOAD_URL, query).status_code == 404

    @pytest.mark.parametrize("kind", [*BOM_KINDS, "document"])
    def test_an_operator_is_refused(self, team, kind):
        _bom(team, "Payments")

        response = _client(team, "operator").get(UPLOAD_URL, {"type": kind})

        assert response.status_code == 403
        assert escape(FORBIDDEN_MESSAGE) in response.content.decode()

    def test_a_guest_is_sent_to_the_public_page(self, team):
        response = _client(team, "guest").get(UPLOAD_URL, {"type": "sbom"})

        assert response.status_code == 302
        assert response["Location"] == reverse("core:workspace_public", kwargs={"workspace_key": team.key})

    def test_an_anonymous_visitor_is_sent_to_sign_in(self):
        response = Client().get(UPLOAD_URL, {"type": "sbom"})

        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_no_workspace_in_session_is_refused(self, member_client):
        session = member_client.session
        session.pop("current_workspace", None)
        session.save()

        assert member_client.get(UPLOAD_URL, {"type": "sbom"}).status_code == 403

    @pytest.mark.parametrize("role", ["owner", "admin", "member"])
    def test_upload_roles_are_admitted(self, team, role):
        _bom(team, "Payments")
        _bom(team, "Ledger")

        response = _client(team, role).get(UPLOAD_URL, {"type": "vex"})

        assert response.status_code == 200


class TestUploadTargetsService:
    def _request(self, member: Member) -> Any:
        setup_authenticated_client_session(Client(), member.team, member.user)
        request: Any = RequestFactory().get(UPLOAD_URL)
        request.user = member.user
        request.session = {"current_workspace": {"key": member.team.key}}
        return request

    def test_failure_codes_and_messages(self, sample_team_with_owner_member):
        request = self._request(sample_team_with_owner_member)

        unknown = upload_targets(request, "aibom")
        assert (unknown.ok, unknown.status_code) == (False, 404)

        request.session = {}
        no_workspace = upload_targets(request, "sbom")
        assert (no_workspace.ok, no_workspace.status_code, no_workspace.error) == (False, 403, FORBIDDEN_MESSAGE)

    def test_the_row_shape(self, sample_team_with_owner_member):
        member = sample_team_with_owner_member
        component = _bom(member.team, "Payments", with_sbom=True)

        result = upload_targets(self._request(member), "cbom")

        assert result.ok and result.value is not None
        assert result.value["label"] == "CBOM"
        assert result.value["rows"] == [
            {
                "id": component.id,
                "name": "Payments",
                "products": [],
                "has_sbom": True,
                "url": _detail(component, "upload-cbom"),
            }
        ]

    def test_only_vex_needs_the_triage_capability(self, sample_team_with_owner_member):
        from sbomify.apps.core.authz import Decision

        request = self._request(sample_team_with_owner_member)

        def deny_vex(actor, action, resource):
            return Decision(action != "artifact:publish_vex")

        with patch("sbomify.apps.core.services.artifact_upload.can", side_effect=deny_vex):
            outcomes = {kind: upload_targets(request, kind).status_code for kind in UPLOAD_KINDS}

        assert outcomes == {"sbom": None, "cbom": None, "vex": 403, "document": None}

    @pytest.mark.parametrize("denied", ["component:manage", "artifact:publish"])
    def test_upload_needs_both_the_page_and_the_api_capability(self, sample_team_with_owner_member, denied):
        from sbomify.apps.core.authz import Decision

        request = self._request(sample_team_with_owner_member)

        with patch(
            "sbomify.apps.core.services.artifact_upload.can",
            side_effect=lambda actor, action, resource: Decision(action != denied),
        ):
            assert upload_targets(request, "sbom").status_code == 403

    def test_ordering_puts_components_with_an_sbom_first_then_name(self, sample_team_with_owner_member):
        member = sample_team_with_owner_member
        for name, with_sbom in [("Delta", False), ("Charlie", True), ("Bravo", False), ("Alpha", True)]:
            _bom(member.team, name, with_sbom=with_sbom)
        request = self._request(member)

        def names(kind: str) -> list[str]:
            result = upload_targets(request, kind)
            assert result.value is not None
            return [row["name"] for row in result.value["rows"]]

        vex, sbom = names("vex"), names("sbom")

        assert vex == ["Alpha", "Charlie", "Bravo", "Delta"]
        assert sbom == ["Alpha", "Bravo", "Charlie", "Delta"]
