"""Tests for Release model functionality and signal handlers."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_product,
    sample_sbom,
)


@pytest.fixture
def sample_component(sample_product: Product):  # noqa: F811
    """Create a sample component for testing."""
    from sbomify.apps.sboms.models import Project

    # Create a project for the component
    project = Project.objects.create(
        name="test project release",
        team=sample_product.team
    )

    # Create the component with the project
    component = Component.objects.create(
        name="test component",
        team=sample_product.team
    )

    # Link project to component
    component.projects.add(project)

    # Link project to product
    sample_product.projects.add(project)

    return component


@pytest.fixture
def sample_document(sample_component: Component):
    """Create a sample document for testing."""
    return Document.objects.create(
        name="Test Document",
        version="1.0",
        document_filename="test_file.pdf",
        component=sample_component,
        source="manual_upload",
        content_type="application/pdf",
        file_size=1024,
        document_type="license",
    )


# =============================================================================
# RELEASE MODEL TESTS
# =============================================================================


@pytest.mark.django_db
def test_release_creation(sample_product: Product):  # noqa: F811
    """Test basic release creation."""
    release = Release.objects.create(
        product=sample_product,
        name="v1.0.0"
    )

    assert release.name == "v1.0.0"
    assert release.product == sample_product
    assert release.is_latest is False
    assert release.created_at is not None


@pytest.mark.django_db
def test_release_unique_constraint(sample_product: Product):  # noqa: F811
    """Test that release names must be unique per product."""
    Release.objects.create(product=sample_product, name="v1.0.0")

    from django.db import transaction
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            Release.objects.create(product=sample_product, name="v1.0.0")


@pytest.mark.django_db
def test_release_same_name_different_products(
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
):
    """Test that releases can have same name in different products."""
    # Create second product
    product2 = Product.objects.create(
        name="Product 2",
        team=sample_team_with_owner_member.team
    )

    # Create releases with same name in different products
    release1 = Release.objects.create(product=sample_product, name="v1.0.0")
    release2 = Release.objects.create(product=product2, name="v1.0.0")

    assert release1.name == release2.name
    assert release1.product != release2.product


@pytest.mark.django_db
def test_single_latest_release_per_product(sample_product: Product):  # noqa: F811
    """Test that only one release per product can be marked as latest."""
    release1 = Release.objects.create(  # noqa: F841
        product=sample_product,
        name="v1.0.0",
        is_latest=True
    )

    # Creating another latest release should fail
    with pytest.raises(ValidationError):
        release2 = Release(
            product=sample_product,
            name="v2.0.0",
            is_latest=True
        )
        release2.full_clean()


@pytest.mark.django_db
def test_get_or_create_latest_release(sample_product: Product):  # noqa: F811
    """Test get_or_create_latest_release class method."""
    # First call should create the latest release
    release1 = Release.get_or_create_latest_release(sample_product)

    assert release1.name == "latest"
    assert release1.is_latest is True
    assert release1.product == sample_product

    # Second call should return existing latest release
    release2 = Release.get_or_create_latest_release(sample_product)

    assert release1.id == release2.id


@pytest.mark.django_db
def test_get_artifacts_method(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_document: Document,  # noqa: F811
):
    """Test the get_artifacts method returns both SBOMs and Documents."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up artifacts
    sample_sbom.component = sample_component
    sample_sbom.save()
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Add artifacts to release
    ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)
    ReleaseArtifact.objects.create(release=release, document=sample_document)

    artifacts = release.get_artifacts()

    assert len(artifacts) == 2
    assert sample_sbom in [a.sbom for a in artifacts if a.sbom]
    assert sample_document in [a.document for a in artifacts if a.document]


@pytest.mark.django_db
def test_get_sboms_method(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_document: Document,  # noqa: F811
):
    """Test the get_sboms method returns only SBOMs."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up artifacts
    sample_sbom.component = sample_component
    sample_sbom.save()
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Add artifacts to release
    ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)
    ReleaseArtifact.objects.create(release=release, document=sample_document)

    sboms = release.get_sboms()

    assert len(sboms) == 1
    assert sample_sbom in sboms


@pytest.mark.django_db
def test_get_documents_method(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_document: Document,  # noqa: F811
):
    """Test the get_documents method returns only Documents."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up artifacts
    sample_sbom.component = sample_component
    sample_sbom.save()
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Add artifacts to release
    ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)
    ReleaseArtifact.objects.create(release=release, document=sample_document)

    documents = release.get_documents()

    assert len(documents) == 1
    assert sample_document in documents


@pytest.mark.django_db
def test_add_sbom_method(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
):
    """Test the add_sbom method."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up SBOM
    sample_sbom.component = sample_component
    sample_sbom.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Add SBOM to release
    release.add_sbom(sample_sbom)

    # Verify artifact was added
    assert ReleaseArtifact.objects.filter(
        release=release,
        sbom=sample_sbom
    ).exists()


@pytest.mark.django_db
def test_add_document_method(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_document: Document,  # noqa: F811
):
    """Test the add_document method."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up document
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Add document to release
    release.add_document(sample_document)

    # Verify artifact was added
    assert ReleaseArtifact.objects.filter(
        release=release,
        document=sample_document
    ).exists()


@pytest.mark.django_db
def test_remove_sbom_method(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
):
    """Test the remove_sbom method."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up SBOM
    sample_sbom.component = sample_component
    sample_sbom.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)

    # Remove SBOM from release
    release.remove_sbom(sample_sbom)

    # Verify artifact was removed
    assert not ReleaseArtifact.objects.filter(
        release=release,
        sbom=sample_sbom
    ).exists()


@pytest.mark.django_db
def test_remove_document_method(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_document: Document,  # noqa: F811
):
    """Test the remove_document method."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up document
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    ReleaseArtifact.objects.create(release=release, document=sample_document)

    # Remove document from release
    release.remove_document(sample_document)

    # Verify artifact was removed
    assert not ReleaseArtifact.objects.filter(
        release=release,
        document=sample_document
    ).exists()


# =============================================================================
# RELEASE ARTIFACT MODEL TESTS
# =============================================================================


@pytest.mark.django_db
def test_release_artifact_unique_constraint(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
):
    """Test that release artifacts have unique constraints."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up SBOM
    sample_sbom.component = sample_component
    sample_sbom.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Create first artifact
    ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)

    # Creating duplicate should fail
    from django.db import transaction
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)


@pytest.mark.django_db
def test_release_artifact_validation_both_none():
    """Test that ReleaseArtifact validation fails when both sbom and document are None."""
    with pytest.raises(ValidationError):
        artifact = ReleaseArtifact(sbom=None, document=None)
        artifact.full_clean()


@pytest.mark.django_db
def test_release_artifact_validation_both_set(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_document: Document,  # noqa: F811
):
    """Test that ReleaseArtifact validation fails when both sbom and document are set."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Set up artifacts
    sample_sbom.component = sample_component
    sample_sbom.save()
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    with pytest.raises(ValidationError):
        artifact = ReleaseArtifact(
            release=release,
            sbom=sample_sbom,
            document=sample_document
        )
        artifact.full_clean()


@pytest.mark.django_db
def test_release_artifact_duplicate_format_validation(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test that duplicate SBOM formats from same component are handled properly at the API level."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Create two SBOMs with same format for same component
    sbom1 = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="SBOM 1"
    )
    sbom2 = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="SBOM 2"
    )

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Add first SBOM
    ReleaseArtifact.objects.create(release=release, sbom=sbom1)

    # Adding second SBOM with same format should work at model level
    # (API level validation will prevent this, but model allows it)
    artifact = ReleaseArtifact(release=release, sbom=sbom2)
    artifact.full_clean()  # Should not raise ValidationError

    # Both artifacts can exist at the model level - the API enforces business rules


# =============================================================================
# SIGNAL HANDLER TESTS
# =============================================================================


@pytest.mark.django_db
@patch("sbomify.apps.core.models.Release.get_or_create_latest_release")
def test_sbom_creation_updates_latest_release(
    mock_get_or_create_latest_release,
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test that creating an SBOM updates the latest release."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Get the existing latest release that was created by signals
    existing_release = Release.objects.get(product=sample_product, is_latest=True)
    mock_get_or_create_latest_release.return_value = existing_release

    # Create SBOM - this should trigger the signal
    sbom = SBOM.objects.create(  # noqa: F841
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="Test SBOM"
    )

    # Verify the signal was triggered at least once (could be called multiple times due to relationships)
    assert mock_get_or_create_latest_release.call_count >= 1
    mock_get_or_create_latest_release.assert_called_with(sample_product)


@pytest.mark.django_db
@patch("sbomify.apps.core.models.Release.get_or_create_latest_release")
def test_document_creation_updates_latest_release(
    mock_get_or_create_latest_release,
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test that creating a Document updates the latest release."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Get the existing latest release that was created by signals
    existing_release = Release.objects.get(product=sample_product, is_latest=True)
    mock_get_or_create_latest_release.return_value = existing_release

    # Create Document - this should trigger the signal
    document = Document.objects.create(  # noqa: F841
        component=sample_component,
        document_type="license",
        name="Test Document"
    )

    # Verify the signal was triggered at least once (could be called multiple times due to relationships)
    assert mock_get_or_create_latest_release.call_count >= 1
    mock_get_or_create_latest_release.assert_called_with(sample_product)


@pytest.mark.django_db
def test_latest_release_auto_management_integration(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test full integration of latest release auto-management."""
    # Set up component relationship
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Verify latest release was auto-created when project was added to product
    latest_release = Release.objects.get(
        product=sample_product,
        is_latest=True
    )
    assert latest_release.name == "latest"

    # Create SBOM - should be added to existing latest release
    sbom = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="Test SBOM"
    )

    # Verify SBOM is in latest release
    latest_release.refresh_from_db()
    assert sbom in latest_release.get_sboms()

    # Create another SBOM - should be added to existing latest release
    sbom2 = SBOM.objects.create(
        component=sample_component,
        format="spdx",
        format_version="2.3",
        name="Test SBOM 2"
    )

    # Verify both SBOMs are in latest release
    latest_release.refresh_from_db()
    sboms = latest_release.get_sboms()
    assert sbom in sboms
    assert sbom2 in sboms

    # Create Document - should be added to latest release
    document = Document.objects.create(
        component=sample_component,
        document_type="license",
        name="Test Document"
    )

    # Verify document is in latest release
    latest_release.refresh_from_db()
    documents = latest_release.get_documents()
    assert document in documents


# =============================================================================
# COMPONENT MODEL ARTIFACT METHODS TESTS
# =============================================================================


@pytest.mark.django_db
def test_component_get_latest_sboms_by_format(
    sample_component: Component,  # noqa: F811
):
    """Test Component.get_latest_sboms_by_format method."""
    # Create multiple SBOMs with different formats
    sbom_cyclone_old = SBOM.objects.create(  # noqa: F841
        component=sample_component,
        format="cyclonedx",
        format_version="1.5",
        name="Old CycloneDX SBOM"
    )

    sbom_cyclone_new = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="New CycloneDX SBOM"
    )

    sbom_spdx = SBOM.objects.create(
        component=sample_component,
        format="spdx",
        format_version="2.3",
        name="SPDX SBOM"
    )

    latest_sboms = sample_component.get_latest_sboms_by_format()

    # Should return latest SBOM for each format
    assert len(latest_sboms) == 2
    assert "cyclonedx" in latest_sboms
    assert "spdx" in latest_sboms

    # Check that we got the latest SBOMs for each format
    assert latest_sboms["cyclonedx"] == sbom_cyclone_new  # Latest by created_at
    assert latest_sboms["spdx"] == sbom_spdx


@pytest.mark.django_db
def test_component_get_latest_documents_by_type(
    sample_component: Component,  # noqa: F811
):
    """Test Component.get_latest_documents_by_type method."""
    # Create multiple documents with different types
    doc_license_old = Document.objects.create(  # noqa: F841
        component=sample_component,
        document_type="license",
        name="Old License"
    )

    doc_license_new = Document.objects.create(
        component=sample_component,
        document_type="license",
        name="New License"
    )

    doc_readme = Document.objects.create(
        component=sample_component,
        document_type="readme",
        name="README"
    )

    latest_docs = sample_component.get_latest_documents_by_type()

    # Should return latest document for each type
    assert len(latest_docs) == 2
    assert "license" in latest_docs
    assert "readme" in latest_docs

    # Check that we got the latest documents for each type
    assert latest_docs["license"] == doc_license_new  # Latest by created_at
    assert latest_docs["readme"] == doc_readme


@pytest.mark.django_db
def test_component_get_latest_artifacts_by_type(
    sample_component: Component,  # noqa: F811
):
    """Test Component.get_latest_artifacts_by_type method."""
    # Create artifacts
    sbom = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="Test SBOM"
    )

    document = Document.objects.create(
        component=sample_component,
        document_type="license",
        name="Test Document"
    )

    latest_artifacts = sample_component.get_latest_artifacts_by_type()

    # Should return dict with sboms and documents keys
    assert "sboms" in latest_artifacts
    assert "documents" in latest_artifacts
    assert len(latest_artifacts["sboms"]) == 1
    assert len(latest_artifacts["documents"]) == 1
    assert sbom in latest_artifacts["sboms"].values()
    assert document in latest_artifacts["documents"].values()