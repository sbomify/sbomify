"""The page itself: who may see it, and that it renders."""

from __future__ import annotations

import html

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import User
from sbomify.apps.ops.services.cache import KEY_PREFIX


PANEL_KEYS = [f"{KEY_PREFIX}:{name}" for name in ("counts", "revenue", "activation", "signups:30")]


@pytest.fixture(autouse=True)
def clear_panel_cache():
    cache.delete_many(PANEL_KEYS)
    yield
    cache.delete_many(PANEL_KEYS)


@pytest.fixture
def staff_user(db) -> User:
    return User.objects.create_user(
        username="staffer",
        email="staffer@example.com",
        password="x",
        is_staff=True,
    )


@pytest.fixture
def customer(db) -> User:
    return User.objects.create_user(username="customer", email="customer@example.com", password="x")


@pytest.mark.django_db
class TestAccess:
    def test_staff_can_open_the_overview(self, client: Client, staff_user):
        client.force_login(staff_user)

        response = client.get(reverse("ops:overview"))

        assert response.status_code == 200

    def test_a_customer_gets_a_404_not_a_403(self, client: Client, customer):
        """A 403 confirms the surface exists. A customer should learn nothing."""
        client.force_login(customer)

        response = client.get(reverse("ops:overview"))

        assert response.status_code == 404

    def test_an_anonymous_visitor_gets_a_404(self, client: Client):
        response = client.get(reverse("ops:overview"))

        assert response.status_code == 404

    def test_a_deactivated_staff_account_is_refused(self, client: Client, staff_user):
        client.force_login(staff_user)
        staff_user.is_active = False
        staff_user.save(update_fields=["is_active"])

        response = client.get(reverse("ops:overview"))

        assert response.status_code == 404


@pytest.mark.django_db
class TestLegacyUrls:
    def test_the_old_dashboard_url_redirects_here(self, client: Client, staff_user):
        client.force_login(staff_user)

        response = client.get("/admin/dashboard/")

        assert response.status_code == 302
        assert response["Location"] == reverse("ops:overview")

    @pytest.mark.parametrize("section", ["billing", "growth", "funnel", "health"])
    def test_the_old_sub_pages_redirect_here(self, client: Client, staff_user, section):
        client.force_login(staff_user)

        response = client.get(f"/admin/dashboard/{section}/")

        assert response.status_code == 302
        assert response["Location"] == reverse("ops:overview")

    def test_a_customer_gets_a_404_from_the_alias_too(self, client: Client, customer):
        """A 302 where a missing URL gives 404 announces the surface exists,
        which is the whole thing the 404 on /ops/ is there to prevent."""
        client.force_login(customer)

        assert client.get("/admin/dashboard/").status_code == 404

    def test_an_anonymous_visitor_gets_a_404_from_the_alias(self, client: Client):
        assert client.get("/admin/dashboard/").status_code == 404

    @pytest.mark.parametrize("section", ["billing", "growth", "funnel", "health"])
    def test_the_sub_page_aliases_are_gated_too(self, client: Client, customer, section):
        client.force_login(customer)

        assert client.get(f"/admin/dashboard/{section}/").status_code == 404


@pytest.mark.django_db
class TestRendering:
    def test_chart_series_are_json_in_data_attributes(self, client: Client, staff_user):
        """Not values pasted into a script body, which is what broke labels before."""
        client.force_login(staff_user)

        response = client.get(reverse("ops:overview"))
        body = response.content.decode()

        assert 'data-chart="signups"' in body
        assert 'data-chart="plans"' in body

    def test_chart_series_parse_as_json(self, client: Client, staff_user):
        """The old charts were hand-built JS, where an escaped apostrophe in a
        workspace name rendered as a visible ``&#x27;``. Series that must parse
        as JSON cannot be built that way."""
        import json
        import re

        from sbomify.apps.teams.models import Team

        Team.objects.create(name="Bob's Team", billing_plan="community")
        client.force_login(staff_user)

        body = client.get(reverse("ops:overview")).content.decode()
        series = re.findall(r'data-(?:labels|values)="([^"]*)"', body)

        assert series
        for raw in series:
            assert isinstance(json.loads(html.unescape(raw)), list)
