"""A GitHub quota reset must outlast the normal assessment retry ladder."""

from datetime import timedelta
from typing import Any, cast

import pytest
import requests
from django.utils import timezone
from pytest_mock import MockerFixture

from sbomify.apps.plugins.builtins.verification import GitHubRateLimitedError, SBOMVerificationPlugin
from sbomify.apps.plugins.sdk.base import RetryLaterError
from sbomify.apps.plugins.tasks import RETRY_LATER_DELAYS_MS, run_assessment_task


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700003600"}, 3601),
        ({"Retry-After": "7200"}, 7200),
        ({"Retry-After": "7200", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700003600"}, 7200),
        ({"Retry-After": "60", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700003600"}, 3601),
        ({"Retry-After": "60", "X-RateLimit-Remaining": "4999", "X-RateLimit-Reset": "1700003600"}, 60),
        ({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1699999999"}, 1),
        ({}, 3600),
        ({"Retry-After": "invalid"}, 3600),
        ({"Retry-After": "-1"}, 3600),
        ({"Retry-After": "0"}, 1),
        ({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "invalid"}, 3600),
        ({"Retry-After": "60", "X-RateLimit-Remaining": "0"}, 3600),
    ],
)
def test_github_rate_limit_preserves_wait_headers(
    mocker: MockerFixture, headers: dict[str, str], expected: int
) -> None:
    mocker.patch("sbomify.apps.plugins.builtins.verification.time.time", return_value=1700000000)
    response = requests.Response()
    response.status_code = 429
    response.headers.update(headers)
    session = mocker.patch("sbomify.apps.plugins.builtins.verification.get_http_session").return_value
    session.get.return_value = response

    with pytest.raises(GitHubRateLimitedError) as error:
        SBOMVerificationPlugin()._download_github_bundle("example", "project", "a" * 64)

    assert error.value.retry_after_seconds == expected


@pytest.mark.django_db
@pytest.mark.parametrize("retry_after_seconds", [None, 30, 3601, 7200])
@pytest.mark.parametrize("attempt", [0, 3])
def test_task_uses_the_longer_of_normal_backoff_and_service_wait(
    mocker: MockerFixture, retry_after_seconds: int | None, attempt: int
) -> None:
    orchestrator = mocker.patch("sbomify.apps.plugins.tasks.PluginOrchestrator").return_value
    orchestrator.run_assessment.side_effect = RetryLaterError(
        "Wait for the service",
        assessment_run_id="00000000-0000-0000-0000-000000000001",
        retry_after_seconds=retry_after_seconds,
    )
    send = mocker.patch.object(run_assessment_task, "send_with_options")

    result = cast(
        dict[str, Any],
        run_assessment_task.fn(
            sbom_id="sbom-1", plugin_name="sbom-verification", run_reason="on_upload", _retry_later_count=attempt
        ),
    )

    assert result["status"] == "pending_retry"
    assert send.call_args.kwargs["delay"] == max(RETRY_LATER_DELAYS_MS[attempt], (retry_after_seconds or 0) * 1000)
    assert send.call_args.kwargs["kwargs"]["_existing_run_id"] == "00000000-0000-0000-0000-000000000001"
    assert send.call_args.kwargs["kwargs"]["_retry_later_count"] == attempt + 1
    orchestrator.finalize_retry_exhausted.assert_not_called()


@pytest.mark.django_db
def test_hour_long_rate_limit_gets_an_attempt_after_reset(mocker: MockerFixture) -> None:
    """Replay the original failure without waiting for real time or calling GitHub."""
    now = 1700000000
    reset = now + 3600
    mocker.patch("sbomify.apps.plugins.builtins.verification.time.time", side_effect=lambda: now)
    response = requests.Response()
    response.status_code = 403
    response.headers.update({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)})
    session = mocker.patch("sbomify.apps.plugins.builtins.verification.get_http_session").return_value
    session.get.return_value = response
    orchestrator = mocker.patch("sbomify.apps.plugins.tasks.PluginOrchestrator").return_value
    completed = mocker.Mock(id="00000000-0000-0000-0000-000000000001", status="completed", sbom_id="sbom-1")
    plugin = SBOMVerificationPlugin()

    def assess(**kwargs: Any) -> Any:
        if now <= reset:
            try:
                plugin._download_github_bundle("example", "project", "a" * 64)
            except GitHubRateLimitedError as error:
                error.assessment_run_id = "00000000-0000-0000-0000-000000000001"
                raise
        return completed

    orchestrator.run_assessment.side_effect = assess
    send = mocker.patch.object(run_assessment_task, "send_with_options")
    mocker.patch("sbomify.apps.plugins.tasks.announce_assessment_settled")
    first = cast(
        dict[str, Any],
        run_assessment_task.fn(sbom_id="sbom-1", plugin_name="sbom-verification", run_reason="on_upload"),
    )
    assert first["status"] == "pending_retry"
    now += send.call_args.kwargs["delay"] // 1000
    assert now > reset

    result = cast(dict[str, Any], run_assessment_task.fn(**send.call_args.kwargs["kwargs"]))
    assert result["status"] == "completed"
    assert orchestrator.run_assessment.call_count == 2
    orchestrator.finalize_retry_exhausted.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["pending", "running"])
@pytest.mark.parametrize(("due_in", "expected_settled"), [(3600, 0), (-60, 0), (-7200, 1)])
def test_cleanup_allows_long_waits_but_still_settles_lost_retries(
    sample_team_with_owner_member: Any, status: str, due_in: int, expected_settled: int
) -> None:
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.stranded import sweep_stranded_runs

    from .test_stranded_runs_are_settled import _run

    run = _run(sample_team_with_owner_member.team, status=status, age=timedelta(hours=5))
    AssessmentRun.objects.filter(pk=run.pk).update(retry_at=timezone.now() + timedelta(seconds=due_in))

    assert sweep_stranded_runs() == expected_settled
    run.refresh_from_db()
    assert run.status == ("completed" if expected_settled else status)


@pytest.mark.django_db
def test_task_persists_the_scheduled_retry_for_cleanup(
    mocker: MockerFixture, sample_team_with_owner_member: Any
) -> None:
    from .test_stranded_runs_are_settled import _run

    run = _run(sample_team_with_owner_member.team, status="pending", age=timedelta(hours=5))
    orchestrator = mocker.patch("sbomify.apps.plugins.tasks.PluginOrchestrator").return_value
    orchestrator.run_assessment.side_effect = GitHubRateLimitedError(
        "Quota resets later", assessment_run_id=str(run.id), retry_after_seconds=7200
    )
    mocker.patch.object(run_assessment_task, "send_with_options")
    before = timezone.now()

    run_assessment_task.fn(sbom_id=str(run.sbom_id), plugin_name="sbom-verification", run_reason="on_upload")

    run.refresh_from_db()
    assert run.retry_at is not None
    assert before + timedelta(hours=2) <= run.retry_at <= timezone.now() + timedelta(hours=2)
