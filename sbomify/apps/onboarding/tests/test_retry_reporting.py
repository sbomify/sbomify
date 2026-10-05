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


class TestAgainstTheRealMiddlewareChain:
    """The event shape, taken from dramatiq rather than written down here.

    Everything above builds the event dict by hand, so a change in how
    ``SentryMiddleware`` serializes the message -- a renamed key, a missing
    ``options.retries``, a different nesting -- would make every attempt
    report while those tests stayed green.

    These run a real actor through a real broker with the real middleware,
    against a real Sentry client wired the way ``settings.py`` wires it
    (``DramatiqIntegration`` plus ``before_send=throttle_self_healing_notices``),
    and assert on what reaches the transport. Nothing about the event shape is
    asserted from memory.
    """

    @staticmethod
    def _broker():
        """A StubBroker carrying SentryMiddleware where the integration puts it.

        At index 0, as ``DramatiqIntegration`` does when it patches
        ``Broker.__init__``. The position is what the filter depends on:
        ``emit_after`` walks middleware in reverse, so first means last --
        after Retries has incremented and decided.
        """
        from dramatiq.brokers.stub import StubBroker
        from sentry_sdk.integrations.dramatiq import SentryMiddleware

        broker = StubBroker()
        broker.emit_after("process_boot")
        broker.add_middleware(SentryMiddleware(), before=type(broker.middleware[0]))
        return broker

    @staticmethod
    def _sentry(events: list[Any], with_logging: bool = True):
        """A client wired as production wires it, capturing instead of sending.

        ``LoggingIntegration`` is part of "as production wires it" and not an
        extra: ``settings.py`` passes all three, and leaving it out here hid
        four events per outage, because dramatiq's worker logs every failed
        attempt at error level on top of what the dramatiq integration
        captures.
        """
        import logging as logging_module

        import sentry_sdk
        from sentry_sdk.integrations.dramatiq import DramatiqIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        from sbomify.sentry_config import throttle_self_healing_notices

        def _transport(payload: Any) -> None:
            # A function transport is handed the event dict itself, not an
            # envelope; keep the envelope branch so this does not depend on
            # which one a future sentry-sdk passes.
            if isinstance(payload, dict):
                events.append(payload)
                return
            for item in getattr(payload, "items", []):
                event = item.get_event()
                if event is not None:
                    events.append(event)

        integrations: list[Any] = [DramatiqIntegration()]
        if with_logging:
            integrations.append(LoggingIntegration(level=logging_module.INFO, event_level=logging_module.ERROR))

        return sentry_sdk.Client(
            dsn="https://public@example.invalid/1",
            integrations=integrations,
            default_integrations=False,
            before_send=throttle_self_healing_notices,
            transport=_transport,
        )

    def _run_until_exhausted(
        self, events: list[Any], actor_name: str, max_retries: int, with_logging: bool = True
    ) -> None:
        import dramatiq
        import sentry_sdk

        broker = self._broker()

        @dramatiq.actor(
            broker=broker,
            actor_name=actor_name,
            max_retries=max_retries,
            # The real values are minutes; the arithmetic under test does not
            # depend on them and a test should not wait them out.
            min_backoff=1,
            max_backoff=2,
        )
        def failing() -> None:
            raise RuntimeError("the mail server is not answering")

        # Bind the client on the global scope: the middleware runs on worker
        # threads, and an isolation-scoped client would not reach them.
        scope = sentry_sdk.get_global_scope()
        previous = scope.client
        scope.set_client(self._sentry(events, with_logging))
        try:
            worker = dramatiq.Worker(broker, worker_timeout=50, worker_threads=1)
            worker.start()
            try:
                failing.send()
                broker.join(failing.queue_name, fail_fast=False)
                worker.join()
            finally:
                worker.stop()
            sentry_sdk.flush()
        finally:
            scope.set_client(previous)

    def test_the_middleware_order_is_what_the_filter_assumes(self) -> None:
        from dramatiq.middleware.retries import Retries
        from sentry_sdk.integrations.dramatiq import SentryMiddleware

        order = [type(middleware) for middleware in self._broker().middleware]

        assert order.index(SentryMiddleware) < order.index(Retries), (
            "SentryMiddleware must precede Retries, so that in the reversed "
            "after_process_message order it runs after it"
        )

    def test_only_the_exhausting_attempt_reaches_the_transport(self) -> None:
        """The behaviour this change is for, with nothing stubbed but the wire."""
        from sbomify.sentry_config import REPORT_ON_RETRY_EXHAUSTION_ONLY

        events: list[Any] = []
        self._run_until_exhausted(events, next(iter(REPORT_ON_RETRY_EXHAUSTION_ONLY)), max_retries=3)

        assert len(events) == 1, f"expected one event for four attempts, got {len(events)}"

    def test_the_workers_own_log_line_is_not_a_second_issue(self) -> None:
        """Both integrations, because production wires both.

        dramatiq's worker logs "Failed to process message ... with unhandled
        exception" at error level on every attempt, and ``LoggingIntegration``
        turns each into its own event. Filtering only what
        ``DramatiqIntegration`` captured left four of those behind, so the
        outage still arrived as five issues rather than one.
        """
        from sbomify.sentry_config import REPORT_ON_RETRY_EXHAUSTION_ONLY

        events: list[Any] = []
        self._run_until_exhausted(events, next(iter(REPORT_ON_RETRY_EXHAUSTION_ONLY)), max_retries=3)

        loggers = [event.get("logger") for event in events]
        assert len(events) == 1, f"expected one event for four attempts, got {len(events)}: {loggers}"
        assert loggers == [None], "the surviving event should be the captured exception, not a log line"

    def test_an_unlisted_actor_still_reports_both_copies(self) -> None:
        """The filter is scoped, and the control says so.

        Four attempts, each producing the worker's log line and the captured
        exception. Nothing outside the named senders changes.
        """
        events: list[Any] = []
        self._run_until_exhausted(events, "some_other_actor_task", max_retries=3)

        assert len(events) == 8, f"expected two events per attempt, got {len(events)}"

    def test_an_actor_not_on_the_list_reports_every_attempt(self) -> None:
        """The control: without the filter this is what the senders did too."""
        events: list[Any] = []
        self._run_until_exhausted(events, "some_other_actor_task", max_retries=3, with_logging=False)

        assert len(events) == 4, f"expected one event per attempt, got {len(events)}"

    def test_the_fields_the_filter_depends_on_are_present_in_the_real_event(self) -> None:
        """Named individually, so a renamed or dropped key fails here."""
        events: list[Any] = []
        self._run_until_exhausted(events, "some_other_actor_task", max_retries=1)

        # The captured exception, picked out rather than indexed: the worker
        # also logs each failed attempt, so this actor produces two events per
        # attempt and only one of them is the shape under test.
        event = next(
            e
            for e in events
            if any(
                (v.get("mechanism") or {}).get("type") == "dramatiq"
                for v in (e.get("exception") or {}).get("values") or []
            )
        )
        mechanisms = [(value.get("mechanism") or {}).get("type") for value in event["exception"]["values"]]
        assert "dramatiq" in mechanisms, mechanisms

        message = event["contexts"]["dramatiq"]["data"]
        assert message["actor_name"] == "some_other_actor_task"
        assert "retries" in message["options"], message["options"]
        assert isinstance(message["options"]["retries"], int)
