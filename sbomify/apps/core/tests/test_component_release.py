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
