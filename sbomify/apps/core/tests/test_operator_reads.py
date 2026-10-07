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


def test_an_operator_has_a_way_to_its_api_keys(items) -> None:
    """The tokens tab admits every internal role, so the rail offers it to all of them."""
    team = items["team"]
    tokens = reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "tokens"})

    page = _client(team, "operator").get(reverse("core:dashboard")).content.decode()

    assert f'href="{tokens}"' in page


def test_the_report_offers_vex_upload_only_to_a_role_that_can_upload(items) -> None:
    """Uploading a VEX file needs ``artifact:publish`` as well as the triage right."""
    url = reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": items["sbom_id"]})

    operator = _client(items["team"], "operator").get(url)
    member = _client(items["team"], "member").get(url)

    assert operator.status_code == member.status_code == 200
    assert 'id="triage-modal"' in operator.content.decode()
    assert "Upload VEX" not in operator.content.decode()
    assert "Upload VEX" in member.content.decode()
