"""Shared helpers for PostHog Tier 2 event-capture tests.

Centralises the mock setup and assertion helpers so the per-domain
test files (``test_posthog_tier2_teams.py``, ``_billing.py``,
``_documents.py``, ``_service.py``) stay focused on the flow under
test rather than re-deriving how to intercept PostHog captures.

Patch target rationale: most capture sites use the
``capture_for_request`` helper, which in turn calls the module-level
``capture``. Patching ``capture`` therefore intercepts both
helper-based and direct call sites without needing per-site patching.
"""

from __future__ import annotations

from typing import Any

from pytest_mock import MockerFixture


def patch_capture(mocker: MockerFixture) -> Any:
    """Mock ``posthog_service.capture`` and force ``is_enabled`` to True.

    Returns the capture mock so the test can inspect ``call_args_list``.
    """
    mocker.patch("sbomify.apps.core.posthog_service.is_enabled", return_value=True)
    return mocker.patch("sbomify.apps.core.posthog_service.capture")


def called_events(mock_capture: Any) -> list[str]:
    """Return the list of event names passed to ``mock_capture``."""
    return [call.args[1] for call in mock_capture.call_args_list]


def find_call(mock_capture: Any, event: str) -> Any:
    """Return the first ``mock_capture`` call for ``event``.

    Raises ``StopIteration`` if no such call exists — callers should
    assert presence via ``called_events`` first if they want a friendly
    failure message.
    """
    return next(c for c in mock_capture.call_args_list if c.args[1] == event)


def assert_workspace_attribution(mock_capture: Any, event: str, workspace_key: str) -> None:
    """Assert that ``event`` was captured with workspace-scoped attribution.

    Tier 2 convention (from PR #822 / C1 fix): the ``distinct_id`` for a
    workspace-scoped event must equal the workspace key, and the
    ``groups`` kwarg must carry ``{"workspace": workspace_key}`` so the
    event lands on the workspace group in PostHog. This helper enforces
    both invariants in one call.
    """
    call = find_call(mock_capture, event)
    distinct_id = call.args[0]
    groups = call.kwargs.get("groups") or {}
    assert distinct_id == workspace_key, (
        f"Expected distinct_id={workspace_key!r} for {event}, got {distinct_id!r}. "
        "Workspace-scoped events must use the team key as distinct_id "
        "(see PR #822 / posthog_service.capture_for_request)."
    )
    assert groups.get("workspace") == workspace_key, (
        f"Expected groups={{'workspace': {workspace_key!r}}} for {event}, "
        f"got {groups!r}. The PostHog workspace group must be set so the "
        "event aggregates correctly under the workspace group type."
    )
