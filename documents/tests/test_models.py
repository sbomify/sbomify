import pytest

from sboms.models import Component
from teams.fixtures import sample_team  # noqa: F401

from ..models import Document


@pytest.mark.django_db
def test_document_creation(sample_team):  # noqa: F811
    """Test creating a document with all fields."""
    # Create a document component
    component = Component.objects.create(
        name="Test Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
    )

    document = Document.objects.create(
        name="Test Document",
        version="1.0",
        document_filename="test_doc.pdf",
        component=component,
        source="manual_upload",
        document_type="specification",
        description="Test document description",
        content_type="application/pdf",
        file_size=1024,
    )

    assert document.id is not None
    assert document.name == "Test Document"
    assert document.version == "1.0"
    assert document.document_filename == "test_doc.pdf"
    assert document.component == component
    assert document.source == "manual_upload"
    assert document.document_type == "specification"
    assert document.description == "Test document description"
    assert document.content_type == "application/pdf"
    assert document.file_size == 1024


@pytest.mark.django_db
def test_document_str_representation(sample_team):  # noqa: F811
    """Test the string representation of a document."""
    component = Component.objects.create(
        name="Test Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
    )

    document = Document.objects.create(
        name="Test Document",
        version="1.0",
        document_filename="test_doc.pdf",
        component=component,
    )

    assert str(document) == "Test Document"


@pytest.mark.django_db
def test_document_public_access_allowed(sample_team):  # noqa: F811
    """Test the public_access_allowed property."""
    # Create a private component
    private_component = Component.objects.create(
        name="Private Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        is_public=False,
    )

    # Create a public component
    public_component = Component.objects.create(
        name="Public Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        is_public=True,
    )

    private_document = Document.objects.create(
        name="Private Document",
        version="1.0",
        document_filename="private_doc.pdf",
        component=private_component,
    )

    public_document = Document.objects.create(
        name="Public Document",
        version="1.0",
        document_filename="public_doc.pdf",
        component=public_component,
    )

    assert not private_document.public_access_allowed
    assert public_document.public_access_allowed


@pytest.mark.django_db
def test_document_source_display(sample_team):  # noqa: F811
    """Test the source_display property."""
    component = Component.objects.create(
        name="Test Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
    )

    # Test API source
    api_document = Document.objects.create(
        name="API Document",
        version="1.0",
        document_filename="api_doc.pdf",
        component=component,
        source="api",
    )

    # Test manual upload source
    manual_document = Document.objects.create(
        name="Manual Document",
        version="1.0",
        document_filename="manual_doc.pdf",
        component=component,
        source="manual_upload",
    )

    # Test unknown source
    unknown_document = Document.objects.create(
        name="Unknown Document",
        version="1.0",
        document_filename="unknown_doc.pdf",
        component=component,
        source="unknown_source",
    )

    # Test None source
    none_document = Document.objects.create(
        name="None Document",
        version="1.0",
        document_filename="none_doc.pdf",
        component=component,
        source=None,
    )

    assert api_document.source_display == "API"
    assert manual_document.source_display == "Manual Upload"
    assert unknown_document.source_display == "unknown_source"
    assert none_document.source_display == "Unknown"


@pytest.mark.django_db
def test_document_defaults(sample_team):  # noqa: F811
    """Test document creation with default values."""
    component = Component.objects.create(
        name="Test Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
    )

    document = Document.objects.create(
        name="Minimal Document",
        component=component,
    )

    assert document.version == ""
    assert document.document_filename == ""
    assert document.source is None
    assert document.document_type == Document.DocumentType.OTHER
    assert document.description == ""
    assert document.content_type == ""
    assert document.file_size is None
    assert document.created_at is not None


@pytest.mark.django_db
def test_document_ordering(sample_team):  # noqa: F811
    """Test that documents are ordered by created_at descending."""
    component = Component.objects.create(
        name="Test Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
    )

    # Create documents in sequence
    doc1 = Document.objects.create(
        name="First Document",
        component=component,
    )

    doc2 = Document.objects.create(
        name="Second Document",
        component=component,
    )

    doc3 = Document.objects.create(
        name="Third Document",
        component=component,
    )

    # Query all documents and check ordering
    documents = list(Document.objects.all())

    # Should be ordered by created_at descending (newest first)
    assert documents[0] == doc3
    assert documents[1] == doc2
    assert documents[2] == doc1