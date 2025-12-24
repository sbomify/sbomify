import hashlib
from datetime import timedelta
from typing import Generator

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, Project, Release
from sbomify.apps.core.tests.e2e.factories import *  # noqa: F403
from sbomify.apps.sboms.models import ProductIdentifier, ProductLink


@pytest.fixture
def dashboard(
    product_factory,
    project_factory,
    component_factory,
    sbom_factory,
    vulnerability_scan_factory,
) -> Generator[dict[str, list], None, None]:
    data = {}

    # -----------------------
    # Products
    # -----------------------
    products = [product_factory(f"Test Product {i}", is_public=(i % 2 == 0)) for i in range(5)]
    data["products"] = products

    # -----------------------
    # Projects
    # -----------------------
    projects = []
    # Product 0: 2 projects
    projects.extend(
        [project_factory(f"Product 0 Project {i}", is_public=(i % 2 == 0), product=products[0]) for i in range(2)]
    )
    # Product 1: 1 project
    projects.append(project_factory("Product 1 Project", is_public=False, product=products[1]))
    # Product 2: 3 projects
    projects.extend(
        [project_factory(f"Product 2 Project {i}", is_public=(i % 2 == 0), product=products[2]) for i in range(3)]
    )
    # Products 3 and 4: no projects
    data["projects"] = projects

    # -----------------------
    # Components
    # -----------------------
    components = []

    # Project 0: 2 SBOM components
    for i in range(2):
        args = {"project": projects[0], "is_public": True} if i % 2 == 0 else {}
        components.append(component_factory(f"SBOM Component {i}", Component.ComponentType.SBOM, **args))

    # Project 1: 1 SBOM + 1 Document
    sbom_comp = component_factory("Private SBOM Component", Component.ComponentType.SBOM, project=projects[1])
    sbom_factory(sbom_comp, name="private-sbom.json", version="1.0.0")
    components.append(sbom_comp)
    components.append(
        component_factory("Private Document Component", Component.ComponentType.DOCUMENT, project=projects[1])
    )

    # Project 4: 4 components (mixed types)
    for i in range(4):
        args = {"project": projects[4]}
        if i % 2 == 0:
            args.update({"project": None, "is_public": True})
        if i % 3 == 0:
            args.update({"is_global": True})
        components.append(component_factory(f"Large Project Component {i}", **args))

    data["components"] = components

    # -----------------------
    # SBOMs for components
    # -----------------------
    sboms = [
        sbom_factory(c, name=f"sbom-{i}.json", version=f"1.0.{i}")
        for i, c in enumerate(components)
        if c.component_type == Component.ComponentType.SBOM
    ]
    data["sboms"] = sboms

    # -----------------------
    # Vulnerability Scan Results
    # -----------------------
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


# -----------------------
# Test Products
# -----------------------
@pytest.fixture
def empty_product_details(product_factory) -> Generator[Product, None, None]:
    name = "Empty Product"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    yield product_factory(name=name, _id=_id)


@pytest.fixture
def product_details(product_factory, project_factory) -> Generator[Product, None, None]:
    name = "Test Product Details"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    product = product_factory(name=name, _id=_id)

    project_factory("Project 1", is_public=True, product=product)
    project_factory("Project 2", is_public=False, product=product)
    project_factory("Project 3", is_public=True)  # Not linked

    # Product Identifiers
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

    # Product Links
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

    # Releases
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


# -----------------------
# Test Projects
# -----------------------
@pytest.fixture
def empty_project_details(project_factory) -> Generator[Project, None, None]:
    name = "Empty Project"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    yield project_factory(name=name, _id=_id, is_public=True)


@pytest.fixture
def project_details(project_factory, component_factory, sbom_factory) -> Generator[Project, None, None]:
    name = "Test Project Details"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    project = project_factory(name=name, _id=_id, is_public=True)

    project_sbom_component = component_factory(
        "Project SBOM Component",
        Component.ComponentType.SBOM,
        project=project,
    )
    sbom_factory(project_sbom_component, name="project-sbom.json", version="1.0.0")

    component_factory(
        "Project Document Component",
        Component.ComponentType.DOCUMENT,
        project=project,
        is_public=True,
    )

    sbom_component = component_factory(
        "SBOM Component",
        Component.ComponentType.SBOM,
        is_public=True,
    )
    sbom_factory(sbom_component, name="sbom.json", version="1.0.1")

    component_factory(
        "Document Component",
        Component.ComponentType.DOCUMENT,
    )

    yield project


# -----------------------
# Test Components
# -----------------------
@pytest.fixture
def sbom_component_details(
    component_factory,
    project_factory,
    product_factory,
    component_author_factory,
    component_license_factory,
    vulnerability_scan_factory,
    sbom_factory,
):
    project = project_factory("Test Project", product=product_factory("Test Product"))

    name = "Test SBOM Component"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    component = component_factory(
        name=name,
        _id=_id,
        component_type=Component.ComponentType.SBOM,
        project=project,
        supplier_urls=["https://example.com/supplier"],
        metadata={"source": "e2e-fixture"},
    )

    # Attach a couple of authors
    component_author_factory(component, name="Alice Example", email="alice@example.com", order=0)
    component_author_factory(component, name="Bob Example", email="bob@example.com", order=1)

    # Attach an SPDX license
    component_license_factory(component, license_id="MIT", order=0)

    # Attach a SBOM and one vulnerability scan
    sbom = sbom_factory(component, name="simple-sbom.json", version="1.0.0")
    vulnerability_scan_factory(sbom, provider="osv")

    return component


@pytest.fixture
def document_component_details(component_factory, project_factory, product_factory, document_factory):
    project = project_factory("Test Project", product=product_factory("Test Product"))

    name = "Test Document Component"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    component = component_factory(
        name=name,
        _id=_id,
        component_type=Component.ComponentType.DOCUMENT,
        project=project,
        supplier_urls=["https://example.com/supplier"],
        metadata={"source": "e2e-fixture"},
    )

    document_factory(component, name="simple-document.pdf", version="1.0.0")

    return component


# -----------------------
# Test Releases
# -----------------------
@pytest.fixture
def product_with_releases(product_factory, release_factory) -> Generator[Product, None, None]:
    name = "Product With Releases"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    product = product_factory(name=name, _id=_id, is_public=True)

    release_factory(product, name="v1.0.0", description="Initial release", is_latest=False, is_prerelease=False)
    release_factory(product, name="v1.1.0", description="Minor update", is_latest=True, is_prerelease=False)
    release_factory(product, name="v2.0.0-beta", description="Beta release", is_latest=False, is_prerelease=True)

    yield product


@pytest.fixture
def empty_release_details(product_factory, release_factory) -> Generator[Release, None, None]:
    product = product_factory(name="Test Product", is_public=True)
    name = "v1.0.0"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    release = release_factory(product=product, name=name, _id=_id)
    yield release


@pytest.fixture
def release_details(
    product_factory,
    release_factory,
    component_factory,
    sbom_factory,
    document_factory,
    release_artifact_factory,
) -> Generator[Release, None, None]:
    product = product_factory(name="Test Product", is_public=True)

    name = "v1.0.0"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    release = release_factory(
        product=product,
        name=name,
        _id=_id,
        description="Test release description",
        is_latest=False,
        is_prerelease=False,
    )

    # Create SBOM component and SBOM
    sbom_component = component_factory(
        name="Release SBOM Component",
        component_type=Component.ComponentType.SBOM,
        is_public=True,
    )
    sbom = sbom_factory(sbom_component, name="release-sbom.json", version="1.0.0")
    release_artifact_factory(release, sbom=sbom)

    # Create Document component and Document
    document_component = component_factory(
        name="Release Document Component",
        component_type=Component.ComponentType.DOCUMENT,
        is_public=True,
    )
    document = document_factory(document_component, name="release-document.pdf", version="1.0.0")
    release_artifact_factory(release, document=document)

    yield release
