"""The team:* to workspace:* dual-emit, at the layer where every path meets.

The twin used to be emitted in ``capture_for_request``, one layer up from the
client, and team:role_changed fires from a signal inside
``transaction.on_commit`` with no request in hand, so its twin never existed:
the migrated dashboard would have recorded zero role changes forever,
indistinguishable from real data. The twin now rides in ``capture`` itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sbomify.apps.core import posthog_service


def _events(client: MagicMock) -> list[str]:
    return [call.args[1] for call in client.capture.call_args_list]


@patch.object(posthog_service, "_get_client")
def test_a_raw_capture_of_a_team_event_emits_the_workspace_twin(mock_get_client):
    """The role_changed path: capture() called directly, no request, no view."""
    client = MagicMock()
    mock_get_client.return_value = client

    posthog_service.capture("wk_123", "team:role_changed", {"old_role": "member", "new_role": "admin"})

    assert _events(client) == ["team:role_changed", "workspace:role_changed"]
    old, new = client.capture.call_args_list
    assert old.kwargs["properties"] == new.kwargs["properties"]


@patch.object(posthog_service, "_get_client")
def test_a_workspace_native_event_does_not_twin(mock_get_client):
    client = MagicMock()
    mock_get_client.return_value = client

    posthog_service.capture("wk_123", "workspace:role_changed", {})

    assert _events(client) == ["workspace:role_changed"]


@patch.object(posthog_service, "_get_client")
def test_the_twin_skips_registry_validation(mock_get_client):
    """workspace:* names are not registered, deliberately.

    The twin is the same payload under the migrating name; validating it
    would log a drift warning on every emission for the whole window, which
    is noise wearing a warning's clothes. The original still validates.
    """
    client = MagicMock()
    mock_get_client.return_value = client

    with patch.object(posthog_service, "logger") as log:
        posthog_service.capture("wk_123", "team:member_invited", {"invited_role": "member"})

    warnings = " ".join(str(c) for c in log.warning.call_args_list)
    assert "workspace:member_invited" not in warnings
    assert _events(client) == ["team:member_invited", "workspace:member_invited"]
