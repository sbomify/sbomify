"""The unified inventory preserves workspace boundaries and assessment meaning."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client, RequestFactory
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.services.inventory_page import build_inventory_context
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


def inventory(member: Member, **params: str) -> dict:
    request = RequestFactory().get("/products/", params)
    request.user = member.user
    request.session = {"current_team": {"key": member.team.key, "role": "owner"}}
    result = build_inventory_context(request)
    assert result.ok, result.error
    assert result.value is not None
    return result.value["inventory"]


def scan(component: Component, advisory: str | None = None) -> SBOM:
    sbom = SBOM.objects.create(
        name="bom",
        component=component,
        version=str(SBOM.objects.filter(component=component).count() + 1),
        format="cyclonedx",
    )
    findings = [{"id": advisory, "severity": "high", "component": {"name": "pkg", "version": "1"}}] if advisory else []
    run = AssessmentRun.objects.create(
        sbom=sbom, plugin_name="osv", category="security", status="completed", result={"findings": findings}
    )
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    sync_findings(run)
    return sbom


def test_inventory_distinguishes_unassessed_clear_and_documents(sample_team_with_owner_member: Member) -> None:
    member = sample_team_with_owner_member
    empty = Component.objects.create(team=member.team, name="Unscanned")
    clean = Component.objects.create(team=member.team, name="Clean")
    document = Component.objects.create(team=member.team, name="Guide", component_type="document")
    scan(clean)
    assert [r["id"] for r in inventory(member, view="components", risk="unassessed")["rows"]] == [empty.id]
    assert [r["id"] for r in inventory(member, view="components", risk="clear")["rows"]] == [clean.id]
    rows = {r["id"]: r for r in inventory(member, view="components")["rows"]}
    assert not rows[document.id]["security_applicable"]
    assert rows[clean.id]["freshness_label"] == "No policy"


def test_product_scope_and_security_rollup(sample_team_with_owner_member: Member) -> None:
    member = sample_team_with_owner_member
    local = Component.objects.create(team=member.team, name="Local")
    foreign = Component.objects.create(team=Team.objects.create(name="Other"), name="Secret")
    scan(local, "CVE-LOCAL")
    scan(foreign, "CVE-SECRET")
    product = Product.objects.create(team=member.team, name="Local product")
    product.components.add(local)
    Product.objects.create(team=foreign.team, name="Secret product").components.add(foreign)
    row = inventory(member)["rows"][0]
    assert row["component_count"] == 1
    assert row["counts"]["high"] == 1
    assert row["no_policy"] == 1
    assert "Secret" not in str(inventory(member, view="components"))


def test_release_uses_pinned_artifacts_and_excludes_foreign_joins(sample_team_with_owner_member: Member) -> None:
    member = sample_team_with_owner_member
    component = Component.objects.create(team=member.team, name="Library")
    old = scan(component, "CVE-PINNED")
    scan(component)  # The latest component SBOM is now clean.
    product = Product.objects.create(team=member.team, name="Product")
    release = Release.objects.create(product=product, name="v1")
    ReleaseArtifact.objects.create(release=release, sbom=old)
    foreign = Component.objects.create(team=Team.objects.create(name="Other"), name="Secret")
    ReleaseArtifact.objects.bulk_create([ReleaseArtifact(release=release, sbom=scan(foreign, "CVE-FOREIGN"))])
    row = next(r for r in inventory(member, view="releases")["rows"] if r["id"] == release.id)
    assert row["counts"]["high"] == 1
    assert row["unassessed"] == 0


def test_filters_sort_and_pagination_preserve_query(sample_team_with_owner_member: Member) -> None:
    member = sample_team_with_owner_member
    for n in range(12):
        Product.objects.create(team=member.team, name=f"Product {n:02}", is_public=True)
    Product.objects.create(team=member.team, name="Private")
    result = inventory(member, visibility="public", sort="name", direction="desc", page="2", search="Product")
    assert len(result["rows"]) == 2
    assert result["rows"][0]["name"] == "Product 01"
    assert result["page"].paginator.count == 12
    assert "visibility=public" in result["query"]
    assert "search=Product" in result["headers"][0]["href"]
    assert inventory(member, page="bogus", sort="bogus", per_page="0")["page"].number == 1


def test_live_membership_required_even_with_cached_owner_role(sample_team_with_owner_member: Member) -> None:
    member = sample_team_with_owner_member
    member.role = "guest"
    member.save(update_fields=["role"])
    request = RequestFactory().get("/products/")
    request.user = member.user
    request.session = {"current_team": {"key": member.team.key, "role": "owner"}}
    assert build_inventory_context(request).status_code == 404


@pytest.mark.parametrize("view", ["products", "releases", "components"])
def test_inventory_renders_full_and_partial_pages(
    client: Client,
    sample_team_with_owner_member: Member,
    mocker: MockerFixture,
    view: str,
    django_assert_max_num_queries: Any,
) -> None:
    member = sample_team_with_owner_member
    product = Product.objects.create(team=member.team, name="Example", is_public=True)
    component = Component.objects.create(team=member.team, name="Library")
    product.components.add(component)
    ReleaseArtifact.objects.create(
        release=Release.objects.create(product=product, name="v1"), sbom=scan(component, "CVE-EXAMPLE")
    )
    setup_authenticated_client_session(client, member.team, member.user)
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)
    response = client.get(reverse(f"core:{view}_dashboard"))
    assert response.status_code == 200
    assert b"<c-" not in response.content
    assert b'id="inventory-content"' in response.content
    # Rendering nested components must not rerun workspace queries for each one.
    with django_assert_max_num_queries(40):
        partial = client.get(
            reverse("core:products_dashboard"),
            {"view": view},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="inventory-content",
        )
    assert partial.status_code == 200
    assert b"<html" not in partial.content
    assert b'id="inventory-content"' in partial.content
    assert "HX-Target" in response["Vary"]
    assert "HX-Target" in partial["Vary"]
    if view == "releases":
        assert client.post(reverse("core:releases_dashboard")).status_code == 405


def test_release_summary_only_and_skipped_results(sample_team_with_owner_member: Member) -> None:
    member = sample_team_with_owner_member
    product = Product.objects.create(team=member.team, name="Product")
    component = Component.objects.create(team=member.team, name="Library")
    sbom = scan(component)
    release = Release.objects.create(product=product, name="v1")
    ReleaseArtifact.objects.create(release=release, sbom=sbom)
    run = AssessmentRun.objects.get(sbom=sbom)
    run.result = {"summary": {"total_findings": 5, "by_severity": {"high": 3}}}
    run.save()
    row = next(r for r in inventory(member, view="releases")["rows"] if r["id"] == release.id)
    assert row["counts"]["total"] == 5
    assert row["counts"]["unknown"] == 2
    run.result = {"metadata": {"skipped": True}, "findings": []}
    run.save()
    row = next(r for r in inventory(member, view="releases")["rows"] if r["id"] == release.id)
    assert row["unassessed"] == 1
    assert not row["assessed"]
    assert not any(r["id"] == release.id for r in inventory(member, view="releases", risk="clear")["rows"])
