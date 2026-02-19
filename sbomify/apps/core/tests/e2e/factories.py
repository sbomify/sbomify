import datetime
from typing import Optional

import pytest

from sbomify.apps.core.models import Component, Product, ProductProject, Project, ProjectComponent
from sbomify.apps.core.utils import generate_id
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM, ComponentAuthor, ComponentLicense
from sbomify.apps.plugins.models import AssessmentRun


@pytest.fixture
def product_factory(team_with_business_plan):
    def _create(name: str = "Product", is_public: bool = True, _id: str | None = None) -> Product:
        return Product.objects.create(
            id=_id or generate_id(), name=name, team=team_with_business_plan, is_public=is_public
        )

    return _create


@pytest.fixture
def project_factory(team_with_business_plan):
    def _create(
        name: str = "Project", is_public: bool = True, product: Product | None = None, _id: str | None = None
    ) -> Project:
        proj = Project.objects.create(
            id=_id or generate_id(), name=name, team=team_with_business_plan, is_public=is_public
        )
        if product:
            # Link
            ProductProject.objects.create(product=product, project=proj)
        return proj

    return _create


@pytest.fixture
def component_factory(team_with_business_plan):
    def _create(
        name: str = "Component",
        component_type: str = Component.ComponentType.SBOM,
        project: Project | None = None,
        visibility: str | Component.Visibility = Component.Visibility.PRIVATE,
        is_global: bool = False,
        supplier_name: str | None = "Test Supplier",
        supplier_urls: list[str] | None = None,
        supplier_address: str | None = "123 Test Street, Test City",
        lifecycle_phase: str | None = "operations",
        metadata: dict | None = None,
        _id: str | None = None,
    ) -> Component:
        if not supplier_urls:
            supplier_urls = []

        if not metadata:
            metadata = {}

        # Convert string to enum if needed
        if isinstance(visibility, str):
            visibility = Component.Visibility(visibility)

        comp = Component.objects.create(
            id=_id or generate_id(),
            name=name,
            team=team_with_business_plan,
            component_type=component_type,
            visibility=visibility,
            is_global=is_global,
            supplier_name=supplier_name,
            supplier_url=supplier_urls,
            supplier_address=supplier_address,
            lifecycle_phase=lifecycle_phase,
            metadata=metadata,
        )
        if project:
            # Link
            ProjectComponent.objects.create(project=project, component=comp)
        return comp

    return _create


@pytest.fixture
def component_author_factory():
    def _create(
        component: Component,
        name: str = "Test Author",
        email: str | None = "author@example.com",
        phone: str | None = "+1-555-1234",
        order: int = 0,
        bom_ref: str | None = None,
    ) -> ComponentAuthor:
        return ComponentAuthor.objects.create(
            component=component,
            name=name,
            email=email,
            phone=phone,
            order=order,
            bom_ref=bom_ref,
        )

    return _create


@pytest.fixture
def component_license_factory():
    def _create_spdx(
        component: Component,
        license_id: str = "MIT",
        order: int = 0,
        bom_ref: str | None = None,
    ) -> ComponentLicense:
        return ComponentLicense.objects.create(
            component=component,
            license_type=ComponentLicense.LicenseType.SPDX,
            license_id=license_id,
            order=order,
            bom_ref=bom_ref,
        )

    return _create_spdx


@pytest.fixture
def document_factory():
    def _create(component: Component, name: str = "test-document.pdf", version: str = "1.0.0") -> Document:
        return Document.objects.create(
            name=name,
            component=component,
            version=version,
        )

    return _create


@pytest.fixture
def sbom_factory():
    def _create(component: Component, name: str = "test-sbom.json", version: str = "1.0.0") -> SBOM:
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
    def _create(
        sbom: SBOM,
        provider: str = "osv",
        created_at: Optional[datetime.datetime] = None,
        critical: int = 1,
        high: int = 2,
        medium: int = 3,
        low: int = 1,
    ) -> AssessmentRun:
        total = critical + high + medium + low
        run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name=provider,
            plugin_version="1.0.0",
            category="security",
            run_reason="on_upload",
            status="completed",
            result={
                "summary": {
                    "total_findings": total,
                    "by_severity": {
                        "critical": critical,
                        "high": high,
                        "medium": medium,
                        "low": low,
                    },
                },
                "findings": [],
            },
        )
        if created_at:
            AssessmentRun.objects.filter(id=run.id).update(created_at=created_at)
            run.refresh_from_db()
        return run

    return _create
