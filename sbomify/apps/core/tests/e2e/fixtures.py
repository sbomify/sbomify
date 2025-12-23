from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest

from sbomify.apps.core.models import Component, Product, ProductProject, Project, ProjectComponent, Release
from sbomify.apps.sboms.models import SBOM, ProductIdentifier, ProductLink
from sbomify.apps.vulnerability_scanning.models import VulnerabilityScanResult

START_DATE = datetime(2025, 12, 1, tzinfo=timezone.utc)


@pytest.fixture
def product_factory(team_with_business_plan):
    def _create(name="Product", is_public=True):
        return Product.objects.create(name=name, team=team_with_business_plan, is_public=is_public)

    return _create


@pytest.fixture
def project_factory(team_with_business_plan):
    def _create(name="Project", is_public=True, product=None):
        proj = Project.objects.create(name=name, team=team_with_business_plan, is_public=is_public)
        if product:
            ProductProject.objects.create(product=product, project=proj)
        return proj

    return _create


@pytest.fixture
def component_factory(team_with_business_plan):
    def _create(name="Component", component_type=Component.ComponentType.SBOM, project=None):
        comp = Component.objects.create(name=name, team=team_with_business_plan, component_type=component_type)
        if project:
            ProjectComponent.objects.create(project=project, component=comp)
        return comp

    return _create


@pytest.fixture
def sbom_factory():
    def _create(component, name="test-sbom.json", version="1.0.0"):
        return SBOM.objects.create(
            name=name,
            component=component,
            format="cyclonedx",
            format_version="1.5",
            version=version,
            sbom_filename=name,
            source="test",
        )

    return _create


@pytest.fixture
def vulnerability_scan_factory():
    def _create(sbom, provider="osv", scan_date=None, critical=1, high=2, medium=3, low=1):
        total = critical + high + medium + low
        result = VulnerabilityScanResult.objects.create(
            sbom=sbom,
            provider=provider,
            scan_trigger="upload",
            vulnerability_count={"total": total, "critical": critical, "high": high, "medium": medium, "low": low},
            findings=[],
            scan_metadata={"provider": provider, "scan_type": "comprehensive"},
            total_vulnerabilities=total,
            critical_vulnerabilities=critical,
            high_vulnerabilities=high,
            medium_vulnerabilities=medium,
            low_vulnerabilities=low,
        )
        if scan_date:
            VulnerabilityScanResult.objects.filter(id=result.id).update(created_at=scan_date)
            result.refresh_from_db()
        return result

    return _create


@pytest.fixture
def simple_product(product_factory):
    return product_factory("Simple Product")


@pytest.fixture
def simple_project(project_factory, simple_product):
    return project_factory("Simple Project", product=simple_product)


@pytest.fixture
def simple_component(component_factory, simple_project):
    return component_factory("Simple SBOM Component", Component.ComponentType.SBOM, project=simple_project)


@pytest.fixture
def simple_sbom(sbom_factory, simple_component):
    return sbom_factory(simple_component)


@pytest.fixture
def simple_scan(vulnerability_scan_factory, simple_sbom):
    return vulnerability_scan_factory(simple_sbom)


@pytest.fixture
def dashboard_products(product_factory) -> Generator[list[Product], None, None]:
    products = [product_factory(f"Test Product {i}", is_public=(i % 2 == 0)) for i in range(5)]
    yield products


@pytest.fixture
def dashboard_projects(dashboard_products, project_factory) -> Generator[list[Project], None, None]:
    projects = []

    # Product 0: 2 projects
    for i in range(2):
        projects.append(
            project_factory(f"Product 0 Project {i}", is_public=(i % 2 == 0), product=dashboard_products[0])
        )

    # Product 1: 1 project
    projects.append(project_factory("Product 1 Project", is_public=False, product=dashboard_products[1]))

    # Product 2: 3 projects
    for i in range(3):
        projects.append(
            project_factory(f"Product 2 Project {i}", is_public=(i % 2 == 0), product=dashboard_products[2])
        )

    # Products 3 and 4: No projects

    yield projects


@pytest.fixture
def dashboard_components(dashboard_projects, component_factory) -> Generator[list[Component], None, None]:
    components = []

    # Project 0: 2 SBOM components
    for i in range(2):
        components.append(
            component_factory(f"SBOM Component {i}", Component.ComponentType.SBOM, project=dashboard_projects[0])
        )

    # Project 1: 1 SBOM + 1 Document
    components.append(
        component_factory("Private SBOM Component", Component.ComponentType.SBOM, project=dashboard_projects[1])
    )
    components.append(
        component_factory("Private Document Component", Component.ComponentType.DOCUMENT, project=dashboard_projects[1])
    )

    # Project 4: 4 components (mix)
    for i in range(4):
        ctype = Component.ComponentType.SBOM if i % 2 == 0 else Component.ComponentType.DOCUMENT
        components.append(component_factory(f"Large Project Component {i}", ctype, project=dashboard_projects[4]))

    # Projects 2 and 3: no components

    yield components


@pytest.fixture
def dashboard_sboms(dashboard_components, sbom_factory) -> Generator[list[SBOM], None, None]:
    sboms = [
        sbom_factory(c, name=f"sbom-{i}.json", version=f"1.0.{i}")
        for i, c in enumerate(dashboard_components)
        if c.component_type == Component.ComponentType.SBOM
    ]
    yield sboms


@pytest.fixture
def dashboard_scan_results(
    dashboard_sboms, vulnerability_scan_factory
) -> Generator[list[VulnerabilityScanResult], None, None]:
    scan_results = []
    start_date = START_DATE - timedelta(days=29)
    providers = ["osv", "dependency_track"]

    for day_offset in range(30):
        scan_date = start_date + timedelta(days=day_offset)
        scans_per_day = 1 if day_offset % 2 == 0 else 2

        for scan_idx in range(scans_per_day):
            sbom = dashboard_sboms[scan_idx % len(dashboard_sboms)]
            provider = providers[scan_idx % len(providers)]
            result = vulnerability_scan_factory(sbom, provider=provider, scan_date=scan_date)
            scan_results.append(result)

    yield scan_results


@pytest.fixture
def product_details(product_factory, project_factory) -> Generator[Product, None, None]:
    product = product_factory("Test Product Details")

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


@pytest.fixture
def empty_product_details(product_factory) -> Generator[Product, None, None]:
    yield product_factory("Empty Product")


@pytest.fixture
def project_details(project_factory, component_factory, sbom_factory) -> Generator[Project, None, None]:
    project = project_factory("Test Project Details", is_public=True)

    sbom_component = component_factory(
        "Project SBOM Component",
        Component.ComponentType.SBOM,
        project=project,
    )
    # Extra SBOM component linked to the same project to increase variety
    extra_sbom_component = component_factory(
        "Extra Project SBOM Component",
        Component.ComponentType.SBOM,
        project=project,
    )
    component_factory(
        "Project Document Component",
        Component.ComponentType.DOCUMENT,
        project=project,
    )

    sbom_factory(sbom_component, name="project-sbom.json", version="1.0.0")
    sbom_factory(extra_sbom_component, name="project-sbom-extra.json", version="1.0.1")

    yield project


@pytest.fixture
def empty_project_details(project_factory) -> Generator[Project, None, None]:
    yield project_factory("Empty Project", is_public=True)
