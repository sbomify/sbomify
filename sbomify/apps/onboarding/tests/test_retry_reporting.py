"""A transient send that a retry fixes should raise one Sentry issue, not four.

The onboarding senders retry an SMTP 4xx or a database that went away, and the
retry is expected to work. Lowering the task's own log line to warning removes
the ``LoggingIntegration`` event for those attempts but not
``DramatiqIntegration``'s: that one captures the exception every time the actor
raises, and raising is how the Retries middleware is told to try again. So the
attempts were still four issues for one delivery that then succeeded.

``REPORT_ON_RETRY_EXHAUSTION_ONLY`` names the actors whose intermediate
attempts are dropped in ``before_send``. These pin the arithmetic that decides
"dramatiq will try again" against the arithmetic the Retries middleware
actually uses, because the two have to agree or the exhausting attempt is
dropped too -- and that is the one worth reading.
"""

from __future__ import annotations

from typing import Any

import pytest

from sbomify.sentry_config import (
    REPORT_ON_RETRY_EXHAUSTION_ONLY,
    _dramatiq_will_retry,
    throttle_self_healing_notices,
)

ACTOR = "send_welcome_email_task"
MAX_RETRIES = 3


def _event(actor_name: str = ACTOR, retries: int | None = None, mechanism: str = "dramatiq") -> dict[str, Any]:
    """The shape DramatiqIntegration captures.

    ``contexts.dramatiq.data`` is ``message.asdict()``, so ``options`` carries
    whatever the middleware chain has written by then. ``retries`` is absent on
    the very first enqueue, which is why None is a case.
    """
    options: dict[str, Any] = {}
    if retries is not None:
        options["retries"] = retries
    return {
        "exception": {"values": [{"type": "SMTPException", "mechanism": {"type": mechanism, "handled": False}}]},
        "contexts": {"dramatiq": {"type": "dramatiq", "data": {"actor_name": actor_name, "options": options}}},
    }


@pytest.fixture
def _max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the actor lookup, so these test the decision and not the broker."""
    monkeypatch.setattr("sbomify.sentry_config._actor_max_retries", lambda name: MAX_RETRIES)


class TestOnlyTheExhaustingAttemptIsReported:
    """Retries increments ``options["retries"]`` and *then* decides.

    It gives up when the pre-increment count has reached ``max_retries``, and
    its ``after_process_message`` runs before the Sentry integration's --
    ``emit_after`` walks middleware in reverse and the integration inserts
    itself at index 0. So the count on the event is one higher than the number
    Retries compared against, and "it gave up" is ``retries > max_retries``.
    """

    # max_retries=3 means four attempts. The count the event carries after
    # each, and whether another attempt follows.
    @pytest.mark.parametrize("retries", [1, 2, 3])
    def test_an_attempt_with_another_to_come_is_dropped(self, retries: int, _max_retries: None) -> None:
        assert throttle_self_healing_notices(_event(retries=retries), {}) is None

    def test_the_attempt_that_exhausts_the_budget_is_reported(self, _max_retries: None) -> None:
        event = _event(retries=MAX_RETRIES + 1)

        assert throttle_self_healing_notices(event, {}) is event

    def test_a_count_beyond_the_budget_is_still_reported(self, _max_retries: None) -> None:
        """Belt and braces: a message carrying a higher count must not vanish."""
        assert throttle_self_healing_notices(_event(retries=99), {}) is not None


class TestNothingElseIsSwallowed:
    """The filter has to be narrow, or it hides real failures."""

    def test_an_actor_not_on_the_list_always_reports(self, _max_retries: None) -> None:
        event = _event(actor_name="process_sbom_task", retries=1)

        assert throttle_self_healing_notices(event, {}) is event

    def test_every_listed_actor_is_covered(self, _max_retries: None) -> None:
        for actor_name in REPORT_ON_RETRY_EXHAUSTION_ONLY:
            assert throttle_self_healing_notices(_event(actor_name=actor_name, retries=1), {}) is None

    def test_a_non_dramatiq_event_is_untouched(self, _max_retries: None) -> None:
        """A Django request error on the same actor name is not a retry."""
        event = _event(retries=1, mechanism="django")

        assert throttle_self_healing_notices(event, {}) is event

    def test_an_event_without_a_dramatiq_context_is_untouched(self, _max_retries: None) -> None:
        event: dict[str, Any] = {
            "exception": {"values": [{"mechanism": {"type": "dramatiq"}}]},
        }

        assert throttle_self_healing_notices(event, {}) is event

    def test_an_unreadable_retry_count_reports(self, _max_retries: None) -> None:
        event = _event(retries=None)
        event["contexts"]["dramatiq"]["data"]["options"] = {"retries": "lots"}

        assert throttle_self_healing_notices(event, {}) is event

    def test_an_unknown_max_retries_reports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No broker in this process, or an actor it never declared."""
        monkeypatch.setattr("sbomify.sentry_config._actor_max_retries", lambda name: None)

        assert throttle_self_healing_notices(_event(retries=1), {}) is not None

    def test_an_empty_event_does_not_raise(self) -> None:
        assert _dramatiq_will_retry({}) is False
        assert _dramatiq_will_retry(None) is False


class TestTheBudgetComesFromTheActor:
    """``_actor_max_retries`` has to read the same option the actor declares."""

    def test_it_reads_the_declared_max_retries(self) -> None:
        from sbomify.sentry_config import _actor_max_retries

        # The onboarding senders all declare max_retries=3.
        import sbomify.apps.onboarding.tasks  # noqa: F401

        assert _actor_max_retries(ACTOR) == MAX_RETRIES

    def test_an_unknown_actor_is_none(self) -> None:
        from sbomify.sentry_config import _actor_max_retries

        assert _actor_max_retries("no_such_actor_anywhere") is None
