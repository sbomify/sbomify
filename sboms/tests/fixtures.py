# Fixtures for team related test cases

from typing import Any, Generator

import pytest
from django.db import transaction

from access_tokens.models import AccessToken
from access_tokens.utils import create_personal_access_token
from billing.models import BillingPlan
from core.tests.fixtures import sample_user  # noqa: F401
from teams.fixtures import sample_team, sample_team_with_owner_member  # noqa: F401
from teams.models import Member

from ..models import SBOM, Component, Product, ProductProject, Project, ProjectComponent
from ..schemas import SPDXSchema

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
def sample_billing_plan() -> Generator[BillingPlan, Any, None]:
    """Create a test billing plan with reasonable limits."""
    plan = BillingPlan.objects.create(
        key="test_plan", name="Test Plan", max_products=10, max_projects=10, max_components=10
    )

    yield plan

    plan.delete()


@pytest.fixture
def sample_product(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_billing_plan: BillingPlan,  # noqa: F811
) -> Generator[Product, Any, None]:
    # Set up billing plan for the team
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()

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
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
) -> Generator[SBOM, Any, None]:
    spdx_paylaod = SPDXSchema(**SAMPLE_SBOM_DATA)
    package = spdx_paylaod.packages[0]

    sbom = SBOM(
        name=spdx_paylaod.name,
        version=package.version,
        format="spdx",
        sbom_filename="test-sbom.json",
        component=sample_component,
        source="test",
        format_version=spdx_paylaod.spdx_version.removeprefix("SPDX-"),
    )

    sbom.save()

    yield sbom

    sbom.delete()


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
