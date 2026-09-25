"""Access requests and NDA signatures come from a signed-in user, for themselves.

The request page already sends a visitor to sign in first. The API routes and
the page's POST handler still accepted a caller who was not signed in and took
an email address as their identity, binding the request to whichever account
held it, and the NDA routes let such a caller sign or fetch the NDA on any
pending request. They now need a signed-in user, who can only act for themselves.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.middleware.csrf import get_token
from django.test import Client, RequestFactory
from django.urls import reverse

from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db

NDA_CONTENT = b"Test NDA Content"


@pytest.fixture
def company_nda(team_with_business_plan):
    component = team_with_business_plan.get_or_create_company_wide_component()
    document = Document.objects.create(
        name="Company NDA",
        component=component,
        document_type=Document.DocumentType.NDA,
        document_filename="nda.pdf",
        content_type="application/pdf",
        file_size=len(NDA_CONTENT),
        content_hash=hashlib.sha256(NDA_CONTENT).hexdigest(),
        source="manual_upload",
        version="1.0",
    )
    team_with_business_plan.branding_info["company_nda_document_id"] = document.id
    team_with_business_plan.save()
    return document


@pytest.fixture
def pending_request(team_with_business_plan, guest_user):
    return AccessRequest.objects.create(
        team=team_with_business_plan, user=guest_user, status=AccessRequest.Status.PENDING
    )


@pytest.fixture
def nda_storage():
    with patch("sbomify.apps.documents.access_apis.StorageClient") as storage:
        client = MagicMock()
        client.get_document_data.return_value = NDA_CONTENT
        storage.return_value = client
        yield client


def _create_url(team) -> str:
    return reverse("api-1:create_access_request", kwargs={"team_key": team.key})


def _sign_url(team, access_request) -> str:
    return reverse("api-1:sign_nda", kwargs={"team_key": team.key, "request_id": access_request.id})


def _nda_url(team, access_request) -> str:
    return reverse("api-1:get_nda_for_signing", kwargs={"team_key": team.key, "request_id": access_request.id})


def _browser(user=None) -> Client:
    """A client that sends a valid CSRF token, as any visitor's browser can, signed in as `user` if given."""
    token = get_token(RequestFactory().get("/"))
    client = Client(enforce_csrf_checks=True, headers={"X-CSRFToken": token})
    client.cookies["csrftoken"] = token
    if user is not None:
        client.force_login(user)
    return client


def _post_json(client: Client, url: str, payload: dict) -> object:
    return client.post(url, json.dumps(payload), content_type="application/json")


def _assert_sends_to_sign_in(response, then: str) -> None:
    """The response sends the visitor to sign in, which then returns them to `then`."""
    assert response.status_code == 302
    location = urlsplit(response.url)
    assert location.path == reverse("core:keycloak_login")
    assert parse_qs(location.query) == {"next": [then]}


def test_anonymous_api_request_cannot_act_for_an_existing_account(team_with_business_plan, guest_user):
    response = _post_json(_browser(), _create_url(team_with_business_plan), {"email": guest_user.email})

    assert response.status_code == 401
    assert not AccessRequest.objects.filter(team=team_with_business_plan, user=guest_user).exists()


def test_anonymous_api_request_creates_no_account(team_with_business_plan):
    response = _post_json(_browser(), _create_url(team_with_business_plan), {"email": "someone@example.com"})

    assert response.status_code == 401
    assert not get_user_model().objects.filter(email="someone@example.com").exists()


def test_anonymous_caller_cannot_sign_a_pending_nda(team_with_business_plan, company_nda, pending_request, nda_storage):
    response = _post_json(
        _browser(), _sign_url(team_with_business_plan, pending_request), {"signed_name": "Someone", "consent": True}
    )

    assert response.status_code == 401
    assert not NDASignature.objects.filter(access_request=pending_request).exists()


def test_signed_in_user_cannot_sign_another_users_nda(
    team_with_business_plan, company_nda, pending_request, nda_storage, sample_user
):
    client = _browser(sample_user)

    response = _post_json(
        client, _sign_url(team_with_business_plan, pending_request), {"signed_name": "Someone", "consent": True}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"
    assert not NDASignature.objects.filter(access_request=pending_request).exists()


def test_anonymous_caller_cannot_fetch_the_nda(team_with_business_plan, company_nda, pending_request, nda_storage):
    response = Client().get(_nda_url(team_with_business_plan, pending_request))

    assert response.status_code == 401


def test_requester_can_fetch_their_nda(team_with_business_plan, company_nda, pending_request, nda_storage, guest_user):
    response = _browser(guest_user).get(_nda_url(team_with_business_plan, pending_request))

    assert response.status_code == 200
    assert response.content == NDA_CONTENT


@pytest.mark.parametrize(("role", "status"), [("owner", 200), ("admin", 200), ("member", 403), (None, 403)])
def test_only_an_owner_or_admin_can_fetch_someone_elses_nda(
    team_with_business_plan, company_nda, pending_request, nda_storage, role, status
):
    reader = get_user_model().objects.create_user(username="reader", email="reader@example.com")
    if role:
        Member.objects.create(team=team_with_business_plan, user=reader, role=role)

    response = _browser(reader).get(_nda_url(team_with_business_plan, pending_request))

    assert response.status_code == status


def test_requester_can_still_sign_their_own_nda(
    team_with_business_plan, company_nda, pending_request, nda_storage, guest_user
):
    client = _browser(guest_user)

    response = _post_json(
        client, _sign_url(team_with_business_plan, pending_request), {"signed_name": "Guest", "consent": True}
    )

    assert response.status_code == 200
    assert NDASignature.objects.filter(access_request=pending_request).exists()


def test_signed_in_api_request_still_works(team_with_business_plan, guest_user):
    client = _browser(guest_user)

    response = _post_json(client, _create_url(team_with_business_plan), {})

    assert response.status_code == 201
    assert AccessRequest.objects.filter(team=team_with_business_plan, user=guest_user).exists()


def test_anonymous_page_post_creates_nothing(team_with_business_plan):
    url = reverse("documents:request_access", kwargs={"team_key": team_with_business_plan.key})

    response = _browser().post(url, {"email": "visitor@example.com", "name": "Visitor"})

    _assert_sends_to_sign_in(response, then=url)
    assert not get_user_model().objects.filter(email="visitor@example.com").exists()
    assert not AccessRequest.objects.filter(team=team_with_business_plan).exists()


def _page_url(team, access_request) -> str:
    return reverse("documents:sign_nda", kwargs={"team_key": team.key, "request_id": access_request.id})


# Sign-in has to return the visitor to the whole link, escaped characters included.
NDA_PAGE_QUERY = "?a=1&b=two%20words&c=%2Fpath"


def test_anonymous_caller_is_sent_to_sign_in_from_the_nda_page(team_with_business_plan, company_nda, pending_request):
    url = _page_url(team_with_business_plan, pending_request) + NDA_PAGE_QUERY

    response = Client().get(url)

    _assert_sends_to_sign_in(response, then=url)


def test_anonymous_page_post_cannot_sign_a_pending_nda(team_with_business_plan, company_nda, pending_request):
    url = _page_url(team_with_business_plan, pending_request) + NDA_PAGE_QUERY
    with patch("sbomify.apps.documents.views.access_requests.StorageClient") as storage:
        storage.return_value.get_document_data.return_value = NDA_CONTENT
        response = _browser().post(url, {"signed_name": "Someone", "consent": "on"})

    _assert_sends_to_sign_in(response, then=url)
    assert not NDASignature.objects.filter(access_request=pending_request).exists()
