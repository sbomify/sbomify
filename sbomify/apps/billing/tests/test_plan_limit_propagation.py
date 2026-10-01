"""Saving a BillingPlan copies its limits onto the workspaces on that plan, and only then."""

import threading
import time

import pytest
from django.db import connection, connections, transaction

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db

OLD_LIMITS = {"max_products": 1, "max_components": 5, "max_users": 2}
OTHER_KEYS = {"stripe_customer_id": "cus_123", "stripe_subscription_id": "sub_123", "subscription_status": "active"}


def _workspace(plan_key: str) -> Team:
    return Team.objects.create(
        name=f"On {plan_key}", billing_plan=plan_key, billing_plan_limits={**OLD_LIMITS, **OTHER_KEYS}
    )


def _plan(key: str) -> BillingPlan:
    return BillingPlan.objects.create(key=key, name=key, **OLD_LIMITS)


def test_saving_a_plan_updates_the_limits_of_workspaces_on_it():
    plan = _plan("propagated")
    on_plan = _workspace(plan.key)
    on_other_plan = _workspace("some_other_plan")

    plan.max_products = 10
    plan.max_components = 100
    plan.max_users = None
    plan.save()

    on_plan.refresh_from_db()
    on_other_plan.refresh_from_db()
    assert on_plan.billing_plan_limits == {
        "max_products": 10,
        "max_components": 100,
        "max_users": None,
        **OTHER_KEYS,
    }
    assert on_other_plan.billing_plan_limits == {**OLD_LIMITS, **OTHER_KEYS}


def test_creating_a_plan_leaves_workspaces_alone():
    workspace = _workspace("created")

    BillingPlan.objects.create(key="created", name="created", max_products=10, max_components=100, max_users=None)

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits == {**OLD_LIMITS, **OTHER_KEYS}


def test_a_save_flagged_to_skip_leaves_workspaces_alone():
    plan = _plan("flagged")
    workspace = _workspace(plan.key)

    plan._skip_team_update = True
    plan.max_products = 10
    plan.save()

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits == {**OLD_LIMITS, **OTHER_KEYS}


def test_a_save_of_other_fields_only_leaves_workspaces_alone():
    plan = _plan("price_only")
    workspace = _workspace(plan.key)

    plan.max_products = 10
    plan.promo_message = "Sale"
    plan.save(update_fields=["promo_message"])

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits == {**OLD_LIMITS, **OTHER_KEYS}


def test_a_workspace_with_no_limits_yet_gets_them():
    plan = _plan("no_limits_yet")
    workspace = Team.objects.create(name="No limits", billing_plan=plan.key, billing_plan_limits=None)

    plan.max_products = 10
    plan.save()

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits == {"max_products": 10, "max_components": 5, "max_users": 2}


def _row_location(workspace: Team) -> str:
    """Where Postgres keeps the row: every UPDATE of it, even to the same values, moves it."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT ctid::text FROM {Team._meta.db_table} WHERE id = %s", [workspace.pk])
        return cursor.fetchone()[0]


def test_a_save_that_leaves_the_limits_alone_does_not_rewrite_the_workspaces():
    plan = _plan("unchanged")
    workspace = _workspace(plan.key)
    before = _row_location(workspace)

    plan.description = "A new description"
    plan.save()

    assert _row_location(workspace) == before


def _wait_until_a_backend_waits_on_a_lock(timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    with connection.cursor() as cursor:
        while time.monotonic() < deadline:
            # Postgres keeps one pg_stat_activity snapshot for the whole transaction.
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT 1 FROM pg_stat_activity"
                " WHERE datname = current_database() AND cardinality(pg_blocking_pids(pid)) > 0"
            )
            if cursor.fetchone():
                return
            time.sleep(0.05)
    raise AssertionError("the plan save never waited on the workspace row")


@pytest.mark.django_db(transaction=True)
def test_a_plan_save_keeps_what_a_concurrent_write_changed():
    """A webhook commits to a workspace while the plan save is reaching it.

    The test holds the workspace row in an open transaction, starts the plan save
    on its own connection, waits until that save is blocked on the row, and only
    then commits. A save that had already read the workspace would write its old
    copy of the JSON back over the commit.
    """
    plan = _plan("raced")
    workspace = _workspace(plan.key)
    errors: list[BaseException] = []

    def save_plan() -> None:
        try:
            saved = BillingPlan.objects.get(pk=plan.pk)
            saved.max_products = 10
            saved.save()
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    saver = threading.Thread(target=save_plan)
    with transaction.atomic():
        Team.objects.filter(pk=workspace.pk).update(
            billing_plan_limits={**OLD_LIMITS, **OTHER_KEYS, "subscription_status": "past_due"}
        )
        saver.start()
        _wait_until_a_backend_waits_on_a_lock()
    saver.join(timeout=20)

    assert not saver.is_alive(), "the plan save never finished"
    assert not errors
    workspace.refresh_from_db()
    assert workspace.billing_plan_limits == {
        **OLD_LIMITS,
        "max_products": 10,
        **OTHER_KEYS,
        "subscription_status": "past_due",
    }
