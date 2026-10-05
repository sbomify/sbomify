"""How often rendering workspace settings reaches Stripe.

Eight sections render from one view and one of them shows billing, so a page
load was depending on a third party that had nothing to say to it. Twice per
load, in fact: the view synced, and the pricing service it then called synced
again. `sync_subscription_from_stripe` bypasses its own cache whenever the
stored copy is over a minute old, so nearly every load made live calls.

Counted rather than timed, because the number of calls is the property that
matters and a timing test would be flaky.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.settings_tabs import SETTINGS_TABS


#: Every section an owner can open apart from billing. Derived from the
#: registry rather than listed, so a tab added later is covered without anyone
#: remembering to add it here.
NON_BILLING_TABS = [tab.key for tab in SETTINGS_TABS if tab.key != "billing" and "owner" in tab.roles]


@pytest.fixture
def paid_workspace(db, django_user_model):
    """A workspace with a subscription, so a sync has something to fetch.

    The BillingPlan row matters more than it looks. Without it
    get_plan_pricing returns at its first branch, before the block that syncs,
    so a test asserting the service does not sync would pass without ever
    reaching the code it names.
    """
    BillingPlan.objects.get_or_create(
        key="business",
        defaults={"name": "Business", "description": "test", "max_products": 10, "max_components": 100},
    )
    user = django_user_model.objects.create_user(
        username="settings-owner", email="settings@test.com", password="password"
    )
    team = Team.objects.create(
        name="Settings Workspace",
        billing_plan="business",
        billing_plan_limits={
            "stripe_customer_id": "cus_test123",
            "stripe_subscription_id": "sub_test123",
            "subscription_status": "active",
            "max_products": 10,
            "max_components": 100,
            # Seeded so get_plan_pricing needs no invoice fetch: it reaches
            # Stripe when either of these is missing, and a test that wants to
            # run the real method needs it to have nothing to fetch.
            "last_payment_amount": 1500,
            "last_payment_currency": "usd",
            "next_billing_date": "2026-10-01T00:00:00Z",
            "billing_period": "monthly",
        },
    )
    Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
    return team, user


def _visit(client, team, user, tab, mocker, settings, *, stub_pricing=True):
    """Render one tab and report how many times each sync path was taken.

    Pricing is stubbed by default, because suppressing the subscription sync
    does not make get_plan_pricing Stripe-free: it still fetches an invoice
    amount when the cached fields are missing.

    ``stub_pricing=False`` runs the real method instead, which is what makes an
    assertion about the service's own sync mean anything. The fixture seeds the
    cached invoice fields so that is safe: with them present there is nothing
    for it to fetch.
    """
    settings.BILLING = True
    synced = mocker.patch("sbomify.apps.teams.views.team_settings.sync_subscription_from_stripe")
    service_synced = mocker.patch("sbomify.apps.billing.stripe_sync.sync_subscription_from_stripe")
    if stub_pricing:
        mocker.patch(
            "sbomify.apps.billing.team_pricing_service.TeamPricingService.get_plan_pricing",
            return_value={"amount": "$0", "period": "forever", "billing_period": None},
        )
    else:
        # Running the real method reaches Stripe once more, for the product
        # catalogue, which is a different call from the one under test. Held
        # to the database copy so the test exercises the sync path without
        # depending on a network it is not measuring.
        mocker.patch(
            "sbomify.apps.billing.stripe_pricing_service.StripePricingService._refresh_pricing_from_stripe",
            side_effect=lambda db_plans: {},
        )
    setup_authenticated_client_session(client, team, user)
    response = client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": tab}))
    return response, synced, service_synced


@pytest.mark.django_db
@pytest.mark.parametrize("tab", NON_BILLING_TABS)
def test_a_tab_that_shows_no_billing_does_not_reach_stripe(client, paid_workspace, mocker, settings, tab):
    team, user = paid_workspace

    response, synced, service_synced = _visit(client, team, user, tab, mocker, settings)

    assert response.status_code == 200
    synced.assert_not_called()
    service_synced.assert_not_called()


@pytest.mark.django_db
def test_the_billing_tab_syncs_exactly_once(client, paid_workspace, mocker, settings):
    """Once, not twice: the view synced and the pricing service synced again.

    Runs the real get_plan_pricing rather than a stub. Stubbing it would make
    the second assertion vacuous, since a method that never runs cannot sync.
    Safe because the fixture seeds the cached invoice fields, so the real path
    has nothing to fetch.
    """
    team, user = paid_workspace

    response, synced, service_synced = _visit(client, team, user, "billing", mocker, settings, stub_pricing=False)

    assert response.status_code == 200
    assert synced.call_count == 1
    service_synced.assert_not_called()


@pytest.mark.django_db
def test_billing_disabled_reaches_stripe_from_no_tab(client, paid_workspace, mocker, settings):
    team, user = paid_workspace
    settings.BILLING = False
    synced = mocker.patch("sbomify.apps.teams.views.team_settings.sync_subscription_from_stripe")
    setup_authenticated_client_session(client, team, user)

    client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "general"}))

    synced.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("tab", NON_BILLING_TABS)
def test_a_tab_that_shows_no_billing_builds_no_pricing(client, paid_workspace, mocker, settings, tab):
    """The sync flag is not enough on its own.

    get_plan_pricing reaches Stripe by two further paths that no sync flag
    covers: listing a customer's subscriptions when none is stored, and
    fetching an invoice amount when the cached fields are missing. Not calling
    it is the only way a tab with no billing on it can be sure of not
    depending on Stripe.
    """
    team, user = paid_workspace
    settings.BILLING = True
    priced = mocker.patch("sbomify.apps.billing.team_pricing_service.TeamPricingService.get_plan_pricing")
    setup_authenticated_client_session(client, team, user)

    response = client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": tab}))

    assert response.status_code == 200
    priced.assert_not_called()


@pytest.mark.django_db
def test_the_billing_tab_still_builds_its_pricing(client, paid_workspace, mocker, settings):
    team, user = paid_workspace
    settings.BILLING = True
    priced = mocker.patch(
        "sbomify.apps.billing.team_pricing_service.TeamPricingService.get_plan_pricing",
        return_value={"amount": "$0", "period": "forever", "billing_period": None},
    )
    setup_authenticated_client_session(client, team, user)

    response = client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "billing"}))

    assert response.status_code == 200
    priced.assert_called_once()


@pytest.mark.django_db
def test_the_billing_tab_prices_what_the_sync_just_fetched(client, paid_workspace, mocker, settings):
    """Pricing must read the refreshed row, not the schema built before the sync.

    get_team() builds its schema at the top of the request, before the sync
    runs, so its billing_plan_limits hold the pre-sync status and dates. The
    pricing service used to hide this by syncing and refreshing again itself.
    Now that it is told not to, pricing the schema would show a subscription
    status the sync had already replaced.
    """
    team, user = paid_workspace
    settings.BILLING = True

    def _sync(team_obj, *args, **kwargs):
        # What a real sync does: write the fresh state to the row.
        team_obj.billing_plan_limits = {
            **(team_obj.billing_plan_limits or {}),
            "subscription_status": "past_due",
            "billing_period": "annual",
        }
        team_obj.save()
        return True

    mocker.patch("sbomify.apps.teams.views.team_settings.sync_subscription_from_stripe", side_effect=_sync)
    priced = mocker.patch(
        "sbomify.apps.billing.team_pricing_service.TeamPricingService.get_plan_pricing",
        return_value={"amount": "$0", "period": "forever", "billing_period": None},
    )
    setup_authenticated_client_session(client, team, user)

    client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "billing"}))

    priced_team = priced.call_args.args[0]
    assert priced_team.billing_plan_limits["subscription_status"] == "past_due", "pricing was handed the pre-sync copy"


@pytest.mark.django_db
def test_the_billing_page_shows_the_status_the_sync_just_wrote(client, paid_workspace, mocker, settings):
    """Pricing and status must not disagree on one page.

    The template reads subscription_status off the context, which is built
    from the schema get_team() made before the sync ran. Pricing reads the
    refreshed row. Fixing only pricing left the page able to show fresh
    figures beside a status the sync had already replaced, which is worse than
    showing stale ones consistently.
    """
    team, user = paid_workspace
    settings.BILLING = True

    def _sync(team_obj, *args, **kwargs):
        team_obj.billing_plan_limits = {
            **(team_obj.billing_plan_limits or {}),
            "subscription_status": "past_due",
        }
        team_obj.save()
        return True

    mocker.patch("sbomify.apps.teams.views.team_settings.sync_subscription_from_stripe", side_effect=_sync)
    mocker.patch(
        "sbomify.apps.billing.team_pricing_service.TeamPricingService.get_plan_pricing",
        return_value={"amount": "$0", "period": "forever", "billing_period": None},
    )
    setup_authenticated_client_session(client, team, user)

    response = client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "billing"}))

    shown = response.context["team"]
    limits = shown["billing_plan_limits"] if isinstance(shown, dict) else shown.billing_plan_limits
    assert limits["subscription_status"] == "past_due", "the page showed the pre-sync status"
