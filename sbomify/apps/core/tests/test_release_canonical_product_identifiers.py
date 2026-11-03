"""A release canonical must resolve to the same product as the page being read."""

import re
from typing import Any
from urllib.parse import urlsplit

import pytest

from sbomify.apps.core.models import Product, Release

from . import test_slug_urls

custom_domain_team = test_slug_urls.custom_domain_team
product_with_slug = test_slug_urls.product_with_slug
setup_app_base_url = test_slug_urls.setup_app_base_url
clear_cache = test_slug_urls.clear_cache

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("case", ["unique", "slug_owner", "slug_collision", "empty_slug"])
@pytest.mark.parametrize("release_identifier", ["slug", "id"])
def test_release_canonical_keeps_product_identity(
    client: Any, product_with_slug: Product, case: str, release_identifier: str
) -> None:
    owner = product_with_slug
    collision = Product.objects.create(name=f"{owner.name}!", team=owner.team, is_public=True)
    assert collision.slug == owner.slug
    if case == "unique":
        product = Product.objects.create(name="Another product", team=owner.team, is_public=True)
    elif case == "slug_owner":
        product = owner
    elif case == "slug_collision":
        product = collision
    else:
        product = Product.objects.create(name="!!!", team=owner.team, is_public=True)
        assert not product.slug

    # Give both colliding products a release at the same slug, so a canonical
    # pointing to the wrong product serves the wrong release rather than a 404.
    releases = {
        p.id: Release.objects.create(name="v1.0.0", product=p)
        for p in {p.id: p for p in (owner, collision, product)}.values()
    }
    release = releases[product.id]
    identifier = release.slug if release_identifier == "slug" else release.id
    response = client.get(f"/product/{product.id}/release/{identifier}/", HTTP_HOST="trust.example.com")
    assert response.status_code == 200
    canonical = re.search(r'<link rel="canonical"\s+href="([^"]*)">', response.content.decode())
    assert canonical is not None
    product_identifier = product.id if case in ("slug_collision", "empty_slug") else product.slug
    expected_path = f"/product/{product_identifier}/release/{release.slug}/"
    assert canonical.group(1) == f"http://trust.example.com{expected_path}"

    destination = client.get(urlsplit(canonical.group(1)).path, HTTP_HOST="trust.example.com")
    assert destination.status_code == 200
    assert destination.context["release"]["id"] == release.id
