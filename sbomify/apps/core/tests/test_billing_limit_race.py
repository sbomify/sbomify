"""The plan limit is only a limit if the count and the insert share a transaction.

Checked outside one, two requests arriving together both read the same count,
both pass, and a workspace on ``max_products=1`` ends up with two. The fix moves
the check inside the create transaction and locks the workspace row, so the
second request waits and then counts the first one's committed row.

These tests assert the structure rather than trying to race two threads: the
lock has no effect on SQLite, so a timing test would pass locally whether or not
the fix is present.
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


def _spy_on_the_limit_check(monkeypatch):
    """Record how the endpoint called the limit check, then call the real one."""
    seen: dict[str, object] = {}
    real = apis._check_billing_limits

    def spy(team_id, resource_type, *, lock=False):
        seen["in_atomic_block"] = transaction.get_connection().in_atomic_block
        seen["lock"] = lock
        return real(team_id, resource_type, lock=lock)

    monkeypatch.setattr(apis, "_check_billing_limits", spy)
    return seen


def _as_owner(client, team, user):
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, team, user)


@pytest.mark.django_db
def test_the_product_limit_check_runs_locked_inside_the_create_transaction(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    monkeypatch,
):
    seen = _spy_on_the_limit_check(monkeypatch)
    team = sample_team_with_owner_member.team
    client = Client()
    _as_owner(client, team, sample_team_with_owner_member.user)

    response = client.post(
        reverse("api-1:create_product"),
        data={"name": "racy-product"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code in (201, 403)
    assert seen.get("in_atomic_block") is True, "the check ran outside the create transaction"
    assert seen.get("lock") is True, "the check did not lock the workspace row"


@pytest.mark.django_db
def test_the_component_limit_check_runs_locked_inside_the_create_transaction(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    monkeypatch,
):
    seen = _spy_on_the_limit_check(monkeypatch)
    team = sample_team_with_owner_member.team
    client = Client()
    _as_owner(client, team, sample_team_with_owner_member.user)

    response = client.post(
        reverse("api-1:create_component"),
        data={"name": "racy-component"},  # component_type defaults to BOM
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code in (201, 403, 400)
    assert seen.get("in_atomic_block") is True, "the check ran outside the create transaction"
    assert seen.get("lock") is True, "the check did not lock the workspace row"


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
def test_locking_still_answers_the_same_way():
    """The lock changes concurrency, not the verdict."""
    from sbomify.apps.billing.models import BillingPlan
    from sbomify.apps.teams.models import Team

    BillingPlan.objects.create(key="community", name="Community", description="c", max_products=1, max_components=1)
    team = Team.objects.create(name="limited", billing_plan="community")

    with transaction.atomic():
        assert apis._check_billing_limits(str(team.id), "product", lock=True)[0] is True

    Product.objects.create(name="P1", team=team)

    with transaction.atomic():
        assert apis._check_billing_limits(str(team.id), "product", lock=True)[0] is False
