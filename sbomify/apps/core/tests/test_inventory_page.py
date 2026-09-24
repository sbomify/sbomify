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


@pytest.mark.parametrize("kind", ["products", "components", "releases"])
@pytest.mark.parametrize("scoped", [False, True])
def test_inventory_only_hydrates_models_used_by_selected_view(
    sample_team_with_owner_member: Member, mocker: MockerFixture, kind: str, scoped: bool
) -> None:
    from sbomify.apps.core.services.inventory_page import build_inventory_snapshot

    workspace = sample_team_with_owner_member.team
    product = Product.objects.create(team=workspace, name="Selected product")
    component = Component.objects.create(team=workspace, name="Selected component")
    product.components.add(component)
    Release.objects.create(product=product, name="v1")
    other = Product.objects.create(team=workspace, name="Other product")
    other.components.add(Component.objects.create(team=workspace, name="Other component"))
    release_count = Release.objects.filter(product=product).count() if scoped else Release.objects.count()
    component_loads = mocker.spy(Component, "from_db")
    release_loads = mocker.spy(Release, "from_db")

    snapshot = build_inventory_snapshot(workspace, kind, product_id=product.id if scoped else "")

    assert snapshot["counts"] == {
        "products": 1 if scoped else 2,
        "components": 1 if scoped else 2,
        "releases": release_count,
    }
    assert snapshot["rows"]
    if kind == "releases":
        component_loads.assert_not_called()
    else:
        release_loads.assert_not_called()


@pytest.fixture
def populated_inventory(sample_team_with_owner_member: Member) -> Member:
    member = sample_team_with_owner_member
    for index in range(13):
        product = Product.objects.create(
            team=member.team,
            name=f"Product {index:02}",
            description="Searchable description",
            is_public=index % 2 == 0,
        )
        component = Component.objects.create(
            team=member.team,
            name=f"Component {index:02}",
            visibility="public" if index % 2 == 0 else "private",
            component_type="document" if index == 12 else "bom",
        )
        product.components.add(component)
        release = Release.objects.create(product=product, name=f"Version {index:02}", is_prerelease=index % 2 == 0)
        if index % 3 != 0 and index != 12:
            sbom = scan(component, f"CVE-EXAMPLE-{index}" if index % 3 == 1 else None)
            ReleaseArtifact.objects.create(release=release, sbom=sbom)
    Component.objects.create(team=member.team, name="Unassigned Straße")
    return member


@pytest.mark.parametrize("kind", ["products", "components", "releases"])
def test_inventory_assesses_only_the_visible_page(
    populated_inventory: Member, mocker: MockerFixture, kind: str
) -> None:
    from sbomify.apps.core.services import inventory_page

    component_picture = mocker.spy(inventory_page, "build_component_security_picture")
    release_picture = mocker.spy(inventory_page, "build_release_vuln_postures")
    result = inventory(populated_inventory, view=kind, page="2")
    ids = {row["id"] for row in result["rows"]}
    assert result["page"].paginator.count > 10
    assert ids
    if kind == "releases":
        component_picture.assert_not_called()
        assert {release.id for release in release_picture.call_args.args[0]} == ids
    else:
        release_picture.assert_not_called()
        expected = (
            ids
            if kind == "components"
            else set(
                Component.objects.filter(team=populated_inventory.team, products__id__in=ids).values_list(
                    "id", flat=True
                )
            )
        )
        assert set(component_picture.call_args.args[0]) == expected


@pytest.mark.parametrize("kind", ["products", "components", "releases"])
def test_paged_inventory_preserves_full_snapshot_filter_and_sort_contract(
    populated_inventory: Member, kind: str
) -> None:
    from sbomify.apps.core.services.inventory_page import COLUMNS, build_inventory_snapshot, build_inventory_table

    member = populated_inventory
    snapshot = build_inventory_snapshot(member.team, kind)
    cases = [
        {},
        {"page": "2"},
        {"page": "999"},
        {"page": "bad"},
        {"page": "-1"},
        {"per_page": "25"},
        {"search": "missing"},
        {"search": "strasse"},
        {"search": "Product 01"},
        {"search": "Searchable description"},
        {"visibility": "public"},
        {"visibility": "private"},
        {"risk": "attention"},
        {"risk": "clear"},
        {"risk": "unassessed"},
        {"search": "01", "risk": "attention", "direction": "desc"},
        {"sort": "bad", "direction": "bad", "per_page": "0", "risk": "bad", "visibility": "bad"},
        *({"sort": column, "direction": direction} for column, _ in COLUMNS[kind] for direction in ("asc", "desc")),
    ]
    if kind != "products":
        cases.append({"product": snapshot["products"][0]["id"]})
    if kind == "components":
        cases.append({"product": "unassigned"})
    for params in cases:
        request = RequestFactory().get("/products/", {"view": kind, **params})
        expected = build_inventory_table(request, snapshot, kind=kind)
        assert expected.ok and expected.value is not None
        actual = inventory(member, view=kind, **params)
        expected_table = expected.value["inventory"]
        assert actual["rows"] == expected_table["rows"], params
        assert actual["page"].number == expected_table["page"].number, params
        assert actual["page"].paginator.count == expected_table["page"].paginator.count, params
        for field in ("total", "tabs", "products", "headers", "query", "refresh_url"):
            assert actual[field] == expected_table[field], (params, field)


@pytest.mark.parametrize("kind", ["products", "components", "releases"])
def test_inventory_narrows_security_work_before_risk_filter(
    populated_inventory: Member, mocker: MockerFixture, kind: str
) -> None:
    from sbomify.apps.core.services import inventory_page

    picture = mocker.spy(inventory_page, "build_component_security_picture")
    postures = mocker.spy(inventory_page, "build_release_vuln_postures")
    result = inventory(populated_inventory, view=kind, search="01", risk="attention")
    assert result["rows"]
    if kind == "releases":
        # Search includes the product name, so both its pinned and rolling
        # releases match. Both must be assessed before filtering by risk.
        expected_ids = set(
            Release.objects.filter(product__team=populated_inventory.team, product__name="Product 01").values_list(
                "id", flat=True
            )
        )
        assert {release.id for release in postures.call_args.args[0]} == expected_ids
    else:
        assert len(result["rows"]) == 1
        assert len(picture.call_args.args[0]) == 1
