from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentUploadRequest(BaseModel):
    """Schema for document upload API response."""

    id: str


class DocumentResponseSchema(BaseModel):
    """Schema for Document API responses."""

    id: str
    name: str
    version: str
    document_filename: str
    created_at: datetime
    source: Optional[str]
    component_id: str
    component_name: str
    document_type: str
    description: str
    content_type: str
    file_size: Optional[int]
    source_display: str


class DocumentCreateSchema(BaseModel):
    """Schema for creating documents via API."""

    name: str
    version: str
    document_type: Optional[str] = ""
    description: Optional[str] = ""


class DocumentUpdateRequest(BaseModel):
    """Schema for updating document metadata via PATCH."""

    name: Optional[str] = None
    version: Optional[str] = None
    document_type: Optional[str] = None
    compliance_subcategory: Optional[str] = None
    description: Optional[str] = None
