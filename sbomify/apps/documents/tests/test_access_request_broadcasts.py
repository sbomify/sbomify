"""Access requests decided or raised in the web UI tell the workspace.

The trust-center queue and the bell repaint on ``access_request_updated``. The
API copies of these actions already sent it; the views the UI actually posts to
did not, so another admin's queue stayed stale until a reload.
"""

from typing import Any
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.documents.access_models import AccessRequest

BROADCAST = "sbomify.apps.documents.views.access_requests.broadcast_to_workspace"


def _request(team: Any, user: Any, status: str, decided_by: Any = None) -> AccessRequest:
    return AccessRequest.objects.create(
        team=team,
        user=user,
        status=status,
        decided_by=decided_by,
        decided_at=timezone.now() if decided_by else None,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action", "starting", "announced"),
    [
        ("approve", AccessRequest.Status.PENDING, "approved"),
        ("reject", AccessRequest.Status.PENDING, "rejected"),
        ("revoke", AccessRequest.Status.APPROVED, "revoked"),
        ("clear_rejection", AccessRequest.Status.REJECTED, "cleared"),
    ],
)
def test_a_queue_decision_broadcasts_once_committed(
    action: str,
    starting: str,
    announced: str,
    authenticated_web_client: Any,
    team_with_business_plan: Any,
    sample_user: Any,
    guest_user: Any,
    django_capture_on_commit_callbacks: Any,
) -> None:
    access_request = _request(team_with_business_plan, guest_user, starting, decided_by=sample_user)
    request_id = str(access_request.id)
    setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
    url = reverse("documents:access_request_queue", kwargs={"workspace_key": team_with_business_plan.key})

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        response = authenticated_web_client.post(
            url, {"action": action, "request_id": request_id, "active_tab": "trust-center"}
        )

    assert response.status_code in (200, 302)
    mock_broadcast.assert_called_once_with(
        workspace_key=team_with_business_plan.key,
        message_type="access_request_updated",
        data={
            "access_request_id": request_id,
            "user_id": str(guest_user.id),
            "status": announced,
            "action": announced,
        },
    )


@pytest.mark.django_db
def test_a_refused_decision_broadcasts_nothing(
    authenticated_web_client: Any,
    team_with_business_plan: Any,
    sample_user: Any,
    guest_user: Any,
    django_capture_on_commit_callbacks: Any,
) -> None:
    access_request = _request(team_with_business_plan, guest_user, AccessRequest.Status.REJECTED, sample_user)
    setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
    url = reverse("documents:access_request_queue", kwargs={"workspace_key": team_with_business_plan.key})

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        authenticated_web_client.post(url, {"action": "approve", "request_id": access_request.id})

    mock_broadcast.assert_not_called()


@pytest.mark.django_db
def test_a_new_request_from_the_web_broadcasts(
    authenticated_web_client: Any,
    team_with_business_plan: Any,
    guest_user: Any,
    django_capture_on_commit_callbacks: Any,
) -> None:
    authenticated_web_client.force_login(guest_user)
    session = authenticated_web_client.session
    session["current_workspace"] = {"key": team_with_business_plan.key, "role": None, "name": "x"}
    session.save()
    url = reverse("documents:request_access", kwargs={"workspace_key": team_with_business_plan.key})

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        authenticated_web_client.post(url, {})

    created = AccessRequest.objects.get(team=team_with_business_plan, user=guest_user)
    mock_broadcast.assert_called_once()
    assert mock_broadcast.call_args.kwargs["message_type"] == "access_request_updated"
    assert mock_broadcast.call_args.kwargs["data"]["access_request_id"] == str(created.id)
    assert mock_broadcast.call_args.kwargs["data"]["status"] == "pending"
