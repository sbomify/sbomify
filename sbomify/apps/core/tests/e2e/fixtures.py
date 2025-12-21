from datetime import timedelta
from typing import Generator

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, ProductProject, Project, ProjectComponent
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.models import VulnerabilityScanResult


@pytest.fixture
def dashboard_products(team_with_business_plan) -> Generator[list[Product], None, None]:
    team = team_with_business_plan
    products = [Product.objects.create(name=f"Test Product {i}", team=team) for i in range(3)]
    yield products


@pytest.fixture
def dashboard_projects(dashboard_products, team_with_business_plan) -> Generator[list[Project], None, None]:
    team = team_with_business_plan
    projects = []

    for i, product in enumerate(dashboard_products):
        project = Project.objects.create(name=f"Test Project {i}", team=team)
        ProductProject.objects.create(product=product, project=project)
        projects.append(project)

    yield projects


@pytest.fixture
def dashboard_components(dashboard_projects, team_with_business_plan) -> Generator[list[Component], None, None]:
    team = team_with_business_plan
    components = []

    for i in range(7):
        component = Component.objects.create(
            name=f"Test Component {i}",
            team=team,
            component_type=Component.ComponentType.SBOM,
        )
        project = dashboard_projects[i % len(dashboard_projects)]
        ProjectComponent.objects.create(project=project, component=component)
        components.append(component)

    yield components


@pytest.fixture
def dashboard_sboms(dashboard_components) -> Generator[list[SBOM], None, None]:
    sboms = []
    for i, component in enumerate(dashboard_components):
        sbom = SBOM.objects.create(
            name=f"test-sbom-{i}.json",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            version=f"1.0.{i}",
            sbom_filename=f"test-sbom-{i}.json",
            source="test",
        )
        sboms.append(sbom)

    yield sboms


@pytest.fixture
def dashboard_scan_results(dashboard_sboms) -> Generator[list[VulnerabilityScanResult], None, None]:
    scan_results = []
    end_date = timezone.now()
    start_date = end_date - timedelta(days=29)
    providers = ["osv", "dependency_track"]

    for day_offset in range(30):
        scan_date = start_date + timedelta(days=day_offset)
        scans_per_day = 1 if day_offset % 2 == 0 else 2

        for scan_idx in range(scans_per_day):
            sbom = dashboard_sboms[scan_idx % len(dashboard_sboms)]
            provider = providers[scan_idx % len(providers)]

            base_count = 10 + (day_offset % 10)
            critical = max(1, base_count % 3)
            high = max(2, (base_count % 5) + 1)
            medium = max(3, (base_count % 7) + 2)
            low = max(1, (base_count % 4) + 1)
            total = critical + high + medium + low

            result = VulnerabilityScanResult.objects.create(
                sbom=sbom,
                provider=provider,
                scan_trigger="upload",
                vulnerability_count={
                    "total": total,
                    "critical": critical,
                    "high": high,
                    "medium": medium,
                    "low": low,
                },
                findings=[],
                scan_metadata={"provider": provider, "scan_type": "comprehensive"},
                total_vulnerabilities=total,
                critical_vulnerabilities=critical,
                high_vulnerabilities=high,
                medium_vulnerabilities=medium,
                low_vulnerabilities=low,
            )
            VulnerabilityScanResult.objects.filter(id=result.id).update(created_at=scan_date)
            result.refresh_from_db()
            scan_results.append(result)

    yield scan_results
