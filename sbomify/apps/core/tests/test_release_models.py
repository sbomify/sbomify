"""Tests for Release model functionality and signal handlers."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

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
    """Create a sample component for testing.

    Component is attached directly to the sample product via the ProductComponent M2M.
    """
    component = Component.objects.create(name="test component", team=sample_product.team)
    sample_product.components.add(component)
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
    release = Release.objects.create(product=sample_product, name="v1.0.0")

    assert release.name == "v1.0.0"
    assert release.product == sample_product
    assert release.is_latest is False
    assert release.created_at is not None
    assert release.released_at is not None
    assert release.created_at == release.released_at


@pytest.mark.django_db
def test_release_released_at_can_be_cleared(sample_product: Product):  # noqa: F811
    """Ensure released_at can be explicitly set to None on update."""
    release = Release.objects.create(product=sample_product, name="v1.0.0")

    release.released_at = None
    release.save()
    release.refresh_from_db()

    assert release.released_at is None


@pytest.mark.django_db
def test_release_released_at_not_before_created_at(sample_product: Product):  # noqa: F811
    """Validation should fail if released_at is earlier than created_at."""
    created_at = timezone.now()
    release = Release(
        product=sample_product,
        name="v1.0.0-invalid",
        created_at=created_at,
        released_at=created_at - timedelta(days=1),
    )

    with pytest.raises(ValidationError):
        release.save()


@pytest.mark.django_db
def test_release_ordering_places_nulls_last(sample_product: Product):  # noqa: F811
    """Ordering should place releases with null released_at at the end."""
    now = timezone.now()
    newest = Release.objects.create(
        product=sample_product,
        name="v3.0.0",
        created_at=now - timedelta(days=1),
        released_at=now,
    )
    older = Release.objects.create(
        product=sample_product,
        name="v2.0.0",
        created_at=now - timedelta(days=14),
        released_at=now - timedelta(days=7),
    )
    unset = Release.objects.create(
        product=sample_product,
        name="v1.0.0",
        created_at=now - timedelta(days=21),
        released_at=now - timedelta(days=21),
    )
    unset.released_at = None
    unset.save(update_fields=["released_at"])

    ordered_names = list(Release.objects.filter(product=sample_product).values_list("name", flat=True))

    assert ordered_names == ["v3.0.0", "v2.0.0", "v1.0.0"]


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
    product2 = Product.objects.create(name="Product 2", team=sample_team_with_owner_member.team)

    # Create releases with same name in different products
    release1 = Release.objects.create(product=sample_product, name="v1.0.0")
    release2 = Release.objects.create(product=product2, name="v1.0.0")

    assert release1.name == release2.name
    assert release1.product != release2.product


@pytest.mark.django_db
def test_single_latest_release_per_product(sample_product: Product):  # noqa: F811
    """Test that only one release per product can be marked as latest."""
    release1 = Release.objects.create(  # noqa: F841
        product=sample_product, name="v1.0.0", is_latest=True
    )

    # Creating another latest release should fail
    with pytest.raises(ValidationError):
        release2 = Release(product=sample_product, name="v2.0.0", is_latest=True)
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
    # Set up component relationship — fixture already attaches component to product
    sample_component.team = sample_product.team
    sample_component.save()

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
    # Set up component relationship — fixture already attaches component to product
    sample_component.team = sample_product.team
    sample_component.save()

    # Set up artifacts
    sample_sbom.component = sample_component
    sample_sbom.save()
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    with pytest.raises(ValidationError):
        artifact = ReleaseArtifact(release=release, sbom=sample_sbom, document=sample_document)
        artifact.full_clean()


@pytest.mark.django_db
def test_release_artifact_duplicate_format_validation(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test that duplicate SBOM formats from same component are handled properly at the API level."""
    # Set up component relationship — fixture already attaches component to product
    sample_component.team = sample_product.team
    sample_component.save()

    # Create two SBOMs with same format for same component (different versions to satisfy uniqueness)
    sbom1 = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="SBOM 1",
        version="1.0.0",
    )
    sbom2 = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="SBOM 2",
        version="2.0.0",
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
    # Set up component relationship — fixture already attaches component to product
    sample_component.team = sample_product.team
    sample_component.save()

    # Get the existing latest release that was created by signals
    existing_release = Release.objects.get(product=sample_product, is_latest=True)
    mock_get_or_create_latest_release.return_value = existing_release

    # Create SBOM - this should trigger the signal
    sbom = SBOM.objects.create(  # noqa: F841
        component=sample_component, format="cyclonedx", format_version="1.6", name="Test SBOM"
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
    # Set up component relationship — fixture already attaches component to product
    sample_component.team = sample_product.team
    sample_component.save()

    # Get the existing latest release that was created by signals
    existing_release = Release.objects.get(product=sample_product, is_latest=True)
    mock_get_or_create_latest_release.return_value = existing_release

    # Create Document - this should trigger the signal
    document = Document.objects.create(  # noqa: F841
        component=sample_component, document_type="license", name="Test Document"
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
    # Set up component relationship — fixture already attaches component to product
    sample_component.team = sample_product.team
    sample_component.save()

    # Verify latest release was auto-created when component was added to product
    latest_release = Release.objects.get(product=sample_product, is_latest=True)
    assert latest_release.name == "latest"

    # Create SBOM - should be added to existing latest release
    sbom = SBOM.objects.create(component=sample_component, format="cyclonedx", format_version="1.6", name="Test SBOM")

    # Verify SBOM is in latest release
    latest_release.refresh_from_db()
    assert latest_release.artifacts.filter(sbom=sbom).exists()

    # Create another SBOM - should be added to existing latest release
    sbom2 = SBOM.objects.create(component=sample_component, format="spdx", format_version="2.3", name="Test SBOM 2")

    # Verify both SBOMs are in latest release
    latest_release.refresh_from_db()
    assert latest_release.artifacts.filter(sbom=sbom).exists()
    assert latest_release.artifacts.filter(sbom=sbom2).exists()

    # Create Document - should be added to latest release
    document = Document.objects.create(component=sample_component, document_type="license", name="Test Document")

    # Verify document is in latest release
    latest_release.refresh_from_db()
    assert latest_release.artifacts.filter(document=document).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("other_bom_type", [SBOM.BomType.CBOM, SBOM.BomType.VEX])
def test_non_sbom_upload_does_not_evict_sbom_from_latest_release(
    other_bom_type,
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """A CBOM/VEX (same cyclonedx format) uploaded after an SBOM must not evict the SBOM from
    the latest release — it takes its own slot. Regression for the live bug shipped with CBOM
    auto-detection."""
    sample_component.team = sample_product.team
    sample_component.save()
    latest_release = Release.objects.get(product=sample_product, is_latest=True)

    sbom = SBOM.objects.create(
        component=sample_component, format="cyclonedx", format_version="1.6", name="Real SBOM", version="1.0.0"
    )
    latest_release.refresh_from_db()
    assert latest_release.artifacts.filter(sbom=sbom).exists()

    # Upload a same-format non-SBOM artifact (CBOM or VEX).
    other = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name=f"{other_bom_type} artifact",
        version="1.0.0",
        bom_type=other_bom_type,
    )

    latest_release.refresh_from_db()
    assert latest_release.artifacts.filter(sbom=sbom).exists()  # the real SBOM survived
    assert latest_release.artifacts.filter(sbom=other).exists()  # the non-SBOM has its own slot
    # The release keeps exactly one artifact per (component, format, bom_type).
    assert latest_release.artifacts.filter(sbom__component=sample_component).count() == 2


# =============================================================================
# COMPONENT MODEL ARTIFACT METHODS TESTS
# =============================================================================


@pytest.mark.django_db
def test_component_get_latest_sboms_by_format(
    sample_component: Component,  # noqa: F811
):
    """Test Component.get_latest_sboms_by_format method."""
    # Create multiple SBOMs with different formats (different versions to satisfy uniqueness)
    sbom_cyclone_old = SBOM.objects.create(  # noqa: F841
        component=sample_component,
        format="cyclonedx",
        format_version="1.5",
        name="Old CycloneDX SBOM",
        version="1.0.0",
    )

    sbom_cyclone_new = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="New CycloneDX SBOM",
        version="2.0.0",
    )

    sbom_spdx = SBOM.objects.create(
        component=sample_component,
        format="spdx",
        format_version="2.3",
        name="SPDX SBOM",
        version="1.0.0",
    )

    latest_sboms = sample_component.get_latest_sboms_by_format()

    # Keyed on (format, bom_type); should return the latest SBOM for each format
    assert len(latest_sboms) == 2
    assert ("cyclonedx", SBOM.BomType.SBOM) in latest_sboms
    assert ("spdx", SBOM.BomType.SBOM) in latest_sboms

    # Check that we got the latest SBOMs for each format
    assert latest_sboms[("cyclonedx", SBOM.BomType.SBOM)] == sbom_cyclone_new  # Latest by created_at
    assert latest_sboms[("spdx", SBOM.BomType.SBOM)] == sbom_spdx


@pytest.mark.django_db
def test_get_latest_sboms_by_format_separates_bom_type(
    sample_component: Component,  # noqa: F811
):
    """A same-format CBOM must not displace the SBOM slot: each (format, bom_type) is its own key."""
    sbom = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="Real SBOM",
        version="1.0.0",
        bom_type=SBOM.BomType.SBOM,
    )
    cbom = SBOM.objects.create(
        component=sample_component,
        format="cyclonedx",
        format_version="1.6",
        name="CBOM",
        version="1.0.0",
        bom_type=SBOM.BomType.CBOM,
    )

    latest = sample_component.get_latest_sboms_by_format()

    assert latest[("cyclonedx", SBOM.BomType.SBOM)] == sbom
    assert latest[("cyclonedx", SBOM.BomType.CBOM)] == cbom


@pytest.mark.django_db
def test_component_get_latest_documents_by_type(
    sample_component: Component,  # noqa: F811
):
    """Test Component.get_latest_documents_by_type method."""
    # Create multiple documents with different types
    doc_license_old = Document.objects.create(  # noqa: F841
        component=sample_component, document_type="license", name="Old License"
    )

    doc_license_new = Document.objects.create(component=sample_component, document_type="license", name="New License")

    doc_readme = Document.objects.create(component=sample_component, document_type="readme", name="README")

    latest_docs = sample_component.get_latest_documents_by_type()

    # Should return latest document for each type
    assert len(latest_docs) == 2
    assert "license" in latest_docs
    assert "readme" in latest_docs

    # Check that we got the latest documents for each type
    assert latest_docs["license"] == doc_license_new  # Latest by created_at
    assert latest_docs["readme"] == doc_readme


# =============================================================================
# Signal: pre_clear / post_clear on ProductComponent
# =============================================================================


@pytest.mark.django_db
def test_component_products_clear_refreshes_previous_products_latest_releases(
    sample_user,  # noqa: F811
):
    """Regression test for the pre_clear snapshot path in
    ``update_latest_release_on_product_components_changed``.

    When ``component.products.clear()`` fires (forward side, ``reverse=False``),
    Django's m2m_changed delivers ``pk_set=None`` because the rows are already
    gone by ``post_clear``. The signal handler snapshots affected product IDs
    on ``pre_clear`` (stored on the instance) and consumes them in
    ``post_clear`` to fan out ``Release.refresh_latest_artifacts()``.

    Without this path, ComponentScopeView (which clears products when flipping
    a component to workspace-scoped) would leave the previous products with
    stale ``latest`` releases.
    """
    from sbomify.apps.teams.models import Team

    team = Team.objects.create(name="signal-test-team")
    component = Component.objects.create(name="snapshot-comp", team=team, component_type=Component.ComponentType.BOM)
    p_a = Product.objects.create(name="P-A", team=team)
    p_b = Product.objects.create(name="P-B", team=team)
    component.products.add(p_a, p_b)

    with patch("sbomify.apps.core.models.Release.refresh_latest_artifacts") as refresh:
        component.products.clear()

        # The signal should have fanned out a refresh for each previously-
        # attached product. The exact call count is one per product (latest
        # release reused via get_or_create_latest_release).
        assert refresh.call_count >= 2, (
            f"Expected ≥2 refresh calls (one per previously-attached product), got {refresh.call_count}"
        )

    # The pre_clear snapshot must have been consumed (deleted) so a stale
    # value can't survive a subsequent reload of the same instance.
    assert not hasattr(component, "_sbomify_pending_clear_product_ids")
