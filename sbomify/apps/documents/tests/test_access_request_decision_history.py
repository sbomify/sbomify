"""Asking for access again keeps the decision that closed the previous request.

The request row cycles back to pending, but the rejection or revocation it held,
with who made it, when and the notes, is copied to ``past_decisions`` first.
Both ways of asking again, the API and the request page, go through it.
"""

from __future__ import annotations

import json

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.documents.access_models import AccessRequest, AccessRequestDecision, NDASignature
from sbomify.apps.documents.models import Document

pytestmark = pytest.mark.django_db


def _ask_via_api(team, user):
    client = Client()
    client.force_login(user)
    url = reverse("api-1:create_access_request", kwargs={"team_key": team.key})
    return client.post(url, json.dumps({}), content_type="application/json")


def _ask_via_page(team, user):
    client = Client()
    client.force_login(user)
    return client.post(reverse("documents:request_access", kwargs={"team_key": team.key}), {})


@pytest.mark.parametrize(("ask", "expected_status"), [(_ask_via_api, 201), (_ask_via_page, 302)])
@pytest.mark.parametrize("status", [AccessRequest.Status.REJECTED, AccessRequest.Status.REVOKED])
def test_asking_again_keeps_the_previous_decision(
    team_with_business_plan, sample_user, guest_user, ask, expected_status, status
):
    decided_at = timezone.now()
    closed = {
        "decided_at": decided_at,
        "decided_by": sample_user,
        "notes": "Not a customer yet",
    }
    if status == AccessRequest.Status.REVOKED:
        closed |= {"revoked_at": decided_at, "revoked_by": sample_user}
    access_request = AccessRequest.objects.create(
        team=team_with_business_plan, user=guest_user, status=status, **closed
    )
    first_asked = access_request.requested_at

    assert ask(team_with_business_plan, guest_user).status_code == expected_status

    access_request.refresh_from_db()
    assert access_request.status == AccessRequest.Status.PENDING
    assert access_request.decided_by is None and access_request.notes == ""

    [past] = access_request.past_decisions.all()
    assert past.status == status
    assert past.requested_at == first_asked
    assert past.decided_at == decided_at
    assert past.decided_by == sample_user
    assert past.notes == "Not a customer yet"
    if status == AccessRequest.Status.REVOKED:
        assert past.revoked_at == decided_at
        assert past.revoked_by == sample_user


@pytest.mark.parametrize(("ask", "expected_status"), [(_ask_via_api, 201), (_ask_via_page, 302)])
def test_asking_again_supersedes_a_live_signature(team_with_business_plan, guest_user, ask, expected_status):
    nda = Document.objects.create(
        name="NDA",
        component=team_with_business_plan.get_or_create_company_wide_component(),
        document_type=Document.DocumentType.NDA,
    )
    access_request = AccessRequest.objects.create(
        team=team_with_business_plan, user=guest_user, status=AccessRequest.Status.REJECTED
    )
    signature = NDASignature.objects.create(access_request=access_request, nda_document=nda, signed_name="Guest")

    assert ask(team_with_business_plan, guest_user).status_code == expected_status

    signature.refresh_from_db()
    assert signature.superseded_at is not None
    assert access_request.nda_signature is None


def test_each_cycle_adds_a_decision(team_with_business_plan, sample_user, guest_user):
    access_request = AccessRequest.objects.create(
        team=team_with_business_plan, user=guest_user, status=AccessRequest.Status.REJECTED, decided_by=sample_user
    )
    assert _ask_via_api(team_with_business_plan, guest_user).status_code == 201
    AccessRequest.objects.filter(pk=access_request.pk).update(status=AccessRequest.Status.REJECTED)
    assert _ask_via_api(team_with_business_plan, guest_user).status_code == 201

    assert access_request.past_decisions.count() == 2


def test_a_pending_request_is_not_archived(team_with_business_plan, guest_user):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)

    assert _ask_via_api(team_with_business_plan, guest_user).status_code == 400

    assert not access_request.past_decisions.exists()


@pytest.mark.parametrize("status", [AccessRequest.Status.PENDING, AccessRequest.Status.APPROVED])
def test_only_a_closed_request_can_be_reopened(team_with_business_plan, guest_user, status):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user, status=status)

    with pytest.raises(ValueError):
        access_request.reopen()

    access_request.refresh_from_db()
    assert access_request.status == status
    assert not access_request.past_decisions.exists()


def test_a_decision_row_holds_only_a_closed_status(team_with_business_plan, guest_user):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)

    with pytest.raises(IntegrityError), transaction.atomic():
        AccessRequestDecision.objects.create(
            access_request=access_request, status=AccessRequest.Status.PENDING, requested_at=timezone.now()
        )
