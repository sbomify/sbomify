"""Tests for ComponentRelease and ComponentReleaseArtifact models."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from sbomify.apps.core.models import Component, ComponentRelease, ComponentReleaseArtifact
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_component,
    sample_product,
    sample_sbom,
)


@pytest.mark.django_db
def test_create_component_release(sample_component: Component):  # noqa: F811
    """Test basic ComponentRelease creation with defaults."""
    cr = ComponentRelease.objects.create(
        component=sample_component,
        version="1.0.0",
    )

    assert cr.uuid is not None
    assert cr.collection_version == 1
    assert cr.collection_update_reason == ComponentRelease.CollectionUpdateReason.INITIAL_RELEASE
    assert cr.created_at is not None
    assert cr.collection_updated_at is None
    assert cr.qualifiers == {}


@pytest.mark.django_db
def test_unique_constraint(sample_component: Component):  # noqa: F811
    """Test that duplicate (component, version, qualifiers) raises IntegrityError."""
    ComponentRelease.objects.create(
        component=sample_component,
        version="1.0.0",
        qualifiers={},
    )

    with transaction.atomic():
        with pytest.raises(IntegrityError):
            ComponentRelease.objects.create(
                component=sample_component,
                version="1.0.0",
                qualifiers={},
            )


@pytest.mark.django_db
def test_bump_collection_version(sample_component: Component):  # noqa: F811
    """Test atomic increment of collection_version with reason and updated_at."""
    cr = ComponentRelease.objects.create(
        component=sample_component,
        version="1.0.0",
    )
    assert cr.collection_version == 1
    assert cr.collection_updated_at is None

    cr.bump_collection_version(ComponentRelease.CollectionUpdateReason.ARTIFACT_ADDED)

    assert cr.collection_version == 2
    assert cr.collection_updated_at is not None
    assert cr.collection_update_reason == ComponentRelease.CollectionUpdateReason.ARTIFACT_ADDED

    # Bump again to verify continued increment
    cr.bump_collection_version(ComponentRelease.CollectionUpdateReason.ARTIFACT_REMOVED)

    assert cr.collection_version == 3
    assert cr.collection_update_reason == ComponentRelease.CollectionUpdateReason.ARTIFACT_REMOVED


@pytest.mark.django_db
def test_different_qualifiers_are_distinct(sample_component: Component):  # noqa: F811
    """Test that same component+version with different qualifiers creates separate records."""
    cr1 = ComponentRelease.objects.create(
        component=sample_component,
        version="1.0.0",
        qualifiers={"os": "linux", "arch": "amd64"},
    )
    cr2 = ComponentRelease.objects.create(
        component=sample_component,
        version="1.0.0",
        qualifiers={"os": "windows", "arch": "amd64"},
    )

    assert cr1.pk != cr2.pk
    assert cr1.uuid != cr2.uuid
    assert ComponentRelease.objects.filter(component=sample_component, version="1.0.0").count() == 2


@pytest.mark.django_db
def test_create_artifact(sample_component: Component, sample_sbom: SBOM):  # noqa: F811
    """Test linking an SBOM to a ComponentRelease via ComponentReleaseArtifact."""
    cr = ComponentRelease.objects.create(
        component=sample_component,
        version="1.0.0",
    )

    artifact = ComponentReleaseArtifact.objects.create(
        component_release=cr,
        sbom=sample_sbom,
    )

    assert artifact.component_release == cr
    assert artifact.sbom == sample_sbom
    assert artifact.created_at is not None
    assert cr.artifacts.count() == 1


@pytest.mark.django_db
def test_artifact_unique_constraint(sample_component: Component, sample_sbom: SBOM):  # noqa: F811
    """Test that same SBOM+ComponentRelease twice raises IntegrityError."""
    cr = ComponentRelease.objects.create(
        component=sample_component,
        version="1.0.0",
    )

    ComponentReleaseArtifact.objects.create(
        component_release=cr,
        sbom=sample_sbom,
    )

    with transaction.atomic():
        with pytest.raises(IntegrityError):
            ComponentReleaseArtifact.objects.create(
                component_release=cr,
                sbom=sample_sbom,
            )


# =============================================================================
# Signal tests: auto-creation on SBOM save/delete
# =============================================================================


@pytest.mark.django_db
def test_sbom_create_creates_component_release(sample_component: Component):  # noqa: F811
    """Saving a new SBOM auto-creates a ComponentRelease and links it."""
    sbom = SBOM.objects.create(component=sample_component, name="test", version="1.0.0", format="cyclonedx")
    cr = ComponentRelease.objects.get(component=sample_component, version="1.0.0")
    assert cr.qualifiers == {}
    assert cr.collection_version == 1
    assert ComponentReleaseArtifact.objects.filter(component_release=cr, sbom=sbom).exists()


@pytest.mark.django_db
def test_sbom_create_with_qualifiers(sample_component: Component):  # noqa: F811
    """SBOM with qualifiers creates a ComponentRelease with matching qualifiers."""
    sbom = SBOM.objects.create(
        component=sample_component,
        name="test",
        version="1.0.0",
        format="cyclonedx",
        qualifiers={"arch": "arm64"},
    )
    cr = ComponentRelease.objects.get(component=sample_component, version="1.0.0", qualifiers={"arch": "arm64"})
    assert ComponentReleaseArtifact.objects.filter(component_release=cr, sbom=sbom).exists()


@pytest.mark.django_db
def test_second_sbom_bumps_collection_version(sample_component: Component):  # noqa: F811
    """Adding a second SBOM to same ComponentRelease bumps collection version."""
    SBOM.objects.create(component=sample_component, name="test-cdx", version="1.0.0", format="cyclonedx")
    cr = ComponentRelease.objects.get(component=sample_component, version="1.0.0")
    assert cr.collection_version == 1

    SBOM.objects.create(component=sample_component, name="test-spdx", version="1.0.0", format="spdx")
    cr.refresh_from_db()
    assert cr.collection_version == 2
    assert cr.collection_update_reason == "ARTIFACT_ADDED"


@pytest.mark.django_db
def test_sbom_delete_bumps_collection_version(sample_component: Component):  # noqa: F811
    """Deleting an SBOM bumps the ComponentRelease collection version."""
    SBOM.objects.create(component=sample_component, name="test-cdx", version="1.0.0", format="cyclonedx")
    sbom2 = SBOM.objects.create(component=sample_component, name="test-spdx", version="1.0.0", format="spdx")
    cr = ComponentRelease.objects.get(component=sample_component, version="1.0.0")
    assert cr.collection_version == 2  # bumped by second SBOM

    sbom2.delete()
    cr.refresh_from_db()
    assert cr.collection_version == 3
    assert cr.collection_update_reason == "ARTIFACT_REMOVED"


@pytest.mark.django_db
def test_sbom_delete_last_artifact_deletes_component_release(sample_component: Component):  # noqa: F811
    """Deleting the last SBOM deletes the ComponentRelease."""
    sbom = SBOM.objects.create(component=sample_component, name="test", version="1.0.0", format="cyclonedx")
    cr_id = ComponentRelease.objects.get(component=sample_component, version="1.0.0").pk

    sbom.delete()
    assert not ComponentRelease.objects.filter(pk=cr_id).exists()
