import hashlib
from datetime import timedelta
from typing import Generator

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.tests.e2e.factories import *  # noqa: F403
from sbomify.apps.sboms.models import ProductIdentifier, ProductLink


@pytest.fixture
def dashboard(
    product_factory,
    component_factory,
    sbom_factory,
    vulnerability_scan_factory,
) -> Generator[dict[str, list], None, None]:
    data = {}

    products = [product_factory(f"Test Product {i}", is_public=(i % 2 == 0)) for i in range(5)]
    data["products"] = products

    components = []

    for i in range(2):
        args = {"product": products[0]} if i % 2 == 0 else {}
        components.append(component_factory(f"Product 0 BOM Component {i}", Component.ComponentType.BOM, **args))

    bom_comp = component_factory("Private BOM Component", Component.ComponentType.BOM, product=products[1])
    sbom_factory(bom_comp, name="private-sbom.json", version="1.0.0")
    components.append(bom_comp)
    components.append(
        component_factory("Private Document Component", Component.ComponentType.DOCUMENT, product=products[1])
    )

    for i in range(4):
        args: dict = {"product": products[4]}
        if i % 2 == 0:
            args["product"] = None
        if i % 3 == 0:
            args["is_global"] = True
        components.append(component_factory(f"Product 4 Component {i}", **args))

    data["components"] = components

    sboms = [
        sbom_factory(c, name=f"sbom-{i}.json", version=f"1.0.{i}")
        for i, c in enumerate(components)
        if c.component_type == Component.ComponentType.BOM
    ]
    data["sboms"] = sboms

    scan_results = []
    start_date = timezone.now() - timedelta(days=29)
    providers = ["osv", "dependency_track"]

    for day_offset in range(30):
        created_at = start_date + timedelta(days=day_offset)
        scans_per_day = 1 if day_offset % 2 == 0 else 2

        for scan_idx in range(scans_per_day):
            sbom = sboms[scan_idx % len(sboms)]
            provider = providers[scan_idx % len(providers)]
            result = vulnerability_scan_factory(sbom, provider=provider, created_at=created_at)
            scan_results.append(result)

    data["scan_results"] = scan_results

    yield data


@pytest.fixture
def empty_product_details(product_factory) -> Generator[Product, None, None]:
    name = "Empty Product"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    yield product_factory(name=name, _id=_id)


@pytest.fixture
def product_details(product_factory, component_factory, sbom_factory) -> Generator[Product, None, None]:
    name = "Test Product Details"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    product = product_factory(name=name, _id=_id)

    bom = component_factory("Product BOM Component", Component.ComponentType.BOM, product=product)
    sbom_factory(bom, name="product-sbom.json", version="1.0.0")
    component_factory("Product Document Component", Component.ComponentType.DOCUMENT, product=product)

    ProductIdentifier.objects.bulk_create(
        [
            ProductIdentifier(
                product=product,
                identifier_type=ProductIdentifier.IdentifierType.SKU,
                value="SKU-12345",
                team=product.team,
            ),
            ProductIdentifier(
                product=product,
                identifier_type=ProductIdentifier.IdentifierType.CPE,
                value="cpe:2.3:a:test:product:1.0.0:*:*:*:*:*:*:*",
                team=product.team,
            ),
        ]
    )

    ProductLink.objects.bulk_create(
        [
            ProductLink(
                product=product,
                link_type=ProductLink.LinkType.WEBSITE,
                title="Product Website",
                url="https://example.com/product",
                team=product.team,
            ),
            ProductLink(
                product=product,
                link_type=ProductLink.LinkType.REPOSITORY,
                title="GitHub Repository",
                url="https://github.com/example/product",
                team=product.team,
            ),
            ProductLink(
                product=product,
                link_type=ProductLink.LinkType.DOCUMENTATION,
                title="Documentation",
                url="https://docs.example.com/product",
                team=product.team,
            ),
        ]
    )

    Release.objects.bulk_create(
        [
            Release(
                product=product, name="v1.0.0", description="Initial release", is_latest=False, is_prerelease=False
            ),
            Release(product=product, name="v1.1.0", description="Minor update", is_latest=True, is_prerelease=False),
            Release(
                product=product, name="v2.0.0-beta", description="Beta release", is_latest=False, is_prerelease=True
            ),
        ]
    )

    yield product


@pytest.fixture
def sbom_component_details(
    component_factory,
    product_factory,
    component_author_factory,
    component_license_factory,
    vulnerability_scan_factory,
    sbom_factory,
):
    product = product_factory("Test Product")

    name = "Test BOM Component"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    component = component_factory(
        name=name,
        _id=_id,
        component_type=Component.ComponentType.BOM,
        product=product,
        supplier_urls=["https://example.com/supplier"],
        metadata={"source": "e2e-fixture"},
    )

    component_author_factory(component, name="Alice Example", email="alice@example.com", order=0)
    component_author_factory(component, name="Bob Example", email="bob@example.com", order=1)

    component_license_factory(component, license_id="MIT", order=0)

    sbom = sbom_factory(component, name="simple-sbom.json", version="1.0.0")
    vulnerability_scan_factory(sbom, provider="osv")

    return component


@pytest.fixture
def document_component_details(component_factory, product_factory, document_factory):
    product = product_factory("Test Product")

    name = "Test Document Component"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    component = component_factory(
        name=name,
        _id=_id,
        component_type=Component.ComponentType.DOCUMENT,
        product=product,
        supplier_urls=["https://example.com/supplier"],
        metadata={"source": "e2e-fixture"},
    )

    document_factory(component, name="simple-document.pdf", version="1.0.0")

    return component
