"""The General tab's security advisory numbering: prefix and starting number."""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.security_advisories.models import SecurityAdvisory
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _post(client: Client, member: Member, **data: str):
    workspace = member.team
    setup_authenticated_client_session(client, workspace, member.user)
    return client.post(
        reverse("workspaces:team_general", args=[workspace.key]), {"action": "update_advisory_ids", **data}
    )


def test_saving_a_prefix_and_start(client: Client, sample_team_with_owner_member: Member) -> None:
    response = _post(client, sample_team_with_owner_member, advisory_id_prefix="acme-psirt", advisory_id_start_at="43")

    assert response.status_code == 200
    assert "refreshAdvisoryIds" in json.loads(response.headers["HX-Trigger"])
    workspace = sample_team_with_owner_member.team
    workspace.refresh_from_db()
    assert workspace.advisory_id_prefix == "ACME-PSIRT"
    assert workspace.advisory_id_start_at == 43


def test_clearing_both_fields_restores_the_defaults(client: Client, sample_team_with_owner_member: Member) -> None:
    workspace = sample_team_with_owner_member.team
    workspace.advisory_id_prefix = "OSPN"
    workspace.advisory_id_start_at = 500
    workspace.save(update_fields=["advisory_id_prefix", "advisory_id_start_at"])

    _post(client, sample_team_with_owner_member, advisory_id_prefix="", advisory_id_start_at="")

    workspace.refresh_from_db()
    assert workspace.advisory_id_prefix == ""
    assert workspace.advisory_id_start_at == 1


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"advisory_id_prefix": "CVE", "advisory_id_start_at": "1"}, "another vulnerability database"),
        ({"advisory_id_prefix": "ACME SA", "advisory_id_start_at": "1"}, "single hyphens"),
        ({"advisory_id_prefix": "ACME", "advisory_id_start_at": "0"}, "greater than or equal to 1"),
    ],
)
def test_invalid_values_are_refused(
    client: Client, sample_team_with_owner_member: Member, data: dict[str, str], message: str
) -> None:
    response = _post(client, sample_team_with_owner_member, **data)

    assert message in json.loads(response.headers["HX-Trigger"])["messages"][0]["message"]
    workspace = sample_team_with_owner_member.team
    workspace.refresh_from_db()
    assert workspace.advisory_id_prefix == ""
    assert workspace.advisory_id_start_at == 1


def test_a_member_cannot_change_numbering(client: Client, sample_team_with_owner_member: Member) -> None:
    sample_team_with_owner_member.role = "member"
    sample_team_with_owner_member.save(update_fields=["role"])

    response = _post(client, sample_team_with_owner_member, advisory_id_prefix="ACME", advisory_id_start_at="5")

    assert response.status_code == 403
    sample_team_with_owner_member.team.refresh_from_db()
    assert sample_team_with_owner_member.team.advisory_id_prefix == ""


def test_published_advisories_keep_their_ids(client: Client, sample_team_with_owner_member: Member) -> None:
    workspace = sample_team_with_owner_member.team
    advisory = SecurityAdvisory.objects.create(
        team=workspace,
        title="Published",
        status=SecurityAdvisory.Status.PUBLISHED,
        published_at=timezone.now(),
        tracking_id="OLD-SA-2026-0001",
    )

    _post(client, sample_team_with_owner_member, advisory_id_prefix="NEW", advisory_id_start_at="1")

    advisory.refresh_from_db()
    assert advisory.tracking_id == "OLD-SA-2026-0001"


def test_the_card_shows_the_next_id_and_refreshes_alone(
    client: Client, sample_team_with_owner_member: Member
) -> None:
    workspace = sample_team_with_owner_member.team
    workspace.advisory_id_prefix = "ACME-SA"
    workspace.advisory_id_start_at = 43
    workspace.save(update_fields=["advisory_id_prefix", "advisory_id_start_at"])
    setup_authenticated_client_session(client, workspace, sample_team_with_owner_member.user)

    html = client.get(
        reverse("workspaces:team_general", args=[workspace.key]), HTTP_HX_REQUEST="true"
    ).content.decode()

    form = html[html.index('id="advisory-ids-form"') :]
    form = form[: form.index("</form>")]
    assert f"ACME-SA-{timezone.now().year}-0043" in form
    # The refresh selects the form alone, so its starting values must be inside it.
    assert 'id="advisory-id-fields"' in form
    assert '"advisory_id_start_at": "43"' in form
