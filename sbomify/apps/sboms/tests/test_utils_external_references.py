"""
Test cases for the external reference functionality in sboms/utils.py.
"""

import pytest
from unittest.mock import Mock, patch

from sbomify.apps.core.models import Component, User, Product
from sbomify.apps.sboms.models import ProductLink
from sbomify.apps.teams.models import Team
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.documents.models import Document

# Use local CycloneDX schemas
from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16


@pytest.fixture
def sample_product(sample_team_with_owner_member):  # noqa: F811
    """Create a sample product for testing."""
    product = Product.objects.create(
        name='Test Product',
        team=sample_team_with_owner_member.team
    )
    yield product
    product.delete()


@pytest.fixture
def sample_doc_component(sample_team_with_owner_member):  # noqa: F811
    """Create a sample document component for testing."""
    component = Component.objects.create(
        name='Test Document Component',
        team=sample_team_with_owner_member.team,
        component_type='document',
        is_public=True
    )
    yield component
    component.delete()


@pytest.mark.django_db
class TestExternalReferenceUtils:
    """Test cases for external reference utility functions."""

    def test_get_spdx_category_for_product_link(self):
        """Test SPDX category mapping for product links."""
        from sbomify.apps.sboms.utils import _get_spdx_category_for_product_link

        test_cases = [
            ('security', 'SECURITY'),
            ('download', 'PACKAGE-MANAGER'),
            ('website', 'OTHER'),
            ('support', 'OTHER'),
            ('documentation', 'OTHER'),
            ('repository', 'OTHER'),
            ('changelog', 'OTHER'),
            ('release_notes', 'OTHER'),
            ('issue_tracker', 'OTHER'),
            ('chat', 'OTHER'),
            ('social', 'OTHER'),
            ('other', 'OTHER'),
            ('unknown_type', 'OTHER'),  # Default fallback
        ]

        for link_type, expected_category in test_cases:
            result = _get_spdx_category_for_product_link(link_type)
            assert result == expected_category, \
                f'Link type {link_type} should map to {expected_category}'

    def test_get_spdx_type_for_product_link(self):
        """Test SPDX type mapping for product links."""
        from sbomify.apps.sboms.utils import _get_spdx_type_for_product_link

        test_cases = [
            ('website', 'website'),
            ('support', 'support'),
            ('documentation', 'documentation'),
            ('repository', 'vcs'),
            ('changelog', 'changelog'),
            ('release_notes', 'release-notes'),
            ('security', 'security-contact'),
            ('issue_tracker', 'issue-tracker'),
            ('download', 'download'),
            ('chat', 'chat'),
            ('social', 'social'),
            ('other', 'other'),
            ('unknown_type', 'other'),  # Default fallback
        ]

        for link_type, expected_type in test_cases:
            result = _get_spdx_type_for_product_link(link_type)
            assert result == expected_type, \
                f'Link type {link_type} should map to {expected_type}'

    def test_create_product_spdx_external_references_with_links(self, sample_product):
        """Test creating SPDX external references from product links."""
        from sbomify.apps.sboms.utils import create_product_spdx_external_references

        # Create product links
        ProductLink.objects.create(
            product=sample_product,
            link_type='security',
            url='https://example.com/security',
            description='Security contact'
        )
        ProductLink.objects.create(
            product=sample_product,
            link_type='download',
            url='https://example.com/download'
        )

        external_refs = create_product_spdx_external_references(sample_product, user=None)

        assert len(external_refs) == 2

        # Check security reference
        security_ref = next(ref for ref in external_refs if ref['referenceLocator'] == 'https://example.com/security')
        assert security_ref['referenceCategory'] == 'SECURITY'
        assert security_ref['referenceType'] == 'security-contact'
        assert security_ref['comment'] == 'Security contact'

        # Check download reference
        download_ref = next(ref for ref in external_refs if ref['referenceLocator'] == 'https://example.com/download')
        assert download_ref['referenceCategory'] == 'PACKAGE-MANAGER'
        assert download_ref['referenceType'] == 'download'
        assert download_ref['comment'] is None

    def test_create_product_spdx_external_references_empty_product(self, sample_product):
        """Test creating SPDX external references for a product with no links or documents."""
        from sbomify.apps.sboms.utils import create_product_spdx_external_references

        external_refs = create_product_spdx_external_references(sample_product, user=None)
        assert len(external_refs) == 0