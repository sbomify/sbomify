"""The assessments card refreshes itself instead of reloading the page.

A completed assessment arrives on the queue's schedule. The card used to answer
it with ``location.reload()``, which lands on whatever the reader was doing: a
triage modal with a justification half typed, a filtered suppression list, an
expanded findings panel. None of that is in the URL, so none of it survives.

The card now swaps its own region, which is what this endpoint serves.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in(sample_team_with_owner_member: Member) -> tuple[Client, Component]:
    component = Component.objects.create(
        team=sample_team_with_owner_member.team,
        name="core-image",
        component_type=Component.ComponentType.BOM,
    )
    client = Client()
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)
    return client, component


def _sbom(component: Component) -> SBOM:
    return SBOM.objects.create(
        component=component,
        name="core-image-minimal",
        format="spdx",
        format_version="3.0.0",
        version="1.0",
        sbom_filename="x.json",
    )


def _card_url(sbom: SBOM) -> str:
    return reverse("plugins:assessment_results_card", kwargs={"sbom_id": str(sbom.id)})


def test_the_card_region_is_served_to_htmx(signed_in) -> None:
    client, component = signed_in
    sbom = _sbom(component)

    response = client.get(_card_url(sbom), headers={"hx-request": "true"})

    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="assessment-results"' in html
    # The swapped region has to carry its own trigger, or it refreshes once and
    # then goes deaf.
    assert 'hx-trigger="refresh-assessments from:body"' in html


def test_the_artifact_page_wires_the_card_to_refresh_rather_than_reload(signed_in) -> None:
    client, component = signed_in
    sbom = _sbom(component)

    page = client.get(
        reverse(
            "core:component_item",
            kwargs={"component_id": component.id, "item_type": "sboms", "item_id": str(sbom.id)},
        )
    )

    html = page.content.decode()
    assert _card_url(sbom) in html
    assert "location.reload()" not in html
    assert "refresh-assessments" in html


def test_a_plain_request_lands_on_the_artifact_page(signed_in) -> None:
    """A pasted link should not answer a bare fragment."""
    client, component = signed_in
    sbom = _sbom(component)

    response = client.get(_card_url(sbom))

    assert response.status_code == 302
    assert response["Location"] == reverse(
        "core:component_item",
        kwargs={"component_id": component.id, "item_type": "sboms", "item_id": str(sbom.id)},
    )


def test_an_id_that_is_not_an_artifact_is_a_404(signed_in) -> None:
    client, _ = signed_in

    url = reverse("plugins:assessment_results_card", kwargs={"sbom_id": "nosuchsbom12"})

    assert client.get(url, headers={"hx-request": "true"}).status_code == 404


def test_a_guest_is_redirected_off_the_fragment(sample_team_with_owner_member: Member) -> None:
    """``component:access`` is the path a guest legitimately reaches gated
    content through, so without the guest block a guest turned away from the
    artifact page could still pull its fragments by URL."""
    member = sample_team_with_owner_member
    member.role = "guest"
    member.save(update_fields=["role"])
    component = Component.objects.create(
        team=member.team, name="core-image", component_type=Component.ComponentType.BOM
    )
    sbom = _sbom(component)
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)

    response = client.get(_card_url(sbom), headers={"hx-request": "true"})

    assert response.status_code == 302
    assert response["Location"] == reverse("core:workspace_public", kwargs={"workspace_key": member.team.key})
