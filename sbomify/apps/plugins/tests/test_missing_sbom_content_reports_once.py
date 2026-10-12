"""An SBOM whose stored document is gone is reported once, not once a day.

The row exists, the object behind it does not, and the scheduled sweep retries
a failed run once a day for as long as the row lives. Each attempt logged the
same "Failed to download SBOM ... from S3 (empty data)" at error level, so one
lost object on staging produced a fresh error-tracker event every morning for
weeks with nothing new to say after the first.

The first failure still reports -- it is data loss, and someone should look.
Repeats of the identical failure drop to warning, which stays in the logs but
stays out of the tracker, since events are raised there from error level.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.orchestrator import PluginOrchestrator
from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus
from sbomify.apps.plugins.tests.test_orchestrator import MockPlugin
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.utils import SBOMContentMissingError, SBOMDataError, get_sbom_data, get_sbom_data_bytes
from sbomify.apps.teams.models import Team

# ``sbomify`` is ``propagate: False`` in LOGGING, so ``caplog`` sees nothing;
# the handler goes on the orchestrator's logger directly.
_LOGGER = "sbomify.apps.plugins.orchestrator"


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured():
    handler = _Collector()
    logger = logging.getLogger(_LOGGER)
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)


@pytest.fixture
def sbom(db):
    BillingPlan.objects.get_or_create(
        key="community",
        defaults={"name": "Community", "max_products": 1, "max_components": 5, "max_users": 2},
    )
    team = Team.objects.create(name="Test Team", billing_plan="community")
    component = Component.objects.create(team=team, name="Test Component")
    return SBOM.objects.create(
        name="test-sbom",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="gone.json",
        component=component,
    )


@pytest.fixture
def object_missing(mocker):
    """The bucket has no object under the SBOM's filename."""
    return mocker.patch("sbomify.apps.core.object_store.StorageClient.get_sbom_data", return_value=None)


def _fetch_errors(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.levelno >= logging.ERROR]


def _run(sbom: SBOM) -> AssessmentRun:
    run = PluginOrchestrator().run_assessment(
        sbom_id=sbom.id, plugin=MockPlugin(), run_reason=RunReason.SCHEDULED_REFRESH
    )
    assert run is not None
    return run


@pytest.mark.django_db
@pytest.mark.parametrize("stored", [None, b""])
@pytest.mark.parametrize("fetch", [get_sbom_data, get_sbom_data_bytes])
def test_missing_content_has_its_own_type(sbom, mocker, stored, fetch) -> None:
    """Both fetchers say "missing" by type, and stay catchable as the base class."""
    mocker.patch("sbomify.apps.core.object_store.StorageClient.get_sbom_data", return_value=stored)

    with pytest.raises(SBOMContentMissingError):
        fetch(sbom.id)
    assert issubclass(SBOMContentMissingError, SBOMDataError)


@pytest.mark.django_db
def test_first_failure_reports_and_repeats_do_not(sbom, object_missing, captured) -> None:
    first = _run(sbom)
    assert first.status == RunStatus.FAILED.value
    assert len(_fetch_errors(captured)) == 1

    captured.clear()
    second = _run(sbom)
    third = _run(sbom)

    # Still a failed run each time -- the backoff and the SBOM page read that.
    assert second.status == third.status == RunStatus.FAILED.value
    assert second.error_message == first.error_message
    assert _fetch_errors(captured) == []
    assert any(r.levelno == logging.WARNING and "still missing" in r.getMessage() for r in captured)


@pytest.mark.django_db
def test_a_loss_after_recovery_reports_again(sbom, object_missing, captured, mocker) -> None:
    """Only the run right before counts, so a restore in between resets it."""
    _run(sbom)

    object_missing.return_value = b'{"bomFormat": "CycloneDX", "specVersion": "1.5"}'
    assert _run(sbom).status == RunStatus.COMPLETED.value

    object_missing.return_value = None
    captured.clear()
    _run(sbom)
    assert len(_fetch_errors(captured)) == 1


@pytest.mark.django_db
def test_a_different_earlier_failure_does_not_silence_it(sbom, object_missing, captured) -> None:
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="mock-plugin",
        plugin_version="1.0.0",
        category="compliance",
        run_reason=RunReason.SCHEDULED_REFRESH.value,
        status=RunStatus.FAILED.value,
        error_message="Failed to fetch SBOM data: database error",
    )

    _run(sbom)
    assert len(_fetch_errors(captured)) == 1


def _missing_message(sbom: SBOM) -> str:
    with pytest.raises(SBOMContentMissingError) as raised:
        get_sbom_data_bytes(sbom.id)
    return str(raised.value)


def _settled_run(sbom: SBOM, status: str, created_at, completed_at, error_message: str = "") -> AssessmentRun:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="mock-plugin",
        plugin_version="1.0.0",
        category="compliance",
        run_reason=RunReason.SCHEDULED_REFRESH.value,
        status=status,
        error_message=error_message,
    )
    # created_at is set on insert, so the clock is moved afterwards.
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=created_at, completed_at=completed_at)
    return run


@pytest.mark.django_db
def test_preceding_means_settled_last_not_enqueued_last(sbom, object_missing, captured) -> None:
    """Overlapping runs can finish out of order; the one that settled last counts.

    The missing-content failure was enqueued after the success but settled
    before it, so the object was back when the last verdict was reached and
    a fresh loss has to report.
    """
    now = timezone.now()
    _settled_run(
        sbom,
        RunStatus.FAILED.value,
        created_at=now - timedelta(minutes=50),
        completed_at=now - timedelta(minutes=40),
        error_message=_missing_message(sbom),
    )
    _settled_run(
        sbom,
        RunStatus.COMPLETED.value,
        created_at=now - timedelta(minutes=60),
        completed_at=now - timedelta(minutes=30),
    )

    _run(sbom)
    assert len(_fetch_errors(captured)) == 1


@pytest.mark.django_db(transaction=True)
def test_a_concurrent_worker_waits_for_the_first_report(sbom, object_missing, captured) -> None:
    """Two workers hitting the same loss together still report it once.

    The other worker holds the report lock with its failure written but not
    yet committed, the window in which an unlocked check would read nothing
    and report a second time. This run has to wait for that commit and then
    see the failure.
    """
    message = _missing_message(sbom)
    holding = threading.Event()
    release = threading.Event()
    failures: list[BaseException] = []

    def other_worker() -> None:
        try:
            with transaction.atomic():
                now = timezone.now()
                run = _settled_run(
                    sbom, RunStatus.FAILED.value, created_at=now, completed_at=now, error_message=message
                )
                PluginOrchestrator._lock_missing_content_report(run)
                holding.set()
                release.wait(timeout=10)
        except BaseException as e:  # surfaced to the test thread below
            failures.append(e)
            holding.set()
        finally:
            connection.close()

    worker = threading.Thread(target=other_worker)
    worker.start()
    try:
        assert holding.wait(timeout=10)
        # Let the other worker commit only once this run is blocked on the lock.
        threading.Timer(0.5, release.set).start()
        _run(sbom)
    finally:
        release.set()
        worker.join(timeout=10)

    assert failures == []
    assert _fetch_errors(captured) == []
    assert any(r.levelno == logging.WARNING and "still missing" in r.getMessage() for r in captured)


@pytest.mark.django_db(transaction=True)
def test_a_success_settles_under_the_report_lock(sbom, object_missing) -> None:
    """A success has to wait for a missing-content check in flight.

    Otherwise it can settle between that check's read of the preceding run and
    the failure's own completed_at, and the failure is then ordered after a
    success it never saw, which silences the loss that follows a restore.
    """
    object_missing.return_value = b'{"bomFormat": "CycloneDX", "specVersion": "1.5"}'
    holding = threading.Event()
    release = threading.Event()
    released_at: list = []
    failures: list[BaseException] = []

    def checking_worker() -> None:
        try:
            with transaction.atomic():
                now = timezone.now()
                run = _settled_run(sbom, RunStatus.RUNNING.value, created_at=now, completed_at=None)
                PluginOrchestrator._lock_missing_content_report(run)
                holding.set()
                release.wait(timeout=10)
                released_at.append(timezone.now())
        except BaseException as e:  # surfaced to the test thread below
            failures.append(e)
            holding.set()
        finally:
            connection.close()

    worker = threading.Thread(target=checking_worker)
    worker.start()
    try:
        assert holding.wait(timeout=10)
        threading.Timer(0.5, release.set).start()
        run = _run(sbom)
    finally:
        release.set()
        worker.join(timeout=10)

    assert failures == []
    assert run.status == RunStatus.COMPLETED.value
    assert run.completed_at >= released_at[0]
