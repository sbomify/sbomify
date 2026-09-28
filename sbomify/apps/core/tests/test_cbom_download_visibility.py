"""CBOM downloads build the public view for a caller who cannot read the releases.

The product and release CBOM downloads answer anonymous callers when the product
is public. Such a caller gets the crypto assets of PUBLIC components only, the
same rule the release SBOM and VEX downloads apply, and a member's full document
never reaches them through the cache.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.sboms.models import SBOM

PUBLIC_REF = "crypto/public"
GATED_REF = "crypto/gated"
PRIVATE_REF = "crypto/private"


def _cbom(component: Component, filename: str) -> SBOM:
    return SBOM.objects.create(
        name=f"cbom-{filename}",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=filename,
        component=component,
        bom_type=SBOM.BomType.CBOM,
    )


def _doc(ref: str) -> bytes:
    return json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"type": "cryptographic-asset", "bom-ref": ref, "name": ref}],
        }
    ).encode()


def _refs(response) -> set[str]:
    return {component["bom-ref"] for component in json.loads(response.content)["components"]}


@pytest.fixture
def mixed_components(team_with_business_plan, mocker):
    """A public product holding one PUBLIC, one GATED and one PRIVATE component, each with a CBOM."""
    team = team_with_business_plan
    product = Product.objects.create(name="Mixed", team=team, is_public=True)
    components = {
        PUBLIC_REF: Component.objects.create(name="pub", team=team, visibility=Component.Visibility.PUBLIC),
        GATED_REF: Component.objects.create(name="gated", team=team, visibility=Component.Visibility.GATED),
        PRIVATE_REF: Component.objects.create(name="priv", team=team, visibility=Component.Visibility.PRIVATE),
    }
    documents = {}
    for ref, component in components.items():
        product.components.add(component)
        filename = f"{component.name}.cbom.json"
        documents[filename] = _doc(ref)
        _cbom(component, filename)

    storage = mocker.patch("sbomify.apps.core.object_store.StorageClient")
    storage.return_value.get_sbom_data.side_effect = lambda filename: documents[filename]
    cache.clear()
    return product


@pytest.fixture
def mixed_release(mixed_components):
    release = Release.objects.create(product=mixed_components, name="v1")
    for sbom in SBOM.objects.filter(component__products=mixed_components, bom_type=SBOM.BomType.CBOM):
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
    return release


def _release_url(release: Release) -> str:
    return reverse("api-1:download_release_cbom", kwargs={"release_id": release.id})


def _product_url(product: Product) -> str:
    return reverse("api-1:download_product_cbom", kwargs={"product_id": product.id})


@pytest.mark.django_db
def test_anonymous_release_cbom_holds_public_components_only(mixed_release):
    response = Client().get(_release_url(mixed_release))

    assert response.status_code == 200
    assert _refs(response) == {PUBLIC_REF}


@pytest.mark.django_db
def test_member_release_cbom_holds_every_component(mixed_release, authenticated_web_client):
    response = authenticated_web_client.get(_release_url(mixed_release))

    assert response.status_code == 200
    assert _refs(response) == {PUBLIC_REF, GATED_REF, PRIVATE_REF}


@pytest.mark.django_db
def test_release_cbom_cache_keeps_the_member_view_from_anonymous_callers(mixed_release, authenticated_web_client):
    authenticated_web_client.get(_release_url(mixed_release))

    response = Client().get(_release_url(mixed_release))

    assert _refs(response) == {PUBLIC_REF}


@pytest.mark.django_db
def test_anonymous_product_cbom_holds_public_components_only(mixed_components):
    response = Client().get(_product_url(mixed_components))

    assert response.status_code == 200
    assert _refs(response) == {PUBLIC_REF}


@pytest.mark.django_db
def test_member_product_cbom_holds_every_component(mixed_components, authenticated_web_client):
    response = authenticated_web_client.get(_product_url(mixed_components))

    assert response.status_code == 200
    assert _refs(response) == {PUBLIC_REF, GATED_REF, PRIVATE_REF}


@pytest.mark.django_db
def test_anonymous_release_cbom_is_absent_when_only_private_components_carry_one(team_with_business_plan, mocker):
    team = team_with_business_plan
    product = Product.objects.create(name="Private crypto", team=team, is_public=True)
    private = Component.objects.create(name="priv", team=team, visibility=Component.Visibility.PRIVATE)
    release = Release.objects.create(product=product, name="v1")
    ReleaseArtifact.objects.create(release=release, sbom=_cbom(private, "priv.cbom.json"))
    storage = mocker.patch("sbomify.apps.core.object_store.StorageClient")
    storage.return_value.get_sbom_data.return_value = _doc(PRIVATE_REF)
    cache.clear()

    response = Client().get(_release_url(release))

    assert response.status_code == 404
