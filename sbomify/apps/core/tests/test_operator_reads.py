"""An operator reads every private item a member reads, and gets no way in to change it.

``operator`` holds the READ_INTERNAL tier, but private reads that asked a
``*:manage`` action answered it 403 while a member got the item. These pin each
read to the answer a member gets, and the upload affordance to the role that
can use it.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, ComponentRelease, Product, Release
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture
def items(team_with_business_plan) -> dict:
    team = team_with_business_plan
    product = Product.objects.create(name="Private product", team=team, is_public=False)
    component = Component.objects.create(name="Private component", team=team)
    product.components.add(component)
    return {
        "team": team,
        "product_id": product.id,
        "component_id": component.id,
        "release_id": Release.objects.create(product=product, name="v1").id,
        "component_release_id": ComponentRelease.objects.create(component=component, version="1.0").id,
        "sbom_id": SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.6").id,
    }


def _client(team, role: str) -> Client:
    user = get_user_model().objects.create_user(username=f"{role}-reader", email=f"{role}-reader@example.com")
    Member.objects.create(team=team, user=user, role=role)
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


READS = [
    ("api-1:get_product", "product_id"),
    ("api-1:get_product_eol_readiness", "product_id"),
    ("api-1:list_product_identifiers", "product_id"),
    ("api-1:list_product_links", "product_id"),
    ("api-1:download_product_sbom", "product_id"),
    ("api-1:download_product_cbom", "product_id"),
    ("api-1:list_cle_events", "product_id"),
    ("api-1:list_cle_support_definitions", "product_id"),
    ("api-1:get_component", "component_id"),
    ("api-1:list_component_releases", "component_id"),
    ("api-1:list_component_cle_events", "component_id"),
    ("api-1:list_component_cle_support_definitions", "component_id"),
    ("api-1:get_release", "release_id"),
    ("api-1:list_release_cle_events", "release_id"),
    ("api-1:list_release_cle_support_definitions", "release_id"),
    ("api-1:list_component_release_cle_events", "component_release_id"),
    ("api-1:list_component_release_cle_support_definitions", "component_release_id"),
    ("core:sbom_download_product", "product_id"),
    ("core:get_component_metadata", "component_id"),
]


@pytest.mark.parametrize(("url_name", "key"), READS)
def test_an_operator_reads_what_a_member_reads(url_name, key, items) -> None:
    url = reverse(url_name, kwargs={key: items[key]})

    member = _client(items["team"], "member").get(url).status_code
    operator = _client(items["team"], "operator").get(url).status_code

    assert member != 403
    assert operator == member


@pytest.mark.parametrize(("url_name", "key"), READS)
def test_a_guest_still_reads_none_of_it(url_name, key, items) -> None:
    url = reverse(url_name, kwargs={key: items[key]})

    assert _client(items["team"], "guest").get(url).status_code == 403


WORKSPACE_VULNERABILITY_READS = [
    "vulnerability-kpis",
    "vulnerability-stats",
    "vulnerability-timeseries?days=7",
    "vulnerability-drill-down?filter_type=severity&filter_value=high&days=7",
]


def _workspace_url(team, path: str) -> str:
    return f"/api/v1/vulnerability-scanning/workspaces/{team.key}/{path}"


@pytest.mark.parametrize("path", WORKSPACE_VULNERABILITY_READS)
@pytest.mark.parametrize("role", ["member", "operator"])
def test_every_internal_role_reads_the_workspace_vulnerability_dashboards(path, role, items) -> None:
    """``workspace:read`` decides, as it does for the trends and heatmap beside them."""
    response = _client(items["team"], role).get(_workspace_url(items["team"], path))

    assert response.status_code == 200, response.content


@pytest.mark.parametrize("path", WORKSPACE_VULNERABILITY_READS)
def test_a_read_only_token_reads_the_workspace_vulnerability_dashboards(path, items) -> None:
    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.access_tokens.utils import create_personal_access_token
    from sbomify.apps.core.authz import SCOPE_PRESETS

    team = items["team"]
    user = get_user_model().objects.create_user(username="operator-script", email="operator-script@example.com")
    Member.objects.create(team=team, user=user, role="operator")
    token = create_personal_access_token(user)
    AccessToken.objects.create(
        user=user, encoded_token=token, description="triage", team=team, scopes=SCOPE_PRESETS["read_only"]
    )

    response = Client().get(_workspace_url(team, path), HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 200, response.content


@pytest.mark.parametrize("path", WORKSPACE_VULNERABILITY_READS)
def test_a_guest_still_reads_no_workspace_vulnerability_dashboard(path, items) -> None:
    assert _client(items["team"], "guest").get(_workspace_url(items["team"], path)).status_code == 403


def test_an_operator_has_a_way_to_its_api_keys(items) -> None:
    """The tokens tab admits every internal role, so the rail offers it to all of them."""
    team = items["team"]
    tokens = reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "tokens"})

    page = _client(team, "operator").get(reverse("core:dashboard")).content.decode()

    assert f'href="{tokens}"' in page


def test_an_operator_has_a_way_to_the_cryptography_page(items) -> None:
    """The page admits every internal role, so the rail offers it to all of them."""
    team = items["team"]
    crypto = reverse("sboms:workspace_crypto", kwargs={"team_key": team.key})

    page = _client(team, "operator").get(reverse("core:dashboard")).content.decode()

    assert f'href="{crypto}"' in page


@pytest.mark.parametrize(("role", "offered"), [("operator", True), ("member", True), ("guest", False)])
def test_the_overview_offers_triage_to_every_role_that_can_triage(role, offered, items, mocker) -> None:
    """The Overview's Triage action opens a modal that admits every triage role, operators included."""
    from sbomify.apps.core.services import dashboard_page

    real = dashboard_page.build_dashboard_context
    finding = {
        "id": "CVE-2026-0001",
        "severity": "high",
        "kev": False,
        "malicious": False,
        "package": "libexample",
        "version": "1.0",
        "ecosystem": "pypi",
        "component_id": items["component_id"],
        "component_name": "Private component",
        "products": ["Private product"],
        "decision": "",
        "sla": {"label": "7 days", "overdue": False},
    }

    def with_one_finding(team_id):
        result = real(team_id)
        return result.__class__.success({**result.value, "needs_attention": [finding]})

    mocker.patch.object(dashboard_page, "build_dashboard_context", with_one_finding)
    team = items["team"]
    team.has_completed_wizard = True
    team.save(update_fields=["has_completed_wizard"])
    client = _client(team, role)
    session = client.session
    session["current_workspace"]["has_completed_wizard"] = True
    session.save()

    response = client.get(reverse("core:dashboard"))
    page = response.content.decode()
    modal = reverse("core:component_triage_modal", kwargs={"component_id": items["component_id"]})

    if offered:
        assert response.status_code == 200
        assert 'id="priority-triage-host"' in page
        assert modal in page
    else:
        assert modal not in page


def test_the_report_offers_vex_upload_only_to_a_role_that_can_upload(items) -> None:
    """Uploading a VEX file needs ``artifact:publish`` as well as the triage right."""
    url = reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": items["sbom_id"]})

    operator = _client(items["team"], "operator").get(url)
    member = _client(items["team"], "member").get(url)

    assert operator.status_code == member.status_code == 200
    assert 'id="triage-modal"' in operator.content.decode()
    assert "Upload VEX" not in operator.content.decode()
    assert "Upload VEX" in member.content.decode()
