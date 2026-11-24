"""Deleting an artifact before its queued assessment runs is a race, not a fault.

Assessments are enqueued when an SBOM is uploaded and run later. Deleting the
artifact in that window is allowed and expected, and the task's only sensible
response is to stop: there is nothing left to assess.

It was reported as an error twice per occurrence — once by the task's handler
and once by ``format_task_error`` — so a user tidying up produced two alerts
naming an id that no longer exists and nothing anyone could do about either.
"""

from __future__ import annotations

import logging

import pytest

from sbomify.apps.plugins.orchestrator import PluginOrchestrator, PluginOrchestratorError, SBOMGoneError

# The two loggers this path writes to. Both sit under ``sbomify``, which the
# project's LOGGING config marks ``propagate: False`` — so records never reach
# the root logger and ``caplog`` alone captures nothing. The handler is attached
# to each one directly instead.
_LOGGERS = ("sbomify.apps.plugins.tasks", "sbomify.task_utils")

MISSING_SBOM_ID = "TESTsbom0001"


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured():
    """Records from the loggers this task path actually uses."""
    handler = _Collector()
    attached = [logging.getLogger(name) for name in _LOGGERS]
    for logger in attached:
        logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        for logger in attached:
            logger.removeHandler(handler)


def _run_with(monkeypatch, error: Exception) -> dict:
    from sbomify.apps.plugins import tasks

    def raise_it(*args, **kwargs):
        raise error

    monkeypatch.setattr(PluginOrchestrator, "run_assessment_by_name", raise_it)
    return tasks.run_assessment_task.fn(
        sbom_id=MISSING_SBOM_ID,
        plugin_name="ntia",
        run_reason="on_upload",
    )


def test_a_missing_sbom_has_its_own_exception_type() -> None:
    """The task can only tell this apart from a real orchestration failure by type.

    Still a ``PluginOrchestratorError``, so callers that catch the base class —
    including the orchestrator's own tests — keep working.
    """
    assert issubclass(SBOMGoneError, PluginOrchestratorError)


@pytest.mark.django_db
def test_the_task_skips_rather_than_failing(monkeypatch, captured) -> None:
    """The outcome that reaches the queue, the logs and the error tracker.

    A skip rather than a failure, and nothing above info — which is what keeps
    it out of the error tracker, since events are raised there from error level.
    """
    result = _run_with(monkeypatch, SBOMGoneError(f"SBOM '{MISSING_SBOM_ID}' not found - it may have been deleted"))

    assert result["status"] == "skipped"
    assert MISSING_SBOM_ID in result["reason"]

    about_this_sbom = [record for record in captured if MISSING_SBOM_ID in record.getMessage()]
    assert about_this_sbom, "the skip must still be recorded somewhere"
    assert all(record.levelno < logging.ERROR for record in about_this_sbom)


@pytest.mark.django_db
def test_a_real_orchestration_failure_is_still_an_error(monkeypatch, captured) -> None:
    """The risk of the fix: a genuine fault must not ride out on the new path.

    Only the missing-artifact race is downgraded. Anything else the orchestrator
    raises is still reported as a failure, at error level.
    """
    result = _run_with(monkeypatch, PluginOrchestratorError("Plugin 'ntia' is not registered"))

    assert result["status"] == "failed"
    assert any(record.levelno >= logging.ERROR for record in captured)
