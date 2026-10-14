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

    # The template reads the workspace from the context, and only renders the
    # alert for a past_due subscription seen by someone who can act on it.
    team = {
        "key": "abc123",
        "is_in_grace_period": True,
        "billing_plan_limits": {"subscription_status": "past_due"},
    }
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    rendered = render_to_string(
        "core/components/site_notifications.html.j2",
        {"team": team, "can_administer": True, "grace_period_days": days},
        request=request,
    )

    assert expected in " ".join(rendered.split())


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("total", "expected"),
    [(1, "1 vulnerability"), (2, "2 vulnerabilities")],
)
def test_the_scan_count_agrees_and_uses_the_whole_word(total, expected, sample_team_with_owner_member):
    """It read "1 vulns", which is two problems in four characters.

    The glossary makes "vulnerability" the user-facing word, so the
    abbreviation was wrong before the agreement was. The count is the artifact
    page's vulnerability scan summary, beside the scanner that produced it.
    """
    from django.test import Client
    from django.urls import reverse
    from django.utils.html import strip_tags

    from sbomify.apps.core.models import Component
    from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM

    member = sample_team_with_owner_member
    component = Component.objects.create(team=member.team, name="counted", component_type=Component.ComponentType.BOM)
    sbom = SBOM.objects.create(
        component=component, name="counted", format="cyclonedx", format_version="1.6", sbom_filename="c.json"
    )
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        category="security",
        status="completed",
        result={
            "summary": {"by_severity": {"high": total}, "total_findings": total},
            "findings": [
                {"id": f"CVE-2026-{n:04d}", "severity": "high", "component": {"name": f"pkg-{n}", "version": "1"}}
                for n in range(total)
            ],
        },
    )
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)

    response = client.get(
        reverse("core:component_item", kwargs={"component_id": component.id, "item_type": "sboms", "item_id": sbom.id})
    )
    text = " ".join(strip_tags(response.content.decode()).split())

    assert response.status_code == 200
    assert f"Vulnerability scan {expected} · " in text
    assert text.split("Vulnerability scan ", 1)[1].split(" Vulnerabilities", 1)[0].endswith(" · OSV")
    assert "vulns" not in text
