"""The access-request API honours an API token's action scopes and workspace binding.

Deciding a request, listing the pending queue, filing a request and reading or
signing its NDA each go through can(), so a token reaches them only when its
scope grants the action. A full (unscoped) token keeps today's behaviour.
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db

NDA_CONTENT = b"Test NDA Content"
NARROW_PRESETS = ["read_only", "publish"]


@pytest.fixture
def company_nda(team_with_business_plan):
    team = team_with_business_plan
    document = Document.objects.create(
        name="Company NDA",
        component=team.get_or_create_company_wide_component(),
        document_type=Document.DocumentType.NDA,
        document_filename="nda.pdf",
        content_type="application/pdf",
        content_hash=hashlib.sha256(NDA_CONTENT).hexdigest(),
    )
    team.branding_info["company_nda_document_id"] = document.id
    team.save()
    return document


@pytest.fixture(autouse=True)
def nda_storage():
    with patch("sbomify.apps.documents.access_apis.StorageClient") as storage:
        storage.return_value = MagicMock(get_document_data=MagicMock(return_value=NDA_CONTENT))
        yield


def _scoped(api_client, scopes, team=None):
    client, token = api_client
    token.scopes = scopes
    token.team = team
    token.save(update_fields=["scopes", "team"])
    return client, get_api_headers(token)


def _decide(api_client, access_request, verb, scopes):
    client, headers = _scoped(api_client, scopes)
    url = reverse(f"api-1:{verb}_access_request", kwargs={"request_id": access_request.id})
    return client.post(url, **headers)


_DECISIONS = [("approve", "pending"), ("reject", "pending"), ("revoke", "approved")]


@pytest.mark.parametrize("preset", NARROW_PRESETS)
@pytest.mark.parametrize("verb,status", _DECISIONS)
def test_a_narrow_token_cannot_decide_a_request(
    authenticated_api_client, team_with_business_plan, guest_user, preset, verb, status
):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user, status=status)

    response = _decide(authenticated_api_client, access_request, verb, SCOPE_PRESETS[preset])

    assert response.status_code == 403
    access_request.refresh_from_db()
    assert access_request.status == status
    assert access_request.decided_by is None and access_request.revoked_by is None


@pytest.mark.parametrize("verb,status", _DECISIONS)
def test_a_full_token_still_decides_a_request(
    authenticated_api_client, team_with_business_plan, guest_user, verb, status
):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user, status=status)

    response = _decide(authenticated_api_client, access_request, verb, SCOPE_PRESETS["full"])

    assert response.status_code == 200


def test_a_token_bound_to_another_workspace_cannot_approve(
    authenticated_api_client, team_with_business_plan, guest_user, sample_user
):
    other = Team.objects.create(name="Other")
    Member.objects.create(team=other, user=sample_user, role="owner")
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)
    client, headers = _scoped(authenticated_api_client, None, team=other)

    response = client.post(reverse("api-1:approve_access_request", kwargs={"request_id": access_request.id}), **headers)

    assert response.status_code == 403
    assert not Member.objects.filter(team=team_with_business_plan, user=guest_user).exists()


@pytest.mark.parametrize("preset,expected", [("read_only", 200), ("publish", 403), ("full", 200)])
def test_the_pending_queue_needs_read_scope(authenticated_api_client, team_with_business_plan, preset, expected):
    client, headers = _scoped(authenticated_api_client, SCOPE_PRESETS[preset])

    response = client.get(reverse("api-1:list_pending_access_requests"), **headers)

    assert response.status_code == expected


@pytest.mark.parametrize("preset", NARROW_PRESETS)
def test_a_narrow_token_cannot_file_a_request(guest_api_client, team_with_business_plan, preset):
    client, headers = _scoped(guest_api_client, SCOPE_PRESETS[preset])

    response = client.post(
        reverse("api-1:create_access_request", kwargs={"team_key": team_with_business_plan.key}), **headers
    )

    assert response.status_code == 403
    assert not AccessRequest.objects.filter(team=team_with_business_plan).exists()


def test_a_full_token_still_files_a_request(guest_api_client, team_with_business_plan):
    client, headers = _scoped(guest_api_client, SCOPE_PRESETS["full"])

    response = client.post(
        reverse("api-1:create_access_request", kwargs={"team_key": team_with_business_plan.key}), **headers
    )

    assert response.status_code == 201


def test_a_token_bound_to_another_workspace_cannot_file_a_request(
    guest_api_client, team_with_business_plan, guest_user
):
    own = Team.objects.create(name="Own")
    Member.objects.create(team=own, user=guest_user, role="owner")
    client, headers = _scoped(guest_api_client, None, team=own)

    response = client.post(
        reverse("api-1:create_access_request", kwargs={"team_key": team_with_business_plan.key}), **headers
    )

    assert response.status_code == 403


def _nda_urls(team, access_request):
    kwargs = {"team_key": team.key, "request_id": access_request.id}
    return reverse("api-1:get_nda_for_signing", kwargs=kwargs), reverse("api-1:sign_nda", kwargs=kwargs)


@pytest.mark.parametrize("preset", NARROW_PRESETS)
def test_a_narrow_token_cannot_read_or_sign_the_nda(
    guest_api_client, team_with_business_plan, guest_user, company_nda, preset
):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)
    nda_url, sign_url = _nda_urls(team_with_business_plan, access_request)
    client, headers = _scoped(guest_api_client, SCOPE_PRESETS[preset])

    assert client.get(nda_url, **headers).status_code == 403
    response = client.post(
        sign_url, {"signed_name": "Guest", "consent": True}, content_type="application/json", **headers
    )

    assert response.status_code == 403
    assert not NDASignature.objects.filter(access_request=access_request).exists()


def test_a_full_token_still_reads_and_signs_the_nda(guest_api_client, team_with_business_plan, guest_user, company_nda):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)
    nda_url, sign_url = _nda_urls(team_with_business_plan, access_request)
    client, headers = _scoped(guest_api_client, SCOPE_PRESETS["full"])

    assert client.get(nda_url, **headers).status_code == 200
    response = client.post(
        sign_url, {"signed_name": "Guest", "consent": True}, content_type="application/json", **headers
    )

    assert response.status_code == 200


@pytest.mark.parametrize("preset,expected", [("read_only", 200), ("publish", 403)])
def test_an_admin_reads_someone_elses_nda_with_read_scope(
    authenticated_api_client, team_with_business_plan, guest_user, company_nda, preset, expected
):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)
    nda_url, _ = _nda_urls(team_with_business_plan, access_request)
    client, headers = _scoped(authenticated_api_client, SCOPE_PRESETS[preset])

    assert client.get(nda_url, **headers).status_code == expected
