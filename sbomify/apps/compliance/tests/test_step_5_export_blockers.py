"""Step 5 must say why it will not export.

Found on staging: an assessment showing every step complete and 21/21 controls
satisfied, with the export button disabled and the caption "Complete all steps
and answer all controls to enable export." Both halves of that sentence were
already done. The real reason — the EU-establishment determination was never
recorded — was in the payload and rendered nowhere.

Driven through the real URL rather than ``render_to_string``: the reason has to
survive the summary, the step context and the template, and rendering the
template alone would prove only the last of those.
"""

from __future__ import annotations

import re

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

pytestmark = pytest.mark.django_db


@pytest.fixture
def blocked_assessment(sample_team_with_owner_member, sample_user):
    """A fresh assessment on a CRA-eligible plan.

    Nothing is completed on it — the point is only that the determination is
    unanswered, which is what puts a reason in the summary for Step 5 to show.
    Completing the other steps would make the page prettier and prove nothing
    more.
    """
    from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
    from sbomify.apps.core.models import Product
    from sbomify.apps.teams.models import ContactEntity, ContactProfile

    team = sample_team_with_owner_member.team
    # The wizard is gated on a CRA-eligible plan; without one the page is a 403
    # and the test would be measuring the billing gate.
    from sbomify.apps.billing.models import BillingPlan

    team.billing_plan = sorted(BillingPlan.CRA_ELIGIBLE_PLAN_KEYS)[0]
    team.save(update_fields=["billing_plan"])

    profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
    ContactEntity.objects.create(
        profile=profile, name="Acme Labs GmbH", email="legal@acme.example", is_manufacturer=True
    )
    product = Product.objects.create(name="Blocker Product", team=team)
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


@pytest.fixture
def step_5_html(blocked_assessment, sample_team_with_owner_member) -> str:
    member = sample_team_with_owner_member
    client = Client()
    client.force_login(member.user)
    setup_authenticated_client_session(client, member.team, member.user)
    response = client.get(
        reverse("compliance:cra_step", kwargs={"assessment_id": blocked_assessment.id, "step": 5})
    )
    assert response.status_code == 200
    return response.content.decode()


def _guards(html: str) -> list[str]:
    return re.findall(r'x-if="([^"]+)"', html)


def test_the_generic_caption_no_longer_fires_on_its_own(step_5_html: str) -> None:
    """It used to render whenever the assessment was not ready, which is how it
    came to be shown beside a step list with nothing left to do."""
    unconditional = [g for g in _guards(step_5_html) if g.strip() == "!overallReady"]

    assert not unconditional, f"still shown for every blocked assessment: {unconditional}"


def test_a_named_reason_is_preferred_when_there_is_one(step_5_html: str) -> None:
    assert "!overallReady && blockers.length" in _guards(step_5_html)


def test_the_generic_caption_survives_for_the_case_it_was_written_for(step_5_html: str) -> None:
    """Steps genuinely outstanding still get the original wording — there is no
    named reason to show, and silence would be worse."""
    assert "!overallReady && !blockers.length" in _guards(step_5_html)


def test_the_reason_list_is_rendered(step_5_html: str) -> None:
    assert 'x-for="reason in blockers"' in step_5_html
    assert 'data-testid="export-blockers"' in step_5_html


def test_the_page_is_handed_a_reason_to_show(step_5_html: str) -> None:
    """The template only helps if the payload carries one, so pin the whole
    chain rather than the template on its own."""
    assert "eu_representation_problems" in step_5_html
    assert "Record whether the manufacturer is established in the EU" in step_5_html
