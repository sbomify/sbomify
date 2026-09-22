"""Tests for the pagination contract on `/api/v1/*` list endpoints.

Pins issue #949: `?page=N` for `N > total_pages` must return an empty `items`
list with `has_next=False`, NOT silently fall back to page 1. The old
behaviour caused a naive page-walking client (`while True: GET ?page=N`) to
loop indefinitely, accumulating duplicate copies of the first page until it
hit the wall-clock or recursion limits — see `sbomify-action` PR #228 for
the downstream-defensive workaround.
"""

from __future__ import annotations

import os

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.apis import _paginate_queryset
from sbomify.apps.core.models import Product
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_product,
)
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

# -- Unit tests on the paginator helper directly -----------------------------


class TestPaginateQuerysetUnit:
    """The unit-level contract: page > total_pages → empty list, not a fallback."""

    @pytest.mark.django_db
    def test_page_within_range_returns_items(self, sample_team_with_owner_member):  # noqa: F811
        team = sample_team_with_owner_member.team
        Product.objects.create(team=team, name="A")
        Product.objects.create(team=team, name="B")

        items, meta = _paginate_queryset(Product.objects.filter(team=team), page=1, page_size=10)

        assert len(items) == 2
        assert meta.total == 2
        assert meta.page == 1
        assert meta.total_pages == 1
        assert meta.has_next is False
        assert meta.has_previous is False

    @pytest.mark.django_db
    def test_out_of_range_page_returns_empty_not_fallback(self, sample_team_with_owner_member):  # noqa: F811
        """The bug: a workspace with 1 product used to return that product
        for every ``page=N`` because the paginator caught EmptyPage and
        silently re-served page 1. Now it must return an empty list."""
        team = sample_team_with_owner_member.team
        Product.objects.create(team=team, name="Only Product")

        items, meta = _paginate_queryset(Product.objects.filter(team=team), page=2, page_size=10)

        assert items == [], (
            "Out-of-range pages must return an empty list. The previous "
            "implementation fell back to page 1, causing client-side "
            "page-walkers to accumulate duplicates (issue #949)."
        )
        assert meta.total == 1
        assert meta.total_pages == 1
        assert meta.has_next is False
        # has_previous is True because the collection has items; the caller
        # overshot and can step back.
        assert meta.has_previous is True

    @pytest.mark.django_db
    def test_very_high_page_number_returns_empty(self, sample_team_with_owner_member):  # noqa: F811
        team = sample_team_with_owner_member.team
        Product.objects.create(team=team, name="Only Product")

        items, meta = _paginate_queryset(Product.objects.filter(team=team), page=999, page_size=10)

        assert items == []
        assert meta.has_next is False

    @pytest.mark.django_db
    def test_empty_queryset_returns_empty_with_no_history(self, sample_team_with_owner_member):  # noqa: F811
        """An empty queryset paired with page=1 must NOT report has_previous;
        there's no previous page when there's nothing at all."""
        team = sample_team_with_owner_member.team

        items, meta = _paginate_queryset(Product.objects.filter(team=team), page=1, page_size=10)

        assert items == []
        assert meta.total == 0
        assert meta.has_next is False
        assert meta.has_previous is False

    @pytest.mark.django_db
    def test_empty_queryset_with_out_of_range_page_still_no_history(self, sample_team_with_owner_member):  # noqa: F811
        """Empty collection + page=5 → still no history (the collection has
        no items, so there's nothing to step back to)."""
        team = sample_team_with_owner_member.team

        items, meta = _paginate_queryset(Product.objects.filter(team=team), page=5, page_size=10)

        assert items == []
        assert meta.has_previous is False, (
            "Empty queryset cannot have a previous page — there's nothing "
            "to step back to."
        )

    @pytest.mark.django_db
    def test_second_page_returns_remaining_items(self, sample_team_with_owner_member):  # noqa: F811
        """Sanity test: pagination still walks correctly for in-range pages."""
        team = sample_team_with_owner_member.team
        for i in range(15):
            Product.objects.create(team=team, name=f"Product {i:02d}")

        items_p1, meta_p1 = _paginate_queryset(Product.objects.filter(team=team), page=1, page_size=10)
        items_p2, meta_p2 = _paginate_queryset(Product.objects.filter(team=team), page=2, page_size=10)

        assert len(items_p1) == 10
        assert len(items_p2) == 5
        assert meta_p1.has_next is True
        assert meta_p2.has_next is False
        assert meta_p2.has_previous is True

        # No overlap: page 2 items must be distinct from page 1 items.
        p1_ids = {p.id for p in items_p1}
        p2_ids = {p.id for p in items_p2}
        assert p1_ids.isdisjoint(p2_ids)


# -- Integration test on the actual /api/v1/products endpoint ----------------


@pytest.mark.django_db
def test_api_list_products_out_of_range_returns_empty(
    sample_product,  # noqa: F811
    sample_access_token,  # noqa: F811
):
    """The end-to-end repro from issue #949 (workspace with 1 product):
    GET /api/v1/products?page=2 must return [], not the same product again."""
    client = Client()
    url = reverse("api-1:list_products")

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Sanity check page 1 returns the product
    r1 = client.get(url, **get_api_headers(sample_access_token))
    assert r1.status_code == 200
    assert len(r1.json()["items"]) == 1

    # The bug: page 2 used to return the same product. Now it must be empty.
    r2 = client.get(url + "?page=2", **get_api_headers(sample_access_token))
    assert r2.status_code == 200
    data = r2.json()
    assert data["items"] == []
    assert data["pagination"]["has_next"] is False
    assert data["pagination"]["total"] == 1
