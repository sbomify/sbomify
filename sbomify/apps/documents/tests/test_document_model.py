"""
Test cases for the Document model with new standardized document types
and external reference functionality.
"""

import pytest
from django.core.exceptions import ValidationError

from sbomify.apps.documents.models import Document
from sbomify.apps.core.models import Component
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401


@pytest.fixture
def sample_component(sample_team_with_owner_member):  # noqa: F811
    """Create a sample component for testing."""
    component = Component.objects.create(
        name='Test Component',
        team=sample_team_with_owner_member.team,
        component_type='document'
    )
    yield component
    component.delete()


@pytest.mark.django_db
class TestDocumentModel:
    """Test cases for the Document model."""

    def test_document_type_choices(self, sample_component):
        """Test that all document type choices are valid."""
        # Test all predefined document types
        for choice_value, choice_label in Document.DocumentType.choices:
            document = Document.objects.create(
                name=f'Test Document {choice_value}',
                component=sample_component,
                document_type=choice_value
            )
            assert document.document_type == choice_value
            assert document.get_document_type_display() == choice_label

    def test_default_document_type(self, sample_component):
        """Test that the default document type is 'other'."""
        document = Document.objects.create(
            name='Test Document',
            component=sample_component
        )
        assert document.document_type == Document.DocumentType.OTHER

    def test_cyclonedx_external_ref_type_mapping(self, sample_component):
        """Test CycloneDX external reference type mapping."""
        test_cases = [
            # Technical Documentation
            (Document.DocumentType.SPECIFICATION, 'documentation'),
            (Document.DocumentType.MANUAL, 'documentation'),
            (Document.DocumentType.README, 'documentation'),
            (Document.DocumentType.DOCUMENTATION, 'documentation'),
            (Document.DocumentType.BUILD_INSTRUCTIONS, 'build-meta'),
            (Document.DocumentType.CONFIGURATION, 'configuration'),

            # Legal and Compliance
            (Document.DocumentType.LICENSE, 'license'),
            (Document.DocumentType.COMPLIANCE, 'certification-report'),
            (Document.DocumentType.EVIDENCE, 'evidence'),

            # Release Information
            (Document.DocumentType.CHANGELOG, 'release-notes'),
            (Document.DocumentType.RELEASE_NOTES, 'release-notes'),

            # Security Documents
            (Document.DocumentType.SECURITY_ADVISORY, 'advisories'),
            (Document.DocumentType.VULNERABILITY_REPORT, 'vulnerability-assertion'),
            (Document.DocumentType.THREAT_MODEL, 'threat-model'),
            (Document.DocumentType.RISK_ASSESSMENT, 'risk-assessment'),
            (Document.DocumentType.PENTEST_REPORT, 'pentest-report'),

            # Analysis Reports
            (Document.DocumentType.STATIC_ANALYSIS, 'static-analysis-report'),
            (Document.DocumentType.DYNAMIC_ANALYSIS, 'dynamic-analysis-report'),
            (Document.DocumentType.QUALITY_METRICS, 'quality-metrics'),
            (Document.DocumentType.MATURITY_REPORT, 'maturity-report'),
            (Document.DocumentType.REPORT, 'other'),

            # Other
            (Document.DocumentType.OTHER, 'other'),
        ]

        for document_type, expected_cyclonedx_type in test_cases:
            document = Document.objects.create(
                name=f'Test Document {document_type}',
                component=sample_component,
                document_type=document_type
            )
            assert document.cyclonedx_external_ref_type == expected_cyclonedx_type, \
                f'Document type {document_type} should map to {expected_cyclonedx_type}'

    def test_spdx_reference_category_mapping(self, sample_component):
        """Test SPDX reference category mapping."""
        # Security document types
        security_types = [
            Document.DocumentType.SECURITY_ADVISORY,
            Document.DocumentType.VULNERABILITY_REPORT,
            Document.DocumentType.THREAT_MODEL,
            Document.DocumentType.RISK_ASSESSMENT,
            Document.DocumentType.PENTEST_REPORT,
        ]

        for doc_type in security_types:
            document = Document.objects.create(
                name=f'Test Document {doc_type}',
                component=sample_component,
                document_type=doc_type
            )
            assert document.spdx_reference_category == 'SECURITY', \
                f'Document type {doc_type} should be in SECURITY category'

        # All other document types should be in OTHER category
        other_types = [
            Document.DocumentType.SPECIFICATION,
            Document.DocumentType.MANUAL,
            Document.DocumentType.README,
            Document.DocumentType.DOCUMENTATION,
            Document.DocumentType.BUILD_INSTRUCTIONS,
            Document.DocumentType.CONFIGURATION,
            Document.DocumentType.LICENSE,
            Document.DocumentType.COMPLIANCE,
            Document.DocumentType.EVIDENCE,
            Document.DocumentType.CHANGELOG,
            Document.DocumentType.RELEASE_NOTES,
            Document.DocumentType.STATIC_ANALYSIS,
            Document.DocumentType.DYNAMIC_ANALYSIS,
            Document.DocumentType.QUALITY_METRICS,
            Document.DocumentType.MATURITY_REPORT,
            Document.DocumentType.REPORT,
            Document.DocumentType.OTHER,
        ]

        for doc_type in other_types:
            document = Document.objects.create(
                name=f'Test Document {doc_type}',
                component=sample_component,
                document_type=doc_type
            )
            assert document.spdx_reference_category == 'OTHER', \
                f'Document type {doc_type} should be in OTHER category'

    def test_spdx_reference_type_mapping(self, sample_component):
        """Test SPDX reference type mapping."""
        test_cases = [
            # Technical Documentation
            (Document.DocumentType.SPECIFICATION, 'specification'),
            (Document.DocumentType.MANUAL, 'manual'),
            (Document.DocumentType.README, 'readme'),
            (Document.DocumentType.DOCUMENTATION, 'documentation'),
            (Document.DocumentType.BUILD_INSTRUCTIONS, 'build-instructions'),
            (Document.DocumentType.CONFIGURATION, 'configuration'),

            # Legal and Compliance
            (Document.DocumentType.LICENSE, 'license'),
            (Document.DocumentType.COMPLIANCE, 'compliance'),
            (Document.DocumentType.EVIDENCE, 'evidence'),

            # Release Information
            (Document.DocumentType.CHANGELOG, 'changelog'),
            (Document.DocumentType.RELEASE_NOTES, 'release-notes'),

            # Security Documents
            (Document.DocumentType.SECURITY_ADVISORY, 'advisory'),
            (Document.DocumentType.VULNERABILITY_REPORT, 'vulnerability-report'),
            (Document.DocumentType.THREAT_MODEL, 'threat-model'),
            (Document.DocumentType.RISK_ASSESSMENT, 'risk-assessment'),
            (Document.DocumentType.PENTEST_REPORT, 'pentest-report'),

            # Analysis Reports
            (Document.DocumentType.STATIC_ANALYSIS, 'static-analysis-report'),
            (Document.DocumentType.DYNAMIC_ANALYSIS, 'dynamic-analysis-report'),
            (Document.DocumentType.QUALITY_METRICS, 'quality-metrics'),
            (Document.DocumentType.MATURITY_REPORT, 'maturity-report'),
            (Document.DocumentType.REPORT, 'report'),

            # Other
            (Document.DocumentType.OTHER, 'other'),
        ]

        for document_type, expected_spdx_type in test_cases:
            document = Document.objects.create(
                name=f'Test Document {document_type}',
                component=sample_component,
                document_type=document_type
            )
            assert document.spdx_reference_type == expected_spdx_type, \
                f'Document type {document_type} should map to {expected_spdx_type}'

    def test_get_external_reference_url(self, sample_component):
        """Test external reference URL generation."""
        document = Document.objects.create(
            name='Test Document',
            component=sample_component,
            document_type=Document.DocumentType.SPECIFICATION
        )

        expected_url = f'/api/v1/documents/{document.id}/download'
        assert document.get_external_reference_url() == expected_url

    def test_document_with_description(self, sample_component):
        """Test document with description field."""
        description = 'This is a test document for testing purposes'
        document = Document.objects.create(
            name='Test Document',
            component=sample_component,
            document_type=Document.DocumentType.SPECIFICATION,
            description=description
        )

        assert document.description == description

    def test_document_string_representation(self, sample_component):
        """Test document string representation."""
        document = Document.objects.create(
            name='Test Document',
            component=sample_component,
            document_type=Document.DocumentType.SPECIFICATION
        )

        assert str(document) == 'Test Document'

    def test_document_type_field_max_length(self, sample_component):
        """Test that document_type field has correct max_length."""
        # This should not raise an exception
        document = Document.objects.create(
            name='Test Document',
            component=sample_component,
            document_type='security-advisory'  # 17 chars, within 50 limit
        )

        # Test that it's stored correctly
        assert document.document_type == 'security-advisory'