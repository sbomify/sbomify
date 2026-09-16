"""The plan limit is only a limit if the count and the insert share a transaction.

Checked outside one, two requests arriving together both read the same count,
both pass, and a workspace on ``max_products=1`` ends up with two.

The work is split in two on purpose. Plan state, suspension and the
scheduled-downgrade path can reach Stripe, so they run before the transaction
opens; a transaction held across a network round trip ties up a connection and
shows as a long-running transaction. Only the part that must be serialized with
the insert, lock the workspace and count, runs inside it.

These tests assert that structure rather than racing two threads: the lock has
no effect on SQLite, so a timing test would pass whether or not the fix is here.
"""

import os

import pytest
from django.db import transaction
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core import apis
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.sboms.tests.fixtures import sample_access_token, sample_product  # noqa: F401
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member


def _atomic_depth() -> int:
    """How many atomic blocks deep we are.

    ``in_atomic_block`` is useless here: pytest-django wraps the whole test in a
    transaction, so it is True everywhere. Savepoint count moves with nesting,
    which is what actually distinguishes inside the endpoint's transaction from
    outside it.
    """
    return len(transaction.get_connection().savepoint_ids)


def _spy_on_the_limit_check(monkeypatch):
    """Record how deep each half of the check ran, then call the real one."""
    seen: dict[str, object] = {}
    real_precheck = apis._check_billing_limits
    real_locked = apis._enforce_limit_under_lock

    def precheck(team_id, resource_type):
        seen["precheck_depth"] = _atomic_depth()
        return real_precheck(team_id, resource_type)

    def locked(team_id, resource_type):
        seen["locked_depth"] = _atomic_depth()
        return real_locked(team_id, resource_type)

    monkeypatch.setattr(apis, "_check_billing_limits", precheck)
    monkeypatch.setattr(apis, "_enforce_limit_under_lock", locked)
    return seen


def _plan_with_room(team):
    """A plan generous enough that both halves of the check run to completion."""
    from sbomify.apps.billing.models import BillingPlan

    BillingPlan.objects.get_or_create(
        key="business",
        defaults={"name": "Business", "description": "b", "max_products": 50, "max_components": 50},
    )
    team.billing_plan = "business"
    team.billing_plan_limits = {"max_products": 50, "max_components": 50}
    team.save(update_fields=["billing_plan", "billing_plan_limits"])


def _as_owner(client, team, user):
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, team, user)


@pytest.mark.django_db
def test_the_product_limit_check_runs_locked_inside_the_create_transaction(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    monkeypatch,
):
    team = sample_team_with_owner_member.team
    _plan_with_room(team)
    seen = _spy_on_the_limit_check(monkeypatch)
    client = Client()
    _as_owner(client, team, sample_team_with_owner_member.user)

    response = client.post(
        reverse("api-1:create_product"),
        data={"name": "racy-product"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 201, response.content[:200]
    assert seen["locked_depth"] > seen["precheck_depth"], (
        "the deciding count must run inside the create transaction and the Stripe-capable pre-check outside it"
    )


@pytest.mark.django_db
def test_the_component_limit_check_runs_locked_inside_the_create_transaction(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    monkeypatch,
):
    team = sample_team_with_owner_member.team
    _plan_with_room(team)
    seen = _spy_on_the_limit_check(monkeypatch)
    client = Client()
    _as_owner(client, team, sample_team_with_owner_member.user)

    response = client.post(
        reverse("api-1:create_component"),
        data={"name": "racy-component"},  # component_type defaults to BOM
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 201, response.content[:200]
    assert seen["locked_depth"] > seen["precheck_depth"], (
        "the deciding count must run inside the create transaction and the Stripe-capable pre-check outside it"
    )


@pytest.mark.django_db
def test_the_limit_itself_still_holds():
    """Moving the check must not stop it refusing."""
    from sbomify.apps.billing.models import BillingPlan
    from sbomify.apps.teams.models import Team

    BillingPlan.objects.create(key="community", name="Community", description="c", max_products=1, max_components=1)
    team = Team.objects.create(name="limited", billing_plan="community")

    assert apis._check_billing_limits(str(team.id), "product")[0] is True
    Product.objects.create(name="P1", team=team)
    assert apis._check_billing_limits(str(team.id), "product")[0] is False

    assert apis._check_billing_limits(str(team.id), "component")[0] is True
    Component.objects.create(name="C1", team=team, component_type="application")
    assert apis._check_billing_limits(str(team.id), "component")[0] is False


@pytest.mark.django_db(transaction=True)
def test_the_locked_recount_answers_the_same_way():
    """The lock changes concurrency, not the verdict."""
    from sbomify.apps.billing.models import BillingPlan
    from sbomify.apps.teams.models import Team

    BillingPlan.objects.create(key="community", name="Community", description="c", max_products=1, max_components=1)
    team = Team.objects.create(name="limited", billing_plan="community")

    with transaction.atomic():
        assert apis._enforce_limit_under_lock(str(team.id), "product")[0] is True

    Product.objects.create(name="P1", team=team)

    with transaction.atomic():
        assert apis._enforce_limit_under_lock(str(team.id), "product")[0] is False
