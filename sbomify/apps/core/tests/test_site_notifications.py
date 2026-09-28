"""The dashboard warns whoever can fix a failed payment."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _past_due(team, failed_days_ago: int) -> None:
    team.billing_plan_limits = {
        **(team.billing_plan_limits or {}),
        "subscription_status": "past_due",
        "payment_failed_at": (timezone.now() - timedelta(days=failed_days_ago)).isoformat(),
    }
    team.save()


@pytest.fixture
def dashboard(authenticated_web_client, mocker, settings):
    settings.BILLING = True
    session = authenticated_web_client.session
    session["current_team"]["has_completed_wizard"] = True
    session.save()
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    def get() -> str:
        response = authenticated_web_client.get(reverse("core:dashboard"))
        assert response.status_code == 200
        return response.content.decode()

    return get


@pytest.mark.parametrize(
    ("failed_days_ago", "shown", "hidden"),
    [(0, "Payment failed", "Account suspended"), (30, "Account suspended", "Payment failed")],
)
def test_past_due_workspace_shows_the_banner(dashboard, team_with_business_plan, failed_days_ago, shown, hidden):
    _past_due(team_with_business_plan, failed_days_ago)

    content = dashboard()

    assert shown in content
    assert hidden not in content
    assert reverse("billing:create_portal_session", args=[team_with_business_plan.key]) in content


def test_active_workspace_shows_no_banner(dashboard):
    content = dashboard()

    assert "Payment failed" not in content
    assert "Account suspended" not in content
