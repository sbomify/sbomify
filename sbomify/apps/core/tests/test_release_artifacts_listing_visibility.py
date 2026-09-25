"""The release artifact listing follows the release detail's visibility rule.

The release detail hides PRIVATE components' artifacts from anyone who cannot
manage the release. The artifact listing now does the same in ``existing`` mode,
and ``available`` mode, the release editor's picker, needs ``release:manage``.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.sboms.models import SBOM

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_release(team_with_business_plan):
    team = team_with_business_plan
    product = Product.objects.create(name="Public", team=team, is_public=True)
    release = Release.objects.create(product=product, name="v1")
    for visibility in (Component.Visibility.PUBLIC, Component.Visibility.GATED, Component.Visibility.PRIVATE):
        component = Component.objects.create(name=visibility, team=team, visibility=visibility)
        product.components.add(component)
        sbom = SBOM.objects.create(name=visibility, component=component, format="cyclonedx", format_version="1.6")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
    return release


def _url(release: Release, mode: str) -> str:
    return reverse("api-1:list_release_artifacts", kwargs={"release_id": release.id}) + f"?mode={mode}&page_size=-1"


def _listed_component_names(response) -> set[str]:
    return {item["component_name"] for item in response.json()["items"]}


def test_anonymous_existing_listing_leaves_out_private_components(public_release):
    response = Client().get(_url(public_release, "existing"))

    assert response.status_code == 200
    assert _listed_component_names(response) == {Component.Visibility.PUBLIC, Component.Visibility.GATED}


def test_manager_existing_listing_shows_every_component(public_release, authenticated_web_client):
    response = authenticated_web_client.get(_url(public_release, "existing"))

    assert response.status_code == 200
    assert _listed_component_names(response) == {
        Component.Visibility.PUBLIC,
        Component.Visibility.GATED,
        Component.Visibility.PRIVATE,
    }


def test_anonymous_available_listing_is_refused(public_release):
    response = Client().get(_url(public_release, "available"))

    assert response.status_code == 403


def test_manager_available_listing_still_works(public_release, authenticated_web_client):
    response = authenticated_web_client.get(_url(public_release, "available"))

    assert response.status_code == 200
