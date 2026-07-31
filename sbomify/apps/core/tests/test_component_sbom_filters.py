"""
Tests for server-side version/format filtering on the component SBOMs list endpoint.

GET /api/v1/components/{component_id}/sboms accepts optional `version` and
`format` query parameters that exact-match against SBOM.version and
SBOM.format before pagination. These tests cover filter hits, misses,
combined filters, unchanged no-param behavior, and the public/private auth
matrix with filters applied.
"""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.sboms.models import SBOM


@pytest.fixture
def component_sboms(sample_component):  # noqa: F811
    """A component with SBOMs across several versions and formats."""
    sboms = {
        "tagged_cdx": SBOM.objects.create(
            name="test-component",
            version="v1.2.3",
            format="cyclonedx",
            sbom_filename="tagged-cdx.json",
            component=sample_component,
            source="test",
        ),
        "tagged_spdx": SBOM.objects.create(
            name="test-component",
            version="v1.2.3",
            format="spdx",
            sbom_filename="tagged-spdx.json",
            component=sample_component,
            source="test",
        ),
        "sha_cdx": SBOM.objects.create(
            name="test-component",
            version="8fae865",
            format="cyclonedx",
            sbom_filename="sha-cdx.json",
            component=sample_component,
            source="test",
        ),
        "untagged": SBOM.objects.create(
            name="test-component",
            version="1.2.3",
            format="spdx",
            sbom_filename="untagged.json",
            component=sample_component,
            source="test",
        ),
    }
    yield sboms
    for sbom in sboms.values():
        sbom.delete()


def _make_public(component) -> None:
    from sbomify.apps.sboms.models import Component

    component.visibility = Component.Visibility.PUBLIC
    component.save()


def _make_private(component) -> None:
    from sbomify.apps.sboms.models import Component

    component.visibility = Component.Visibility.PRIVATE
    component.save()


def _sboms_url(component_id: str) -> str:
    return reverse("api-1:list_component_sboms", kwargs={"component_id": component_id})


@pytest.mark.django_db
class TestComponentSbomFilters:
    """Test version/format filtering on the component SBOMs list endpoint."""

    def test_version_hit(self, sample_component, component_sboms):  # noqa: F811
        """Filtering by version returns only exact matches, newest first."""
        _make_public(sample_component)

        response = Client().get(_sboms_url(sample_component.id), {"version": "v1.2.3"})

        assert response.status_code == 200
        data = response.json()
        returned_ids = [item["sbom"]["id"] for item in data["items"]]
        expected = sorted(
            [component_sboms["tagged_cdx"], component_sboms["tagged_spdx"]],
            key=lambda s: s.created_at,
            reverse=True,
        )
        assert returned_ids == [s.id for s in expected]
        assert data["pagination"]["total"] == 2
        assert all(item["sbom"]["version"] == "v1.2.3" for item in data["items"])

    def test_version_miss_returns_empty_items(self, sample_component, component_sboms):  # noqa: F811
        """A version with no SBOMs returns 200 with an empty first page."""
        _make_public(sample_component)

        response = Client().get(_sboms_url(sample_component.id), {"version": "v9.9.9"})

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["pagination"]["total"] == 0

    def test_version_is_exact_match_not_prefix(self, sample_component, component_sboms):  # noqa: F811
        """'v1.2.3' and '1.2.3' are distinct versions — no fuzzy matching."""
        _make_public(sample_component)

        response = Client().get(_sboms_url(sample_component.id), {"version": "1.2.3"})

        assert response.status_code == 200
        returned_ids = [item["sbom"]["id"] for item in response.json()["items"]]
        assert returned_ids == [component_sboms["untagged"].id]

    def test_version_and_format_combined(self, sample_component, component_sboms):  # noqa: F811
        """Combining version and format narrows to a single SBOM."""
        _make_public(sample_component)

        response = Client().get(
            _sboms_url(sample_component.id),
            {"version": "v1.2.3", "format": "cyclonedx"},
        )

        assert response.status_code == 200
        returned_ids = [item["sbom"]["id"] for item in response.json()["items"]]
        assert returned_ids == [component_sboms["tagged_cdx"].id]

    def test_format_alone(self, sample_component, component_sboms):  # noqa: F811
        """Filtering by format alone returns all SBOMs in that format."""
        _make_public(sample_component)

        response = Client().get(_sboms_url(sample_component.id), {"format": "cyclonedx"})

        assert response.status_code == 200
        data = response.json()
        returned_ids = {item["sbom"]["id"] for item in data["items"]}
        assert returned_ids == {component_sboms["tagged_cdx"].id, component_sboms["sha_cdx"].id}
        assert all(item["sbom"]["format"] == "cyclonedx" for item in data["items"])

    def test_no_params_behavior_unchanged(self, sample_component, component_sboms):  # noqa: F811
        """Without filters the endpoint returns every SBOM, newest first."""
        _make_public(sample_component)

        response = Client().get(_sboms_url(sample_component.id))

        assert response.status_code == 200
        data = response.json()
        returned_ids = [item["sbom"]["id"] for item in data["items"]]
        expected = sorted(component_sboms.values(), key=lambda s: s.created_at, reverse=True)
        assert returned_ids == [s.id for s in expected]
        assert data["pagination"]["total"] == len(component_sboms)

    def test_filter_excludes_other_bom_types(self, sample_component, component_sboms):  # noqa: F811
        """A VEX artifact at the same version is not returned by the SBOM listing."""
        _make_public(sample_component)
        vex = SBOM.objects.create(
            name="test-component",
            version="v1.2.3",
            format="cyclonedx",
            sbom_filename="vex.json",
            component=sample_component,
            source="test",
            bom_type=SBOM.BomType.VEX,
        )
        try:
            response = Client().get(_sboms_url(sample_component.id), {"version": "v1.2.3"})

            assert response.status_code == 200
            returned_ids = [item["sbom"]["id"] for item in response.json()["items"]]
            assert vex.id not in returned_ids
            assert len(returned_ids) == 2
        finally:
            vex.delete()

    def test_public_component_anonymous_with_filters(self, sample_component, component_sboms):  # noqa: F811
        """Filters work anonymously on public components."""
        _make_public(sample_component)

        response = Client().get(
            _sboms_url(sample_component.id),
            {"version": "8fae865", "format": "cyclonedx"},
        )

        assert response.status_code == 200
        returned_ids = [item["sbom"]["id"] for item in response.json()["items"]]
        assert returned_ids == [component_sboms["sha_cdx"].id]

    def test_private_component_anonymous_with_filters(self, sample_component, component_sboms):  # noqa: F811
        """Filters do not bypass authentication on private components."""
        _make_private(sample_component)

        response = Client().get(_sboms_url(sample_component.id), {"version": "v1.2.3"})

        assert response.status_code == 403
        assert "Authentication required for private items" in response.json()["detail"]

    def test_private_component_with_auth_and_filters(
        self,
        sample_component,  # noqa: F811
        component_sboms,
        authenticated_api_client,  # noqa: F811
    ):
        """Team members can filter SBOMs on private components."""
        _make_private(sample_component)

        client, access_token = authenticated_api_client
        response = client.get(
            _sboms_url(sample_component.id),
            {"version": "v1.2.3"},
            HTTP_AUTHORIZATION=f"Bearer {access_token.encoded_token}",
        )

        assert response.status_code == 200
        returned_ids = {item["sbom"]["id"] for item in response.json()["items"]}
        assert returned_ids == {component_sboms["tagged_cdx"].id, component_sboms["tagged_spdx"].id}
