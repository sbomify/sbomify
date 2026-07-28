"""Workspace sub-processors and their appearance on a public product page.

A trust centre lists these because a customer's own compliance obligations flow
through to whoever actually processes the data. They belong to the workspace,
since one vendor usually sits behind several products, and attach to products
through an M2M so a product page shows only its own chain.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.sboms.models import Product, SubProcessor
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_component,
    sample_product,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def processor(sample_product):  # noqa: F811
    return SubProcessor.objects.create(
        team=sample_product.team,
        name="Amazon Web Services",
        purpose="Hosting",
        url="https://aws.amazon.com",
        location="EU (Frankfurt)",
    )


class TestModel:
    def test_it_belongs_to_the_workspace_not_a_product(self, processor, sample_product):  # noqa: F811
        """One vendor normally sits behind several products."""
        assert processor.team_id == sample_product.team_id
        assert processor.products.count() == 0

    def test_it_attaches_to_products(self, processor, sample_product):  # noqa: F811
        processor.products.add(sample_product)

        assert list(sample_product.sub_processors.all()) == [processor]

    def test_one_vendor_serves_several_products(self, processor, sample_product):  # noqa: F811
        second = Product.objects.create(name="Second product", team=sample_product.team)
        processor.products.add(sample_product, second)

        assert processor.products.count() == 2

    def test_a_name_is_required(self, sample_product):  # noqa: F811
        with pytest.raises(ValidationError, match="needs a name"):
            SubProcessor.objects.create(team=sample_product.team, name="   ")

    def test_names_are_stripped(self, sample_product):  # noqa: F811
        processor = SubProcessor.objects.create(team=sample_product.team, name="  Cloudflare  ")

        assert processor.name == "Cloudflare"

    def test_a_name_is_unique_within_a_workspace(self, processor, sample_product):  # noqa: F811
        """Two rows for the same vendor would show as duplicates on the page."""
        with pytest.raises(IntegrityError), transaction.atomic():
            SubProcessor.objects.create(team=sample_product.team, name="Amazon Web Services")

    def test_an_invalid_url_is_rejected(self, sample_product):  # noqa: F811
        with pytest.raises(ValidationError):
            SubProcessor.objects.create(team=sample_product.team, name="Bad", url="not a url")

    def test_deleting_the_workspace_takes_them_with_it(self, processor, sample_product):  # noqa: F811
        team = sample_product.team
        team.delete()

        assert not SubProcessor.objects.filter(pk=processor.pk).exists()

    def test_deleting_a_product_keeps_the_vendor(self, processor, sample_product):  # noqa: F811
        """The vendor still serves the workspace's other products.

        A throwaway product, not the fixture's: the fixture deletes its own in
        teardown and would fail on a row this test already removed.
        """
        doomed = Product.objects.create(name="Retired product", team=sample_product.team)
        processor.products.add(doomed)
        doomed.delete()

        processor.refresh_from_db()
        assert processor.products.count() == 0


class TestPublicPage:
    @staticmethod
    def _get(product):
        product.is_public = True
        product.save()
        return Client().get(reverse("core:product_details_public", kwargs={"product_id": product.id}))

    def test_an_attached_processor_is_listed(self, processor, sample_product):  # noqa: F811
        processor.products.add(sample_product)

        content = self._get(sample_product).content.decode()

        assert "Sub-processors" in content
        assert "Amazon Web Services" in content
        assert "EU (Frankfurt)" in content

    def test_an_unattached_processor_is_not_listed(self, processor, sample_product):  # noqa: F811
        """It belongs to the workspace, but this product does not use it."""
        content = self._get(sample_product).content.decode()

        assert "Amazon Web Services" not in content

    def test_the_section_is_absent_when_there_are_none(self, sample_product):  # noqa: F811
        content = self._get(sample_product).content.decode()

        assert "Sub-processors" not in content
