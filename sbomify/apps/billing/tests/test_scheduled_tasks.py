"""The scheduler sends these tasks themselves, on the schedules they have always run on."""

from dramatiq_crontab import scheduler

import sbomify.apps.billing.tasks  # noqa: F401
import sbomify.apps.onboarding.tasks  # noqa: F401
import sbomify.apps.teams.tasks  # noqa: F401


def test_tasks_are_scheduled_under_their_own_names():
    triggers = {job.name: str(job.trigger) for job in scheduler.get_jobs()}

    assert triggers["check_stale_trials_task"] == "cron[month='*', day='*', day_of_week='*', hour='2', minute='0']"
    assert triggers["sync_active_subscriptions_task"] == (
        "cron[month='*', day='*', day_of_week='*', hour='3', minute='30']"
    )
    assert triggers["verify_custom_domains"] == "cron[month='*', day='*', day_of_week='*', hour='*', minute='*/15']"
    assert triggers["process_onboarding_sequence_batch_task"] == (
        "cron[month='*', day='*', day_of_week='*', hour='9', minute='0']"
    )
