"""Product details retain workspace boundaries and use the shared inventory snapshot."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client, RequestFactory
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.services.product_page import build_product_page_context
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.tests.test_inventory_page import scan
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


def context(member: Member, item: Product, **params: str) -> dict[str, Any]:
    request = RequestFactory().get(reverse("core:product_details", args=[item.id]), params)
    request.user = member.user
    request.session = {"current_team": {"key": member.team.key, "role": "owner"}}
    result = build_product_page_context(request, item.id)
    assert result.ok, result.error
    assert result.value is not None
    return result.value


def test_product_metrics_remain_unfiltered_and_releases_use_their_own_artifacts(
    sample_team_with_owner_member: Member,
) -> None:
    member = sample_team_with_owner_member
    product = Product.objects.create(name="Product", team=member.team)
    risky = Component.objects.create(name="Risky", team=member.team)
    clean = Component.objects.create(name="Clean", team=member.team)
    unassessed = Component.objects.create(name="Unassessed", team=member.team)
    document = Component.objects.create(name="Guide", team=member.team, component_type="document")
    product.components.add(risky, clean, unassessed, document)
    old = scan(clean, "CVE-OLD")
    scan(clean)
    scan(risky, "CVE-CURRENT")
    release = Release.objects.create(product=product, name="v1")
    ReleaseArtifact.objects.create(release=release, sbom=old)
    result = context(member, product, search="Clean")
    assert [row["id"] for row in result["inventory"]["rows"]] == [clean.id]
    assert result["metrics"] == {"components": 4, "artifacts": 3, "open": 1, "past_sla": 0, "unassessed": 1}
    row = next(row for row in result["release_inventory"]["rows"] if row["id"] == release.id)
    assert row["counts"]["high"] == 1
    result = context(member, product, risk="unassessed")
    assert [row["id"] for row in result["inventory"]["rows"]] == [unassessed.id]


def test_product_scope_cannot_be_changed_by_filters_or_foreign_relationships(
    sample_team_with_owner_member: Member,
) -> None:
    member = sample_team_with_owner_member
    product = Product.objects.create(name="Product", team=member.team)
    other = Product.objects.create(name="Other", team=member.team)
    own = Component.objects.create(name="Own", team=member.team)
    unrelated = Component.objects.create(name="Unrelated", team=member.team)
    foreign = Component.objects.create(name="Secret", team=Team.objects.create(name="Foreign"))
    product.components.add(own)
    from sbomify.apps.sboms.models import ProductComponent

    ProductComponent.objects.bulk_create([ProductComponent(product=product, component=foreign)])
    other.components.add(unrelated)
    result = context(member, product, product=other.id)
    assert [row["id"] for row in result["inventory"]["rows"]] == [own.id]
    assert "Secret" not in str(result)
    assert result["inventory"]["params"]["product"] == product.id
    assert all(
        header["href"].startswith(reverse("core:product_details", args=[product.id]))
        for header in result["inventory"]["headers"]
    )


def test_product_membership_forms_preserve_other_assignments_and_reject_foreign_or_global_components(
    sample_team_with_owner_member: Member,
) -> None:
    member = sample_team_with_owner_member
    product = Product.objects.create(name="Product", team=member.team)
    first = Component.objects.create(name="First", team=member.team)
    second = Component.objects.create(name="Second", team=member.team)
    shared = Product.objects.create(name="Shared", team=member.team)
    shared.components.add(first)
    product.components.add(first)
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)
    url = reverse("core:product_details", args=[product.id])
    response = client.post(url, {"action": "assign_component", "component_id": second.id}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert "refresh-product" in response["HX-Trigger"]
    assert set(product.components.values_list("id", flat=True)) == {first.id, second.id}
    client.post(url, {"action": "remove_component", "component_id": first.id}, HTTP_HX_REQUEST="true")
    assert list(product.components.values_list("id", flat=True)) == [second.id]
    assert shared.components.filter(id=first.id).exists()
    invalid = [
        Component.objects.create(
            name="Workspace document", team=member.team, component_type="document", is_global=True
        ),
        Component.objects.create(name="Foreign", team=Team.objects.create(name="Other workspace")),
    ]
    for component in invalid:
        response = client.post(
            url, {"action": "assign_component", "component_id": component.id}, HTTP_HX_REQUEST="true"
        )
        assert response["HX-Reswap"] == "none"
        assert list(product.components.values_list("id", flat=True)) == [second.id]


def test_demoted_member_cannot_write_with_cached_owner_session(sample_team_with_owner_member: Member) -> None:
    member = sample_team_with_owner_member
    product = Product.objects.create(name="Product", team=member.team)
    component = Component.objects.create(name="Component", team=member.team)
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)
    member.role = "guest"
    member.save(update_fields=["role"])
    client.post(
        reverse("core:product_details", args=[product.id]), {"action": "assign_component", "component_id": component.id}
    )
    assert not product.components.exists()


def test_product_partial_is_a_single_frame_and_hides_unavailable_actions(sample_team_with_owner_member: Member) -> None:
    member = sample_team_with_owner_member
    product = Product.objects.create(name="Product", team=member.team)
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)
    member.role = "member"
    member.save(update_fields=["role"])
    response = client.get(reverse("core:product_details", args=[product.id]), HTTP_HX_TARGET="product-content")
    html = response.content.decode()
    assert response.status_code == 200
    assert html.count('id="product-content"') == 1
    assert "<html" not in html
    assert "Assign component" in html
    assert "Product visibility" not in html
    assert "Delete Product" not in html
    assert "HX-Target" in response["Vary"]
