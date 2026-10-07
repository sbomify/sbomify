"""Sessions written before the workspace key names move to them on their next request."""

import pytest
from django.test import Client

# Any URL Django answers, a 404 included, passes through the middleware.
PROBE = "/__session-key-probe__/"
OLD_WORKSPACE = {"key": "old-key", "role": "owner", "name": "Old", "is_default_team": True, "id": 1}
OLD_WORKSPACES = {"old-key": {"role": "owner", "name": "Old", "is_default_team": True, "team_id": 1}}


def _client_with(**values) -> Client:
    client = Client()
    session = client.session
    session.update(values)
    session.save()
    return client


@pytest.mark.django_db
def test_old_keys_move_to_the_new_names() -> None:
    client = _client_with(current_team=OLD_WORKSPACE, user_teams=OLD_WORKSPACES)

    client.get(PROBE)

    session = client.session
    assert session["current_workspace"] == OLD_WORKSPACE
    assert session["user_workspaces"] == OLD_WORKSPACES
    assert "current_team" not in session
    assert "user_teams" not in session


@pytest.mark.django_db
def test_a_value_already_under_the_new_name_wins() -> None:
    newer = {**OLD_WORKSPACE, "key": "new-key"}
    client = _client_with(current_team=OLD_WORKSPACE, current_workspace=newer)

    client.get(PROBE)

    session = client.session
    assert session["current_workspace"] == newer
    assert "current_team" not in session


@pytest.mark.django_db
def test_a_session_without_old_keys_is_left_alone() -> None:
    client = _client_with(current_workspace=OLD_WORKSPACE, other="kept")

    client.get(PROBE)

    assert dict(client.session) == {"current_workspace": OLD_WORKSPACE, "other": "kept"}
