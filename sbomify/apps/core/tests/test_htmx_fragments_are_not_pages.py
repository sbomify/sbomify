"""The htmx endpoints answer a direct visit with a 404, not with bare markup.

Each of these renders a section: a template extending no base, so no head, no
stylesheet, no script. htmx swaps them into a page that has all three. Typed
into a browser they used to answer 200 and serve the markup alone, looking like
nothing and doing nothing, and a URL that answers 200 also passes an uptime
check.

That stayed a curiosity until an email linked one of them and every admin
reviewing an access request landed on a bare section. This holds the rest to
saying they are not pages.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture
def fixtures(sample_team_with_owner_member: Member):
    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="frag", team=team, component_type=Component.ComponentType.BOM)
    product = Product.objects.create(name="frag-product", team=team)
    sbom = SBOM.objects.create(
        component=component, name="s", version="1.0", format="cyclonedx", format_version="1.6", sbom_filename="s.json"
    )
    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
    return client, team, component, product, sbom


def _urls(team, component, product, sbom) -> list[str]:
    return [
        reverse("core:components_table"),
        reverse("core:products_table"),
        reverse("core:releases_table"),
        reverse("core:security_advisories_table"),
        reverse("teams:team_general", kwargs={"team_key": team.key}),
        reverse("teams:team_tokens", kwargs={"team_key": team.key}),
        reverse("teams:team_branding", kwargs={"team_key": team.key}),
        reverse("teams:contact_profiles_list", kwargs={"team_key": team.key}),
        reverse("sboms:sboms_table", kwargs={"component_id": component.id}),
        reverse("documents:documents_table", kwargs={"component_id": component.id}),
        reverse("plugins:plugins_summary"),
        reverse("plugins:team_plugin_settings", kwargs={"team_key": team.key}),
        reverse("oidc:trusted_publishers", kwargs={"component_id": component.id}),
        reverse("core:product_links", kwargs={"product_id": product.id}),
        reverse("core:product_identifiers", kwargs={"product_id": product.id}),
        reverse("core:product_lifecycle", kwargs={"product_id": product.id}),
        reverse("sboms:sbom_crypto_inventory", kwargs={"sbom_id": sbom.id}),
        reverse("sboms:component_crypto_posture", kwargs={"component_id": component.id}),
        reverse("sboms:component_vex_documents", kwargs={"component_id": component.id}),
        reverse("core:component_metadata_form", kwargs={"component_id": component.id}),
    ]


def test_a_direct_visit_is_refused(fixtures) -> None:
    client, team, component, product, sbom = fixtures

    served = [url for url in _urls(team, component, product, sbom) if client.get(url).status_code != 404]

    assert not served, f"these answered a browser with a bare section: {served}"


def test_htmx_still_gets_every_one_of_them(fixtures) -> None:
    """The guard keys on the header htmx always sends, so the pages that swap
    these in are untouched. Without this half the fix is indistinguishable from
    deleting the feature."""
    client, team, component, product, sbom = fixtures

    refused = [
        url
        for url in _urls(team, component, product, sbom)
        if client.get(url, headers={"hx-request": "true"}).status_code != 200
    ]

    assert not refused, f"htmx could not load: {refused}"
