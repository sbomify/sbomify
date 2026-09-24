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
    [(1, "1 vulnerability"), (2, "2 vulnerabilities")],
)
def test_the_scan_count_agrees_and_uses_the_whole_word(total, expected):
    """It read "1 vulns", which is two problems in four characters.

    The glossary makes "vulnerability" the user-facing word, so the
    abbreviation was wrong before the agreement was.
    """
    run = {
        "id": "run1",
        "plugin_name": "osv",
        "category": "security",
        "status": "completed",
        "result": {"summary": {"by_severity": {"high": total}, "total_findings": total}},
    }

    rendered = render_to_string("plugins/components/_assessment_run_item.html.j2", {"run": run, "loop_index": 1})

    assert expected in " ".join(rendered.split())
    assert "vulns" not in rendered
