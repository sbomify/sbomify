"""Tests for documents schemas."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from ..schemas import DocumentCreateSchema, DocumentResponseSchema, DocumentUploadRequest


class TestDocumentUploadRequest:
    """Test DocumentUploadRequest schema."""

    def test_valid_data(self):
        """Test valid document upload request."""
        data = {"id": "test-doc-123"}
        schema = DocumentUploadRequest(**data)
        assert schema.id == "test-doc-123"

    def test_serialization(self):
        """Test schema serialization."""
        data = {"id": "test-doc-123"}
        schema = DocumentUploadRequest(**data)
        assert schema.dict() == data

    def test_missing_id(self):
        """Test that id is required."""
        with pytest.raises(ValidationError) as exc_info:
            DocumentUploadRequest()

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("id",)
        assert errors[0]["type"] == "missing"

    def test_empty_id(self):
        """Test that empty id is accepted."""
        # Pydantic allows empty strings for str fields by default
        schema = DocumentUploadRequest(id="")
        assert schema.id == ""


class TestDocumentResponseSchema:
    """Test DocumentResponseSchema schema."""

    def test_valid_data(self):
        """Test valid document response."""
        data = {
            "id": "test-doc-123",
            "name": "Test Document",
            "version": "1.0",
            "document_filename": "test.pdf",
            "created_at": datetime.now(),
            "source": "manual_upload",
            "component_id": "comp-123",
            "document_type": "specification",
            "description": "Test document description",
            "content_type": "application/pdf",
            "file_size": 1024,
            "source_display": "Manual Upload",
        }
        schema = DocumentResponseSchema(**data)
        assert schema.id == "test-doc-123"
        assert schema.name == "Test Document"
        assert schema.version == "1.0"
        assert schema.document_filename == "test.pdf"
        assert schema.source == "manual_upload"
        assert schema.component_id == "comp-123"
        assert schema.document_type == "specification"
        assert schema.description == "Test document description"
        assert schema.content_type == "application/pdf"
        assert schema.file_size == 1024
        assert schema.source_display == "Manual Upload"

    def test_none_source(self):
        """Test document response with None source."""
        data = {
            "id": "test-doc-123",
            "name": "Test Document",
            "version": "1.0",
            "document_filename": "test.pdf",
            "created_at": datetime.now(),
            "source": None,
            "component_id": "comp-123",
            "document_type": "specification",
            "description": "Test document description",
            "content_type": "application/pdf",
            "file_size": None,
            "source_display": "Unknown",
        }
        schema = DocumentResponseSchema(**data)
        assert schema.source is None
        assert schema.file_size is None

    def test_serialization(self):
        """Test schema serialization."""
        data = {
            "id": "test-doc-123",
            "name": "Test Document",
            "version": "1.0",
            "document_filename": "test.pdf",
            "created_at": datetime.now(),
            "source": "manual_upload",
            "component_id": "comp-123",
            "document_type": "specification",
            "description": "Test document description",
            "content_type": "application/pdf",
            "file_size": 1024,
            "source_display": "Manual Upload",
        }
        schema = DocumentResponseSchema(**data)
        serialized = schema.dict()

        assert serialized["id"] == "test-doc-123"
        assert serialized["name"] == "Test Document"
        assert serialized["version"] == "1.0"
        assert serialized["document_filename"] == "test.pdf"
        assert serialized["source"] == "manual_upload"
        assert serialized["component_id"] == "comp-123"
        assert serialized["document_type"] == "specification"
        assert serialized["description"] == "Test document description"
        assert serialized["content_type"] == "application/pdf"
        assert serialized["file_size"] == 1024
        assert serialized["source_display"] == "Manual Upload"

    def test_missing_required_fields(self):
        """Test that required fields are validated."""
        with pytest.raises(ValidationError) as exc_info:
            DocumentResponseSchema()

        errors = exc_info.value.errors()
        required_fields = [
            "id", "name", "version", "document_filename", "created_at",
            "component_id", "document_type", "description", "content_type",
            "source_display"
        ]

        error_fields = [error["loc"][0] for error in errors]
        for field in required_fields:
            assert field in error_fields

    def test_invalid_created_at(self):
        """Test invalid created_at field."""
        data = {
            "id": "test-doc-123",
            "name": "Test Document",
            "version": "1.0",
            "document_filename": "test.pdf",
            "created_at": "invalid-date",
            "source": "manual_upload",
            "component_id": "comp-123",
            "document_type": "specification",
            "description": "Test document description",
            "content_type": "application/pdf",
            "file_size": 1024,
            "source_display": "Manual Upload",
        }

        with pytest.raises(ValidationError) as exc_info:
            DocumentResponseSchema(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("created_at",) for error in errors)

    def test_invalid_file_size(self):
        """Test invalid file_size field."""
        data = {
            "id": "test-doc-123",
            "name": "Test Document",
            "version": "1.0",
            "document_filename": "test.pdf",
            "created_at": datetime.now(),
            "source": "manual_upload",
            "component_id": "comp-123",
            "document_type": "specification",
            "description": "Test document description",
            "content_type": "application/pdf",
            "file_size": "invalid-size",
            "source_display": "Manual Upload",
        }

        with pytest.raises(ValidationError) as exc_info:
            DocumentResponseSchema(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("file_size",) for error in errors)


class TestDocumentCreateSchema:
    """Test DocumentCreateSchema schema."""

    def test_valid_data(self):
        """Test valid document creation."""
        data = {
            "name": "Test Document",
            "version": "1.0",
            "document_type": "specification",
            "description": "Test document description",
        }
        schema = DocumentCreateSchema(**data)
        assert schema.name == "Test Document"
        assert schema.version == "1.0"
        assert schema.document_type == "specification"
        assert schema.description == "Test document description"

    def test_minimal_data(self):
        """Test document creation with minimal required data."""
        data = {
            "name": "Test Document",
            "version": "1.0",
        }
        schema = DocumentCreateSchema(**data)
        assert schema.name == "Test Document"
        assert schema.version == "1.0"
        assert schema.document_type == ""
        assert schema.description == ""

    def test_empty_optional_fields(self):
        """Test document creation with empty optional fields."""
        data = {
            "name": "Test Document",
            "version": "1.0",
            "document_type": "",
            "description": "",
        }
        schema = DocumentCreateSchema(**data)
        assert schema.name == "Test Document"
        assert schema.version == "1.0"
        assert schema.document_type == ""
        assert schema.description == ""

    def test_none_optional_fields(self):
        """Test document creation with None optional fields."""
        data = {
            "name": "Test Document",
            "version": "1.0",
            "document_type": None,
            "description": None,
        }
        schema = DocumentCreateSchema(**data)
        assert schema.name == "Test Document"
        assert schema.version == "1.0"
        # When None is explicitly provided, it's preserved
        assert schema.document_type is None
        assert schema.description is None

    def test_serialization(self):
        """Test schema serialization."""
        data = {
            "name": "Test Document",
            "version": "1.0",
            "document_type": "specification",
            "description": "Test document description",
        }
        schema = DocumentCreateSchema(**data)
        serialized = schema.dict()

        assert serialized["name"] == "Test Document"
        assert serialized["version"] == "1.0"
        assert serialized["document_type"] == "specification"
        assert serialized["description"] == "Test document description"

    def test_missing_required_fields(self):
        """Test that required fields are validated."""
        with pytest.raises(ValidationError) as exc_info:
            DocumentCreateSchema()

        errors = exc_info.value.errors()
        required_fields = ["name", "version"]

        error_fields = [error["loc"][0] for error in errors]
        for field in required_fields:
            assert field in error_fields

    def test_empty_name(self):
        """Test that empty name is accepted."""
        # Pydantic allows empty strings for str fields by default
        schema = DocumentCreateSchema(name="", version="1.0")
        assert schema.name == ""
        assert schema.version == "1.0"

    def test_empty_version(self):
        """Test that empty version is accepted."""
        # Pydantic allows empty strings for str fields by default
        schema = DocumentCreateSchema(name="Test Document", version="")
        assert schema.name == "Test Document"
        assert schema.version == ""

    def test_long_fields(self):
        """Test document creation with long field values."""
        data = {
            "name": "A" * 1000,
            "version": "1.0",
            "document_type": "B" * 1000,
            "description": "C" * 5000,
        }
        schema = DocumentCreateSchema(**data)
        assert schema.name == "A" * 1000
        assert schema.version == "1.0"
        assert schema.document_type == "B" * 1000
        assert schema.description == "C" * 5000

    def test_special_characters(self):
        """Test document creation with special characters."""
        data = {
            "name": "Test Document with émojis 🚀 and spëcial chars",
            "version": "1.0-beta+build.123",
            "document_type": "spécification",
            "description": "Test with 特殊字符 and émojis 🎉",
        }
        schema = DocumentCreateSchema(**data)
        assert schema.name == "Test Document with émojis 🚀 and spëcial chars"
        assert schema.version == "1.0-beta+build.123"
        assert schema.document_type == "spécification"
        assert schema.description == "Test with 特殊字符 and émojis 🎉"