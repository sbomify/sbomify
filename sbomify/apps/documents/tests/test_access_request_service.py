"""The access-request state changes the views and the API share."""

import pytest
from django.db import IntegrityError
from django.test import RequestFactory

from sbomify.apps.documents.access_models import AccessRequest, AccessRequestDecision, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.documents.services.access_requests import (
    approve_request,
    dismiss_access_request_notification_if_no_pending,
    record_nda_signature,
    reject_request,
    request_access,
    revoke_request,
)
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(team_with_business_plan):
    return team_with_business_plan


@pytest.fixture
def nda(team):
    document = Document.objects.create(
        name="Company NDA",
        component=team.get_or_create_company_wide_component(),
        document_type=Document.DocumentType.NDA,
        document_filename="nda.pdf",
    )
    team.branding_info["company_nda_document_id"] = document.id
    team.save()
    return document


def _sign(access_request, nda):
    return NDASignature.objects.create(
        access_request=access_request, nda_document=nda, nda_content_hash="0" * 64, signed_name="Guest User"
    )


class TestRequestAccess:
    def test_a_first_request_is_created_pending(self, team, guest_user):
        access_request, changed = request_access(team, guest_user)

        assert (access_request.status, changed) == (AccessRequest.Status.PENDING, True)

    @pytest.mark.parametrize("status", [AccessRequest.Status.PENDING, AccessRequest.Status.APPROVED])
    def test_an_open_request_comes_back_untouched(self, team, guest_user, status):
        existing = AccessRequest.objects.create(team=team, user=guest_user, status=status)

        access_request, changed = request_access(team, guest_user)

        assert (access_request.pk, access_request.status, changed) == (existing.pk, status, False)

    @pytest.mark.parametrize("status", [AccessRequest.Status.REJECTED, AccessRequest.Status.REVOKED])
    def test_a_closed_request_is_reopened_and_its_decision_kept(self, team, guest_user, sample_user, status):
        existing = AccessRequest.objects.create(team=team, user=guest_user, status=status, decided_by=sample_user)

        access_request, changed = request_access(team, guest_user)

        assert (access_request.pk, access_request.status, changed) == (existing.pk, AccessRequest.Status.PENDING, True)
        assert AccessRequestDecision.objects.get(access_request=existing).status == status

    def test_a_request_created_concurrently_is_returned_unchanged(self, team, guest_user, mocker):
        existing = AccessRequest.objects.create(team=team, user=guest_user)
        mocker.patch.object(
            AccessRequest.objects, "select_for_update"
        ).return_value.filter.return_value.first.return_value = None
        mocker.patch.object(AccessRequest.objects, "get_or_create", side_effect=IntegrityError)

        assert request_access(team, guest_user) == (existing, False)

    def test_a_request_deleted_mid_race_is_created_again(self, team, guest_user, mocker):
        created = AccessRequest(team=team, user=guest_user)
        mocker.patch.object(
            AccessRequest.objects, "select_for_update"
        ).return_value.filter.return_value.first.return_value = None
        mocker.patch.object(AccessRequest.objects, "get_or_create", side_effect=[IntegrityError, (created, True)])

        assert request_access(team, guest_user) == (created, True)


class TestDecisions:
    def test_approval_makes_the_requester_a_guest(self, team, guest_user, sample_user):
        access_request = AccessRequest.objects.create(team=team, user=guest_user)

        approve_request(access_request, sample_user)

        access_request.refresh_from_db()
        assert (access_request.status, access_request.decided_by) == (AccessRequest.Status.APPROVED, sample_user)
        assert access_request.decided_at is not None
        assert Member.objects.get(team=team, user=guest_user).role == "guest"

    def test_rejection_supersedes_the_live_signature(self, team, guest_user, sample_user, nda):
        access_request = AccessRequest.objects.create(team=team, user=guest_user)
        signature = _sign(access_request, nda)

        reject_request(access_request, sample_user)

        access_request.refresh_from_db()
        signature.refresh_from_db()
        assert (access_request.status, access_request.decided_by) == (AccessRequest.Status.REJECTED, sample_user)
        assert signature.superseded_at is not None

    def test_revocation_removes_only_the_guest_membership(self, team, guest_user, sample_user, nda):
        access_request = AccessRequest.objects.create(team=team, user=guest_user, status=AccessRequest.Status.APPROVED)
        Member.objects.create(team=team, user=guest_user, role="guest")
        signature = _sign(access_request, nda)

        revoke_request(access_request, sample_user)

        access_request.refresh_from_db()
        signature.refresh_from_db()
        assert (access_request.status, access_request.revoked_by) == (AccessRequest.Status.REVOKED, sample_user)
        assert not Member.objects.filter(team=team, user=guest_user).exists()
        assert signature.superseded_at is not None

    def test_revocation_leaves_a_member_who_is_not_a_guest(self, team, guest_user, sample_user):
        access_request = AccessRequest.objects.create(team=team, user=guest_user, status=AccessRequest.Status.APPROVED)
        Member.objects.create(team=team, user=guest_user, role="member")

        revoke_request(access_request, sample_user)

        assert Member.objects.get(team=team, user=guest_user).role == "member"


def test_a_signature_records_who_signed_from_where(team, guest_user, nda):
    access_request = AccessRequest.objects.create(team=team, user=guest_user)
    request = RequestFactory().post("/", REMOTE_ADDR="192.0.2.10", HTTP_USER_AGENT="x" * 600)

    signature, reloaded = record_nda_signature(request, access_request, nda, "a" * 64, "Guest User")

    assert (signature.signed_name, signature.nda_content_hash, signature.nda_document) == ("Guest User", "a" * 64, nda)
    assert signature.ip_address == "192.0.2.10"
    assert len(signature.user_agent) == 500
    assert list(reloaded.nda_signatures.all()) == [signature]


class TestDismissNotification:
    def _session_request(self, client):
        request = RequestFactory().get("/")
        request.session = client.session
        return request

    def test_no_pending_request_dismisses_it(self, client, team):
        request = self._session_request(client)

        dismiss_access_request_notification_if_no_pending(request, team)

        assert request.session["dismissed_notifications"] == [f"access_request_pending_{team.key}"]

    def test_a_pending_request_keeps_it(self, client, team, guest_user):
        AccessRequest.objects.create(team=team, user=guest_user)
        request = self._session_request(client)

        dismiss_access_request_notification_if_no_pending(request, team)

        assert "dismissed_notifications" not in request.session

    def test_a_request_still_waiting_on_its_nda_does_not_count(self, client, team, guest_user, nda):
        AccessRequest.objects.create(team=team, user=guest_user)
        request = self._session_request(client)

        dismiss_access_request_notification_if_no_pending(request, team)

        assert request.session["dismissed_notifications"] == [f"access_request_pending_{team.key}"]
