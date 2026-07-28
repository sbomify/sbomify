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


class TestTenancy:
    """These render on a public page, so a cross-tenant row would publish one
    workspace's vendor list on another's trust centre."""

    @pytest.fixture
    def other_team_product(self, sample_product):  # noqa: F811
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Team

        team = Team.objects.create(name="other workspace")
        team.key = number_to_random_token(team.pk)
        team.save()
        return Product.objects.create(name="Their product", team=team)

    def test_attaching_across_workspaces_is_rejected(self, processor, other_team_product):
        # atomic(): raising from a pre_add receiver aborts the implicit
        # transaction the M2M write opened, and fixture teardown cannot query
        # until it is closed.
        with pytest.raises(ValidationError, match="Cross-tenant SubProcessor"), transaction.atomic():
            processor.products.add(other_team_product)

    def test_the_reverse_direction_is_rejected_too(self, processor, other_team_product):
        """product.sub_processors.add(...) reaches the same M2M the other way."""
        with pytest.raises(ValidationError, match="Cross-tenant SubProcessor"), transaction.atomic():
            other_team_product.sub_processors.add(processor)

    def test_the_public_query_is_scoped_to_the_workspace(self, processor, sample_product):  # noqa: F811
        """Defence in depth: the page does not rely on the write-time guard alone."""
        from sbomify.apps.core.views.product_details_public import _get_sub_processors

        processor.products.add(sample_product)

        assert _get_sub_processors(sample_product.id, sample_product.team_id) != []
        assert _get_sub_processors(sample_product.id, sample_product.team_id + 999) == []


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


class TestApi:
    """Workspace CRUD and per-product assignment."""

    @pytest.fixture
    def owner_client(self, sample_product, sample_user):  # noqa: F811
        from sbomify.apps.teams.models import Member

        team = sample_product.team
        Member.objects.get_or_create(user=sample_user, team=team, defaults={"role": "owner"})
        client = Client()
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
        session.save()
        return client

    def test_owner_lists_them(self, owner_client, processor, sample_product):  # noqa: F811
        response = owner_client.get(f"/api/v1/workspaces/{sample_product.team.key}/sub-processors")

        assert response.status_code == 200
        assert [row["name"] for row in response.json()] == ["Amazon Web Services"]

    def test_owner_adds_one(self, owner_client, sample_product):  # noqa: F811
        response = owner_client.post(
            f"/api/v1/workspaces/{sample_product.team.key}/sub-processors",
            data={"name": "Cloudflare", "purpose": "CDN"},
            content_type="application/json",
        )

        assert response.status_code == 201
        assert SubProcessor.objects.filter(team=sample_product.team, name="Cloudflare").exists()

    def test_a_duplicate_name_is_a_clean_400(self, owner_client, processor, sample_product):  # noqa: F811
        """The unique constraint would otherwise surface as a 500."""
        response = owner_client.post(
            f"/api/v1/workspaces/{sample_product.team.key}/sub-processors",
            data={"name": "Amazon Web Services"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "already listed" in response.json()["detail"]

    def test_owner_deletes_one(self, owner_client, processor):
        response = owner_client.delete(f"/api/v1/sub-processors/{processor.id}")

        assert response.status_code == 204
        assert not SubProcessor.objects.filter(pk=processor.pk).exists()

    def test_assignment_replaces_the_set(self, owner_client, processor, sample_product):  # noqa: F811
        response = owner_client.patch(
            f"/api/v1/products/{sample_product.id}/sub-processors",
            data={"sub_processor_ids": [processor.id]},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert list(sample_product.sub_processors.all()) == [processor]

        cleared = owner_client.patch(
            f"/api/v1/products/{sample_product.id}/sub-processors",
            data={"sub_processor_ids": []},
            content_type="application/json",
        )

        assert cleared.status_code == 200
        assert sample_product.sub_processors.count() == 0

    def test_assigning_a_foreign_sub_processor_is_rejected(self, owner_client, sample_product):  # noqa: F811
        """Caught by the workspace filter, so it never reaches the M2M guard as
        an exception."""
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Team

        other = Team.objects.create(name="other workspace")
        other.key = number_to_random_token(other.pk)
        other.save()
        foreign = SubProcessor.objects.create(team=other, name="Someone else's vendor")

        response = owner_client.patch(
            f"/api/v1/products/{sample_product.id}/sub-processors",
            data={"sub_processor_ids": [foreign.id]},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert sample_product.sub_processors.count() == 0

    def test_an_outsider_cannot_read_them(self, processor, sample_product, django_user_model):  # noqa: F811
        outsider = django_user_model.objects.create_user(username="outsider", password="x")  # noqa: S106
        client = Client()
        client.force_login(outsider)

        response = client.get(f"/api/v1/workspaces/{sample_product.team.key}/sub-processors")

        assert response.status_code == 403

    def test_an_outsider_cannot_add_one(self, sample_product, django_user_model):  # noqa: F811
        outsider = django_user_model.objects.create_user(username="outsider2", password="x")  # noqa: S106
        client = Client()
        client.force_login(outsider)

        response = client.post(
            f"/api/v1/workspaces/{sample_product.team.key}/sub-processors",
            data={"name": "Sneaky"},
            content_type="application/json",
        )

        assert response.status_code == 403
        assert not SubProcessor.objects.filter(name="Sneaky").exists()
