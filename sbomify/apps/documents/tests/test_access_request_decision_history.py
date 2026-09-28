"""Asking for access again keeps the decision that closed the previous request.

The request row cycles back to pending, but the rejection or revocation it held,
with who made it, when and the notes, is copied to ``past_decisions`` first.
Both ways of asking again, the API and the request page, go through it.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.documents.access_models import AccessRequest

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


@pytest.mark.parametrize("ask", [_ask_via_api, _ask_via_page])
@pytest.mark.parametrize("status", [AccessRequest.Status.REJECTED, AccessRequest.Status.REVOKED])
def test_asking_again_keeps_the_previous_decision(team_with_business_plan, sample_user, guest_user, ask, status):
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

    ask(team_with_business_plan, guest_user)

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


def test_each_cycle_adds_a_decision(team_with_business_plan, sample_user, guest_user):
    access_request = AccessRequest.objects.create(
        team=team_with_business_plan, user=guest_user, status=AccessRequest.Status.REJECTED, decided_by=sample_user
    )
    _ask_via_api(team_with_business_plan, guest_user)
    AccessRequest.objects.filter(pk=access_request.pk).update(status=AccessRequest.Status.REJECTED)
    _ask_via_api(team_with_business_plan, guest_user)

    assert access_request.past_decisions.count() == 2


def test_a_pending_request_is_not_archived(team_with_business_plan, guest_user):
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)

    _ask_via_api(team_with_business_plan, guest_user)

    assert not access_request.past_decisions.exists()
