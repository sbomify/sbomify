# Fixtures for team related test cases

from typing import Any, Generator

import pytest
from django.db import transaction
from django.utils import timezone

from access_tokens.models import AccessToken
from access_tokens.utils import create_personal_access_token
from core.tests.fixtures import sample_user  # noqa: F401
from teams.fixtures import sample_team, sample_team_with_owner_member  # noqa: F401
from teams.models import Member, Team

from ..models import SBOM, Component, Product, ProductProject, Project, ProjectComponent
from ..schemas import SPDXSchema
from core.utils import generate_id
from sboms.models import (
    LicenseComponent,
    LicenseExpression,
    ProjectComponent,
    SBOM,
)
from sboms.schemas import (
    ComponentMetaData as ComponentMetaDataSchema,
    CustomLicenseSchema,
    LicenseSchema,
    SupplierSchema,
)
from sboms.license_utils import LicenseExpressionHandler

SAMPLE_SBOM_DATA = {
    "SPDXID": "SPDXRef-DOCUMENT",
    "spdxVersion": "SPDX-2.3",
    "creationInfo": {
        "created": "2024-06-06T07:48:34Z",
        "creators": ["Tool: GitHub.com-Dependency-Graph"],
    },
    "name": "com.github.test/test",
    "dataLicense": "CC0-1.0",
    "documentDescribes": ["SPDXRef-com.github.test-test"],
    "documentNamespace": "https://github.com/test/test/dependency_graph/sbom-9292e6160727aee2",
    "packages": [
        {
            "SPDXID": "SPDXRef-com.github.test-test",
            "name": "com.github.test/test",
            "versionInfo": "",
            "downloadLocation": "git+https://github.com/test/test",
            "filesAnalyzed": False,
            "supplier": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": "pkg:github/test/test",
                }
            ],
        },
        {
            "SPDXID": "SPDXRef-pip-requests-2.31.0",
            "name": "pip:requests",
            "versionInfo": "2.31.0",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "Apache-2.0",
            "supplier": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceLocator": "pkg:pypi/requests@2.31.0",
                    "referenceType": "purl",
                }
            ],
        },
    ],
    "relationships": [
        {
            "relationshipType": "DEPENDS_ON",
            "spdxElementId": "SPDXRef-com.github.test-test",
            "relatedSpdxElement": "SPDXRef-pip-requests-2.31.0",
        }
    ],
}


@pytest.fixture
def sample_product(
    sample_team_with_owner_member: Member,  # noqa: F811
) -> Generator[Product, Any, None]:
    product = Product(team_id=sample_team_with_owner_member.team_id, name="test product")
    product.save()

    yield product

    product.delete()


@pytest.fixture
def sample_project(
    sample_product: Product,  # noqa: F811
) -> Generator[Project, Any, None]:
    with transaction.atomic():
        project = Project(product=sample_product, name="test project", team_id=sample_product.team_id)
        project.save()

        product_project = ProductProject(product=sample_product, project=project)
        product_project.save()

    yield project

    with transaction.atomic():
        product_project.delete()
        project.delete()


@pytest.fixture
def sample_component(
    sample_project: Project,  # noqa: F811
) -> Generator[Component, Any, None]:
    with transaction.atomic():
        component = Component(project=sample_project, name="test component", team_id=sample_project.team_id)
        component.save()

        project_component = ProjectComponent(project=sample_project, component=component)
        project_component.save()

    yield component

    with transaction.atomic():
        project_component.delete()
        component.delete()


@pytest.fixture
def sample_sbom(
    sample_component: Component,
    spdx_payload: dict,
    package: dict,
) -> Generator[SBOM, None, None]:
    """Create a sample SBOM for testing."""
    sbom = SBOM(
        name=spdx_payload["name"],
        version=package.get("versionInfo", ""),
        format="spdx",
        sbom_filename="test-sbom.json",
        component=sample_component,
        source="test",
        format_version=spdx_payload["spdxVersion"].removeprefix("SPDX-"),
    )
    sbom.save()

    # Create license expression if package has a license
    if package.get("license"):
        handler = LicenseExpressionHandler()
        try:
            # Parse and validate the license expression
            parsed = handler.parse_expression(package["license"])
            is_valid, warnings = handler.validate_expression(package["license"])
            validation_status = "warning" if warnings else "valid" if is_valid else "invalid"

            # Create the license expression tree
            def _create_node(parsed_node, parent=None, order=0) -> LicenseExpression:
                # Handle WITH nodes
                if hasattr(parsed_node, "license_symbol") and hasattr(parsed_node, "exception_symbol"):
                    operator = "WITH"
                    node = LicenseExpression.objects.create(
                        parent=parent,
                        order=order,
                        operator=operator,
                        component=None,
                        expression=str(parsed_node),
                        normalized_expression=str(parsed_node),
                        source="spdx",
                        validation_status=validation_status,
                        validation_errors=warnings,
                    )
                    # Create license component
                    license_component = LicenseComponent.objects.create(
                        identifier=str(parsed_node.license_symbol),
                        name=str(parsed_node.license_symbol),
                        type="spdx",
                    )
                    _create_node(parsed_node.license_symbol, parent=node, order=0)
                    # Create exception component
                    exception_component = LicenseComponent.objects.create(
                        identifier=str(parsed_node.exception_symbol),
                        name=str(parsed_node.exception_symbol),
                        type="spdx",
                    )
                    LicenseExpression.objects.create(
                        parent=node,
                        order=1,
                        component=exception_component,
                        operator=None,
                        expression=str(parsed_node.exception_symbol),
                        normalized_expression=str(parsed_node.exception_symbol),
                        source="spdx",
                        validation_status=validation_status,
                        validation_errors=warnings,
                    )
                    return node

                # Handle leaf nodes (simple licenses)
                if not hasattr(parsed_node, "operator"):
                    component = LicenseComponent.objects.create(
                        identifier=str(parsed_node),
                        name=str(parsed_node),
                        type="spdx",
                    )
                    return LicenseExpression.objects.create(
                        parent=parent,
                        order=order,
                        component=component,
                        operator=None,
                        expression=str(parsed_node),
                        normalized_expression=str(parsed_node),
                        source="spdx",
                        validation_status=validation_status,
                        validation_errors=warnings,
                    )

                # Handle operator nodes (AND, OR)
                op = getattr(parsed_node, "operator", None)
                operator = op.strip() if isinstance(op, str) and op else None
                node = LicenseExpression.objects.create(
                    parent=parent,
                    order=order,
                    operator=operator,
                    component=None,
                    expression=str(parsed_node),
                    normalized_expression=str(parsed_node),
                    source="spdx",
                    validation_status=validation_status,
                    validation_errors=warnings,
                )
                # Create child nodes
                for idx, child in enumerate(getattr(parsed_node, "args", [])):
                    _create_node(child, parent=node, order=idx)
                return node

            # Create the root node
            root = _create_node(parsed)
            sbom.license_expression = root

        except Exception as e:
            # If parsing fails, create a simple invalid expression
            component = LicenseComponent.objects.create(
                identifier=package["license"],
                name=package["license"],
                type="custom",
            )
            root = LicenseExpression.objects.create(
                component=component,
                operator=None,
                expression=package["license"],
                normalized_expression=package["license"],
                source="spdx",
                validation_status="invalid",
                validation_errors=[str(e)],
            )
            sbom.license_expression = root

    yield sbom


@pytest.fixture
def sample_access_token(
    sample_team_with_owner_member: Member,  # noqa: F811
) -> Generator[AccessToken, Any, None]:
    user = sample_team_with_owner_member.user
    token_str = create_personal_access_token(user)
    access_token: AccessToken = AccessToken(user=user, encoded_token=token_str)
    access_token.save()

    yield access_token

    access_token.delete()


@pytest.fixture
def spdx_payload() -> dict:
    """Fixture for a sample SPDX payload."""
    return SAMPLE_SBOM_DATA


@pytest.fixture
def package() -> dict:
    """Fixture for a sample SPDX package."""
    return SAMPLE_SBOM_DATA["packages"][0]
