# Fixtures for team related test cases

from datetime import datetime, timezone
from typing import Any, Generator
from uuid import uuid4

import pytest
from django.db import transaction

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.teams.fixtures import sample_team, sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member

from ..models import SBOM, Component, Product, ProductProject, Project, ProjectComponent
from ..schemas import SPDXSchema


# =============================================================================
# SPDX Test Data Builder
# =============================================================================
#
# NOTE: This module currently supports SPDX 2.x only.
# SPDX 3.0 introduces a fundamentally different structure based on linked data
# (JSON-LD) with separate Element, Artifact, Package, and Relationship objects.
# When adding SPDX 3.0 support:
# - Create separate create_spdx3_test_sbom() function
# - SPDX 3.0 uses "@context", "@type", "spdxId" instead of "SPDXID"
# - Relationships are first-class objects with "from", "to", "relationshipType"
# - Supplier becomes "suppliedBy" relationship to Agent/Organization
# - See: https://spdx.github.io/spdx-spec/v3.0/
# =============================================================================


def create_spdx_test_sbom(
    # Package metadata
    supplier: str | None = "Organization: Test Corp",
    package_name: str = "test-package",
    version: str = "1.0.0",
    purl: str | None = None,
    checksums: list[dict] | None = None,
    license_concluded: str | None = "MIT",
    license_declared: str | None = None,
    valid_until_date: str | None = None,
    package_annotations: list[dict] | None = None,
    # Document metadata
    creators: list[str] | None = None,
    timestamp: str | None = None,
    generation_context: str | None = None,
    document_comment: str | None = None,
    document_annotations: list[dict] | None = None,
    # Structure
    with_relationships: bool = True,
    spdx_version: str = "SPDX-2.3",
    additional_packages: list[dict] | None = None,
) -> dict:
    """Generate complete SPDX 2.x SBOM test data with all configurable fields.

    This builder creates SPDX 2.x compliant SBOMs for testing plugin validation.
    All fields are configurable to test both passing and failing scenarios.

    NOTE: This function only supports SPDX 2.x. For SPDX 3.0 support (when added),
    use create_spdx3_test_sbom() which will handle the different linked data model.

    Args:
        supplier: Package supplier (format: "Organization: Name" or "Person: Name").
                  Set to None to omit for failure testing.
        package_name: Name of the main package.
        version: Package version string.
        purl: Package URL. Auto-generated from package_name and version if None.
        checksums: List of checksum dicts, e.g., [{"algorithm": "SHA256", "checksumValue": "abc123"}].
        license_concluded: SPDX license ID or expression.
        license_declared: SPDX license ID or expression (alternative to concluded).
        valid_until_date: ISO-8601 date for end of support (FDA/CRA requirement).
        package_annotations: Package-level annotations for support status, etc.
        creators: List of creator strings, e.g., ["Tool: sbomify (1.0)", "Person: Dev"].
        timestamp: ISO-8601 timestamp. Auto-generated if None.
        generation_context: Lifecycle phase (e.g., "build", "pre-build", "post-build").
        document_comment: Document-level comment.
        document_annotations: Document-level annotations for generation context, etc.
        with_relationships: Whether to include dependency relationships.
        spdx_version: SPDX 2.x version string (default "SPDX-2.3"). Supported: 2.2, 2.3.
        additional_packages: Extra packages to include in the SBOM.

    Returns:
        Complete SPDX 2.x SBOM dictionary ready for validation.

    Raises:
        ValueError: If spdx_version is not a supported SPDX 2.x version.
    """
    # Validate SPDX version - only 2.x supported by this function
    if not spdx_version.startswith("SPDX-2."):
        raise ValueError(
            f"Unsupported SPDX version: {spdx_version}. "
            "This function only supports SPDX 2.x (e.g., 'SPDX-2.3'). "
            "For SPDX 3.0, use create_spdx3_test_sbom() when available."
        )
    # Generate defaults
    if purl is None:
        purl = f"pkg:generic/{package_name}@{version}"

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if creators is None:
        creators = ["Tool: sbomify-test (1.0.0)"]

    doc_namespace = f"https://sbomify.com/spdx/{uuid4()}"
    package_spdxid = f"SPDXRef-Package-{package_name.replace('/', '-').replace('@', '-')}"

    # Build main package
    main_package: dict[str, Any] = {
        "SPDXID": package_spdxid,
        "name": package_name,
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ],
    }

    # Add optional package fields
    if supplier is not None:
        main_package["supplier"] = supplier

    if checksums is not None:
        main_package["checksums"] = checksums

    if license_concluded is not None:
        main_package["licenseConcluded"] = license_concluded

    if license_declared is not None:
        main_package["licenseDeclared"] = license_declared

    if valid_until_date is not None:
        main_package["validUntilDate"] = valid_until_date

    if package_annotations is not None:
        main_package["annotations"] = package_annotations

    # Build packages list
    packages = [main_package]
    if additional_packages:
        packages.extend(additional_packages)

    # Build creation info
    creation_info: dict[str, Any] = {
        "created": timestamp,
        "creators": creators,
    }

    if generation_context is not None:
        creation_info["comment"] = f"Generation context: {generation_context}"

    # Build document
    sbom: dict[str, Any] = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "spdxVersion": spdx_version,
        "creationInfo": creation_info,
        "name": f"SBOM for {package_name}",
        "dataLicense": "CC0-1.0",
        "documentNamespace": doc_namespace,
        "documentDescribes": [package_spdxid],
        "packages": packages,
    }

    # Add optional document fields
    if document_comment is not None:
        sbom["comment"] = document_comment

    if document_annotations is not None:
        sbom["annotations"] = document_annotations

    # Add relationships
    if with_relationships:
        sbom["relationships"] = [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": package_spdxid,
            }
        ]

        # Add DEPENDS_ON relationships for additional packages
        if additional_packages:
            for pkg in additional_packages:
                sbom["relationships"].append(
                    {
                        "spdxElementId": package_spdxid,
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": pkg["SPDXID"],
                    }
                )

    return sbom


def create_spdx_dependency_package(
    package_name: str,
    version: str = "1.0.0",
    supplier: str | None = "Organization: Dependency Corp",
    license_concluded: str | None = "Apache-2.0",
    checksums: list[dict] | None = None,
) -> dict:
    """Create a dependency package for use with create_spdx_test_sbom().

    Args:
        package_name: Name of the dependency package.
        version: Package version.
        supplier: Package supplier.
        license_concluded: License ID.
        checksums: Optional checksums.

    Returns:
        Package dictionary for use in additional_packages parameter.
    """
    purl = f"pkg:generic/{package_name}@{version}"
    package_spdxid = f"SPDXRef-Package-{package_name.replace('/', '-').replace('@', '-')}"

    package: dict[str, Any] = {
        "SPDXID": package_spdxid,
        "name": package_name,
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ],
    }

    if supplier is not None:
        package["supplier"] = supplier

    if license_concluded is not None:
        package["licenseConcluded"] = license_concluded

    if checksums is not None:
        package["checksums"] = checksums

    return package


def contact_entity_to_spdx_supplier(entity) -> str:
    """Convert ContactEntity to SPDX supplier format.

    Args:
        entity: ContactEntity with name field, or None.

    Returns:
        "Organization: <name>" format string, or "NOASSERTION" if no entity/name.
    """
    if entity and getattr(entity, "name", None):
        return f"Organization: {entity.name}"
    return "NOASSERTION"


# =============================================================================
# SPDX Pytest Fixtures
# =============================================================================


@pytest.fixture
def spdx_sbom_ntia_compliant() -> dict:
    """SPDX SBOM meeting NTIA minimum elements.

    Includes: supplier, name, version, identifiers, relationships, author, timestamp.
    """
    return create_spdx_test_sbom(
        supplier="Organization: NTIA Test Supplier",
        package_name="ntia-compliant-package",
        version="1.0.0",
        creators=["Tool: sbomify (1.0.0)", "Person: Test Author"],
        with_relationships=True,
        additional_packages=[
            create_spdx_dependency_package("dependency-lib", "2.0.0"),
        ],
    )


@pytest.fixture
def spdx_sbom_cisa_compliant() -> dict:
    """SPDX SBOM meeting CISA 2025 requirements.

    Includes all NTIA elements plus: checksums, licenses, tool name, generation context.
    """
    return create_spdx_test_sbom(
        supplier="Organization: CISA Test Supplier",
        package_name="cisa-compliant-package",
        version="1.0.0",
        checksums=[{"algorithm": "SHA256", "checksumValue": "abc123def456789"}],
        license_concluded="MIT",
        creators=["Tool: sbomify (1.0.0)", "Person: Test Author"],
        generation_context="build",
        with_relationships=True,
        additional_packages=[
            create_spdx_dependency_package(
                "dependency-lib",
                "2.0.0",
                checksums=[{"algorithm": "SHA256", "checksumValue": "def456abc123789"}],
            ),
        ],
    )


@pytest.fixture
def spdx_sbom_fda_compliant() -> dict:
    """SPDX SBOM meeting FDA Medical Device Cybersecurity requirements.

    Includes all NTIA elements plus: validUntilDate, support status annotations.
    """
    return create_spdx_test_sbom(
        supplier="Organization: FDA Test Supplier",
        package_name="fda-compliant-package",
        version="1.0.0",
        valid_until_date="2026-12-31",
        package_annotations=[
            {
                "annotationType": "OTHER",
                "annotator": "Tool: sbomify",
                "annotationDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "comment": "supportStatus=active",
            }
        ],
        creators=["Tool: sbomify (1.0.0)", "Person: Test Author"],
        with_relationships=True,
    )


@pytest.fixture
def spdx_sbom_cra_compliant() -> dict:
    """SPDX SBOM meeting EU Cyber Resilience Act requirements.

    Includes: supplier, name, version, identifiers, dependencies, author, timestamp,
    vulnerability contact, support period.
    """
    return create_spdx_test_sbom(
        supplier="Organization: CRA Test Supplier",
        package_name="cra-compliant-package",
        version="1.0.0",
        valid_until_date="2026-12-31",
        creators=[
            "Tool: sbomify (1.0.0)",
            "Person: Test Author (security@example.com)",
        ],
        with_relationships=True,
        additional_packages=[
            create_spdx_dependency_package("dependency-lib", "2.0.0"),
        ],
    )


@pytest.fixture
def spdx_sbom_minimal() -> dict:
    """Minimal SPDX SBOM for failure testing.

    Missing most optional fields to test plugin failure detection.
    """
    return create_spdx_test_sbom(
        supplier=None,
        package_name="minimal-package",
        version="1.0.0",
        checksums=None,
        license_concluded=None,
        creators=["Person: Unknown"],  # No Tool: entry
        with_relationships=False,
    )

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
        key="test_plan",
        name="Test Plan",
        description="Test Plan Description",
        max_products=10,
        max_projects=10,
        max_components=10
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
