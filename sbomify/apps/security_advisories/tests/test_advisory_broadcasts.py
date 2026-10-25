"""Every advisory write tells the workspace, so an open advisories table repaints.

The broadcast is sent from the service layer, which both the API and the web
views call, and only once the change is committed. Every member hears it,
drafts included, so it names the advisory and the action and nothing else.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import get_api_headers, setup_authenticated_client_session
from sbomify.apps.security_advisories.models import SecurityAdvisory
from sbomify.apps.security_advisories.services import advisories as service

BROADCAST = "sbomify.apps.teams.broadcasts.broadcast_to_workspace"

pytestmark = pytest.mark.django_db


def _sent(mock_broadcast: Any) -> list[tuple[str, dict[str, Any]]]:
    return [(call.kwargs["message_type"], call.kwargs["data"]) for call in mock_broadcast.call_args_list]


@pytest.fixture
def user(sample_team_with_owner_member: Any) -> Any:
    return sample_team_with_owner_member.user


class TestServiceWrites:
    def test_create(self, team: Any, user: Any, django_capture_on_commit_callbacks: Any) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            result = service.create_advisory(team, user, title="Secret title stays out")

        assert result.ok
        mock_broadcast.assert_called_once_with(
            workspace_key=team.key,
            message_type="advisory_updated",
            data={"advisory_id": str(result.value), "action": "created"},
        )

    def test_update(self, team: Any, user: Any, advisory: SecurityAdvisory, django_capture_on_commit_callbacks: Any):
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            assert service.update_advisory(team, user, advisory.id, title="Renamed").ok

        assert _sent(mock_broadcast) == [("advisory_updated", {"advisory_id": advisory.id, "action": "updated"})]

    def test_publish(
        self, team: Any, user: Any, make_publishable: SecurityAdvisory, django_capture_on_commit_callbacks
    ):
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            result = service.publish_advisory(team, user, make_publishable.id, visibility="public")

        assert result.ok, result.error
        assert _sent(mock_broadcast) == [
            ("advisory_updated", {"advisory_id": make_publishable.id, "action": "published"})
        ]

    def test_withdraw(
        self, team: Any, user: Any, make_publishable: SecurityAdvisory, django_capture_on_commit_callbacks
    ):
        assert service.publish_advisory(team, user, make_publishable.id, visibility="public").ok

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            assert service.withdraw_advisory(team, user, make_publishable.id, reason="Not affected").ok

        assert _sent(mock_broadcast) == [
            ("advisory_updated", {"advisory_id": make_publishable.id, "action": "withdrawn"})
        ]

    @pytest.mark.parametrize(("kind", "note"), [("update", "Still looking"), ("investigating", "")])
    def test_post_update(
        self,
        kind: str,
        note: str,
        team: Any,
        user: Any,
        advisory: SecurityAdvisory,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            result = service.post_update(team, user, advisory.id, kind=kind, note=note)

        assert result.ok, result.error
        assert _sent(mock_broadcast) == [("advisory_updated", {"advisory_id": advisory.id, "action": "updated"})]

    def test_delete_by_tracking_id_names_the_real_id(
        self, team: Any, user: Any, make_publishable: SecurityAdvisory, django_capture_on_commit_callbacks: Any
    ) -> None:
        assert service.publish_advisory(team, user, make_publishable.id, visibility="public").ok
        make_publishable.refresh_from_db()

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            assert service.delete_advisory(team, make_publishable.tracking_id).ok

        assert _sent(mock_broadcast) == [
            ("advisory_updated", {"advisory_id": make_publishable.id, "action": "deleted"})
        ]

    def test_bulk_delete_announces_each(
        self, team: Any, advisory: SecurityAdvisory, notice: SecurityAdvisory, django_capture_on_commit_callbacks: Any
    ) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            assert service.delete_advisories(team, [advisory.id, notice.id]).ok

        assert sorted(_sent(mock_broadcast), key=lambda sent: sent[1]["advisory_id"]) == sorted(
            [
                ("advisory_updated", {"advisory_id": advisory.id, "action": "deleted"}),
                ("advisory_updated", {"advisory_id": notice.id, "action": "deleted"}),
            ],
            key=lambda sent: sent[1]["advisory_id"],
        )


class TestRefusedWrites:
    def test_a_rolled_back_create_broadcasts_nothing(
        self, team: Any, user: Any, product: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        from sbomify.apps.core.models import Release

        release = Release.objects.create(product=product, name="1.0")
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            result = service.create_advisory(team, user, title="Bad mapping", products=[], affected_releases=[release])

        assert not result.ok
        mock_broadcast.assert_not_called()

    def test_a_refused_publish_broadcasts_nothing(
        self, team: Any, user: Any, advisory: SecurityAdvisory, django_capture_on_commit_callbacks: Any
    ) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            result = service.publish_advisory(team, user, advisory.id, visibility="private")

        assert not result.ok
        mock_broadcast.assert_not_called()


class TestEntryPoints:
    """Both front doors reach the service, so both announce."""

    def test_the_api_create(
        self, authenticated_api_client: Any, sample_team_with_owner_member: Any, django_capture_on_commit_callbacks
    ) -> None:
        client, token = authenticated_api_client
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                "/api/v1/advisories/",
                data={"title": "From the API"},
                content_type="application/json",
                **get_api_headers(token),
            )

        assert response.status_code == 201, response.content
        assert [message_type for message_type, _ in _sent(mock_broadcast)] == ["advisory_updated"]
        assert _sent(mock_broadcast)[0][1]["action"] == "created"

    def test_the_web_delete(
        self,
        sample_team_with_owner_member: Any,
        advisory: SecurityAdvisory,
        client: Any,
        django_capture_on_commit_callbacks,
    ) -> None:
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            response = client.post(reverse("core:security_advisory_detail", args=[advisory.id]), {"intent": "delete"})

        assert response.status_code == 302
        assert _sent(mock_broadcast) == [("advisory_updated", {"advisory_id": advisory.id, "action": "deleted"})]

    def test_the_table_repaints_on_the_message(self, sample_team_with_owner_member: Any, client: Any) -> None:
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.get(reverse("core:security_advisories_table"), HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        html = response.content.decode()
        assert "'advisory_updated', 'resync'" in html
        assert "refresh-advisories" in html
