"""Where an uploaded HBOM lands: the product's latest release, the component
release junction, and its own detail page.

An HBOM is an SBOM-table row of a different bom_type, so every one of these paths
keys on the type rather than on the format — a board's hardware BOM and its
firmware SBOM are the same cyclonedx format for the same component and must not
displace each other anywhere.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import (
    Component,
    ComponentRelease,
    ComponentReleaseArtifact,
    Product,
    Release,
)
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM


def _artifact(component: Component, bom_type: str, name: str, version: str = "rev-1") -> SBOM:
    return SBOM.objects.create(
        component=component,
        name=name,
        version=version,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=f"{name}.json",
        source="api",
        bom_type=bom_type,
    )


@pytest.mark.django_db
def test_hbom_auto_pins_into_latest_release_beside_the_sbom(
    sample_product: Product,
    sample_component: Component,
) -> None:
    """Uploading the board's HBOM must not evict the firmware SBOM the release
    already pins: each (format, bom_type) owns its own slot, and both pins are
    sbomify-managed."""
    # The latest release is created lazily, by the same signal that auto-pins,
    # so it is read after the artifacts exist rather than before.
    sbom = _artifact(sample_component, SBOM.BomType.SBOM, "firmware")
    hbom = _artifact(sample_component, SBOM.BomType.HBOM, "board")

    latest = Release.objects.get(product=sample_product, is_latest=True)

    pinned = latest.artifacts.filter(sbom__component=sample_component)
    assert {artifact.sbom_id for artifact in pinned} == {sbom.id, hbom.id}
    assert all(artifact.auto_pinned for artifact in pinned)


@pytest.mark.django_db
def test_hbom_creates_component_release_junction_rows(
    sample_component: Component,
) -> None:
    """The TEA component-release view is built from these rows, so an HBOM has to
    link into the same (component, version) release as the SBOM sharing its
    version rather than spawning a second one."""
    sbom = _artifact(sample_component, SBOM.BomType.SBOM, "firmware")
    hbom = _artifact(sample_component, SBOM.BomType.HBOM, "board")

    component_release = ComponentRelease.objects.get(component=sample_component, version="rev-1")
    linked = ComponentReleaseArtifact.objects.filter(component_release=component_release)

    assert {artifact.sbom_id for artifact in linked} == {sbom.id, hbom.id}


@pytest.mark.django_db
class TestHbomDetailPageRouting:
    """``/hbom/`` is the canonical path for a hardware BOM; a request under any
    other type segment is redirected rather than served, so bookmarks and the
    artifact table's link both settle on one URL."""

    def _client(self, component: Component, user) -> Client:
        client = Client()
        setup_authenticated_client_session(client, component.team, user)
        return client

    def _url(self, component: Component, item_type: str, item_id: str) -> str:
        return reverse(
            "core:component_item",
            kwargs={"component_id": component.id, "item_type": item_type, "item_id": item_id},
        )

    def test_hbom_renders_on_its_own_path(self, sample_component: Component, sample_user) -> None:
        hbom = _artifact(sample_component, SBOM.BomType.HBOM, "board")

        response = self._client(sample_component, sample_user).get(self._url(sample_component, "hbom", hbom.id))

        assert response.status_code == 200
        assert response.context["is_hbom"] is True
        assert response.context["is_cbom"] is False
        assert response.context["is_vex"] is False
        assert b"Download CycloneDX HBOM" in response.content

    def test_sboms_path_redirects_to_hbom(self, sample_component: Component, sample_user) -> None:
        hbom = _artifact(sample_component, SBOM.BomType.HBOM, "board")

        response = self._client(sample_component, sample_user).get(self._url(sample_component, "sboms", hbom.id))

        assert response.status_code == 302
        assert response["Location"] == self._url(sample_component, "hbom", hbom.id)

    def test_hbom_path_redirects_a_plain_sbom_back(self, sample_component: Component, sample_user) -> None:
        sbom = _artifact(sample_component, SBOM.BomType.SBOM, "firmware")

        response = self._client(sample_component, sample_user).get(self._url(sample_component, "hbom", sbom.id))

        assert response.status_code == 302
        assert response["Location"] == self._url(sample_component, "sboms", sbom.id)
