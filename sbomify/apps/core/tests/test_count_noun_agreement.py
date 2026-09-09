"""Counts and the nouns beside them have to agree.

The Trust Center summary strip read "1 Products" to the first person who saw
it, which is what started this. These two are the same defect on internal
pages: a grace period can be configured to one day, and a scan can find one
vulnerability, and both then read as plurals.

Rendered rather than grepped, because the point is what a reader sees.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("days", "expected"),
    [(1, "within 1 day to avoid"), (3, "within 3 days to avoid")],
)
def test_the_grace_period_agrees_with_its_count(days, expected):
    """PAYMENT_GRACE_PERIOD_DAYS is configurable, so one day is reachable."""

    # The template reads the workspace out of the session, and only renders
    # the alert for a past_due subscription seen by someone who can act on it.
    team = {
        "key": "abc123",
        "is_in_grace_period": True,
        "billing_plan_limits": {"subscription_status": "past_due"},
    }
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    request.session = {"current_team": team}

    rendered = render_to_string(
        "core/components/site_notifications.html.j2",
        {"can_administer": True, "grace_period_days": days},
        request=request,
    )

    assert expected in " ".join(rendered.split())


@pytest.mark.parametrize(
    ("total", "expected"),
    [(1, "1 vulnerability:"), (2, "2 vulnerabilities:")],
)
def test_the_scan_count_agrees_and_uses_the_whole_word(total, expected):
    """It read "1 vulns", which is two problems in four characters.

    The glossary makes "vulnerability" the user-facing word, so the
    abbreviation was wrong before the agreement was.
    """
    activity = {
        "type": "scan",
        "scan_details": {"total": total, "critical": 0, "high": 0, "medium": 0, "low": 0},
        "title": "scan",
        "timestamp": None,
    }

    rendered = render_to_string("core/components/recent_activity.html.j2", {"activities": [activity]})

    assert expected in " ".join(rendered.split())
    assert "vulns" not in rendered
