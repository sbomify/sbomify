"""Signing a reader in on a Trust Center served from its own host.

A Trust Center lives on a custom domain or a Trust Center subdomain, where the
app domain's session cookie is never sent. An approved reader was therefore
anonymous on every page that offered them their gated artifacts, and could not
download any of them. These tests walk the handoff that signs them in there,
and pin down how little the session it creates is allowed to do.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Member, Workspace

TRUST_HOST = "trust.example.com"
APP_HOST = "localhost"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _workspace(name: str, domain: str | None) -> Workspace:
    workspace = Workspace.objects.create(
        name=name, billing_plan="business", custom_domain=domain, custom_domain_validated=bool(domain)
    )
    workspace.is_public = True
    workspace.save(update_fields=["is_public"])
    return workspace


def _gated_document(team: Workspace, name: str = "Gated") -> Document:
    component = Component.objects.create(
        name=name,
        team=team,
        component_type=Component.ComponentType.DOCUMENT,
        visibility=Component.Visibility.GATED,
    )
    return Document.objects.create(
        name=f"{name} report",
        component=component,
        document_type=Document.DocumentType.SPECIFICATION,
        document_filename=f"{name}.pdf",
        content_type="application/pdf",
        source="manual_upload",
    )


def _approve(team: Workspace, user) -> None:
    AccessRequest.objects.create(team=team, user=user, status=AccessRequest.Status.APPROVED)
    Member.objects.create(team=team, user=user, role="guest")


@pytest.fixture
def team():
    return _workspace("Gating Co", TRUST_HOST)


@pytest.fixture
def reader():
    return get_user_model().objects.create_user(username="reader", email="reader@example.com", password="x")


def _download(client: Client, document: Document):
    with patch("sbomify.apps.documents.views.document_download.StorageClient") as storage:
        storage.return_value = MagicMock(get_document_data=MagicMock(return_value=b"gated bytes"))
        return client.get(reverse("documents:document_download", kwargs={"document_id": document.id}))


def _handoff_url(team: Workspace, reader, next_path: str = "/") -> str:
    """Sign in on the app domain and confirm; return where it sends the reader."""
    app = Client(HTTP_HOST=APP_HOST)
    app.force_login(reader)
    response = app.post(
        reverse("core:trust_center_sign_in", kwargs={"workspace_key": team.key}),
        {"next": next_path},
    )
    assert response.status_code == 302
    return response["Location"]


def _signed_in_trust_center(team: Workspace, reader, host: str = TRUST_HOST) -> Client:
    location = urlsplit(_handoff_url(team, reader))
    client = Client(HTTP_HOST=host)
    response = client.get(f"{location.path}?{location.query}")
    assert response.status_code == 302
    return client


@pytest.mark.django_db
class TestApprovedReaderOnTheTrustCenterHost:
    def test_an_approved_reader_is_anonymous_there_without_the_handoff(self, team, reader):
        document = _gated_document(team)
        _approve(team, reader)

        assert _download(Client(HTTP_HOST=TRUST_HOST), document).status_code == 403

    def test_signing_in_from_the_trust_center_goes_through_the_app_domain(self, team):
        response = Client(HTTP_HOST=TRUST_HOST).get("/login/", {"next": "/component/x/"})

        assert response.status_code == 302
        location = urlsplit(response["Location"])
        assert location.netloc == "localhost:8001"
        assert location.path == reverse("core:trust_center_sign_in", kwargs={"workspace_key": team.key})
        assert parse_qs(location.query)["next"] == ["/component/x/"]

    def test_the_app_domain_asks_before_handing_over(self, team, reader):
        app = Client(HTTP_HOST=APP_HOST)
        app.force_login(reader)

        response = app.get(reverse("core:trust_center_sign_in", kwargs={"workspace_key": team.key}), {"next": "/x/"})

        assert response.status_code == 200
        content = response.content.decode()
        assert TRUST_HOST in content
        assert reader.email in content

    def test_the_handoff_points_at_the_workspace_own_host(self, team, reader):
        location = urlsplit(_handoff_url(team, reader, "/component/x/"))

        assert location.netloc == TRUST_HOST
        assert location.path == reverse("core:trust_center_session")
        assert parse_qs(location.query)["next"] == ["/component/x/"]

    def test_an_approved_reader_downloads_after_the_handoff(self, team, reader):
        document = _gated_document(team)
        _approve(team, reader)

        client = _signed_in_trust_center(team, reader)

        response = _download(client, document)
        assert response.status_code == 200
        assert response.content == b"gated bytes"

    def test_the_handoff_lands_on_the_page_the_reader_came_from(self, team, reader):
        location = urlsplit(_handoff_url(team, reader, "/component/x/"))

        response = Client(HTTP_HOST=TRUST_HOST).get(f"{location.path}?{location.query}")

        assert response["Location"] == "/component/x/"

    def test_an_absolute_next_is_not_followed(self, team, reader):
        location = urlsplit(_handoff_url(team, reader, "//evil.example.net/"))

        response = Client(HTTP_HOST=TRUST_HOST).get(f"{location.path}?{location.query}")

        assert response["Location"] == "/"

    def test_a_reader_still_waiting_is_still_refused(self, team, reader):
        document = _gated_document(team)
        AccessRequest.objects.create(team=team, user=reader, status=AccessRequest.Status.PENDING)

        client = _signed_in_trust_center(team, reader)

        assert _download(client, document).status_code == 403


@pytest.mark.django_db
class TestHandoffToken:
    def test_a_token_works_once(self, team, reader):
        location = urlsplit(_handoff_url(team, reader))
        url = f"{location.path}?{location.query}"

        assert Client(HTTP_HOST=TRUST_HOST).get(url).status_code == 302
        assert Client(HTTP_HOST=TRUST_HOST).get(url).status_code == 400

    def test_a_token_is_refused_on_another_host(self, team, reader):
        _workspace("Other Co", "trust.other.example.com")
        location = urlsplit(_handoff_url(team, reader))

        response = Client(HTTP_HOST="trust.other.example.com").get(f"{location.path}?{location.query}")

        assert response.status_code == 400

    def test_a_tampered_token_is_refused(self, team, reader):
        location = urlsplit(_handoff_url(team, reader))
        token = parse_qs(location.query)["token"][0]

        response = Client(HTTP_HOST=TRUST_HOST).get(reverse("core:trust_center_session"), {"token": token + "x"})

        assert response.status_code == 400

    def test_the_session_endpoint_does_nothing_on_the_app_domain(self, team, reader):
        location = urlsplit(_handoff_url(team, reader))

        response = Client(HTTP_HOST=APP_HOST).get(f"{location.path}?{location.query}")

        assert response.status_code == 404

    def test_the_handoff_is_not_offered_from_a_trust_center_host(self, team, reader):
        client = Client(HTTP_HOST=TRUST_HOST)
        client.force_login(reader)

        response = client.post(reverse("core:trust_center_sign_in", kwargs={"workspace_key": team.key}))

        assert response.status_code == 404

    def test_a_workspace_without_its_own_host_has_nothing_to_hand_over_to(self, reader):
        plain = _workspace("Plain Co", None)
        app = Client(HTTP_HOST=APP_HOST)
        app.force_login(reader)

        response = app.post(reverse("core:trust_center_sign_in", kwargs={"workspace_key": plain.key}))

        assert response.status_code == 404


@pytest.mark.django_db
class TestScopedSession:
    def test_the_session_is_anonymous_on_the_app_domain(self, team, reader):
        client = _signed_in_trust_center(team, reader)
        cookie = client.cookies["sessionid"].value

        app = Client(HTTP_HOST=APP_HOST)
        app.cookies["sessionid"] = cookie
        response = app.get(reverse("core:trust_center_access"))

        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_the_session_does_not_reach_the_app_on_the_trust_center_host(self, team, reader):
        client = _signed_in_trust_center(team, reader)

        response = client.get(reverse("core:trust_center_access"))

        assert response.status_code == 302

    def test_the_session_does_not_reach_another_workspace(self, team, reader):
        other = _workspace("Other Co", "trust.other.example.com")
        elsewhere = _gated_document(other, "Elsewhere")
        _approve(other, reader)
        _approve(team, reader)

        client = _signed_in_trust_center(team, reader)

        assert _download(client, elsewhere).status_code == 403

    def test_the_session_does_not_ask_another_workspace_for_access(self, team, reader):
        other = _workspace("Other Co", "trust.other.example.com")
        client = _signed_in_trust_center(team, reader)

        client.post(reverse("documents:request_access", kwargs={"workspace_key": other.key}))

        assert not AccessRequest.objects.filter(team=other, user=reader).exists()

    def test_the_session_asks_its_own_workspace_for_access(self, team, reader):
        client = _signed_in_trust_center(team, reader)

        client.post(reverse("documents:request_access", kwargs={"workspace_key": team.key}))

        assert AccessRequest.objects.filter(team=team, user=reader, status=AccessRequest.Status.PENDING).exists()

    def test_signing_out_of_the_trust_center_stays_on_it(self, team, reader):
        client = _signed_in_trust_center(team, reader)

        response = client.get(reverse("core:logout"))

        assert response["Location"] == "/"
        document = _gated_document(team)
        _approve(team, reader)
        assert _download(client, document).status_code == 403


@pytest.mark.django_db
class TestTrustCenterAccessPage:
    def test_lists_every_request_with_its_status(self, team, reader):
        plain = _workspace("Plain Co", None)
        AccessRequest.objects.create(team=team, user=reader, status=AccessRequest.Status.APPROVED)
        AccessRequest.objects.create(team=plain, user=reader, status=AccessRequest.Status.PENDING)
        app = Client(HTTP_HOST=APP_HOST)
        app.force_login(reader)

        response = app.get(reverse("core:trust_center_access"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "Gating Co" in content
        assert "Plain Co" in content
        assert "Access granted" in content
        assert "Waiting for review" in content
        # A Trust Center on its own host is linked through the handoff, so the
        # reader arrives signed in; one on the app domain is linked directly.
        assert reverse("core:trust_center_sign_in", kwargs={"workspace_key": team.key}) in content
        assert reverse("core:workspace_public", kwargs={"workspace_key": plain.key}) in content

    def test_shows_only_the_signed_in_reader_requests(self, team, reader):
        someone = get_user_model().objects.create_user(username="someone", email="someone@example.com")
        AccessRequest.objects.create(team=team, user=someone, status=AccessRequest.Status.APPROVED)
        app = Client(HTTP_HOST=APP_HOST)
        app.force_login(reader)

        response = app.get(reverse("core:trust_center_access"))

        assert "Gating Co" not in response.content.decode()
        assert "No access requests" in response.content.decode()

    def test_a_guest_reaches_it_from_the_workspace_they_asked(self, team, reader):
        _approve(team, reader)
        app = Client(HTTP_HOST=APP_HOST)
        app.force_login(reader)
        session = app.session
        session["current_workspace"] = {"key": team.key, "role": "guest", "name": team.name}
        session.save()

        response = app.get(reverse("core:trust_center_access"))

        assert response.status_code == 200
