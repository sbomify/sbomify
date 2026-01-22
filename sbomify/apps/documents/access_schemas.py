from pydantic import BaseModel, EmailStr, Field


class AccessRequestCreateRequest(BaseModel):
    """Request schema for creating an access request."""

    email: EmailStr | None = Field(None, description="Email for unauthenticated users (creates user account)")
    name: str | None = Field(None, description="Optional name for unauthenticated users")


class AccessRequestResponse(BaseModel):
    """Response schema for access request."""

    id: str
    team_id: str
    user_id: str
    status: str
    requested_at: str
    decided_at: str | None = None
    decided_by_id: str | None = None
    revoked_at: str | None = None
    revoked_by_id: str | None = None
    notes: str = ""


class NDASignRequest(BaseModel):
    """Request schema for signing NDA."""

    signed_name: str = Field(..., description="Name provided by user when signing")
    consent: bool = Field(..., description="User consent to NDA terms")


class NDASignatureResponse(BaseModel):
    """Response schema for NDA signature."""

    id: str
    access_request_id: str
    nda_document_id: str
    signed_name: str
    signed_at: str


class AccessRequestListResponse(BaseModel):
    """Response schema for listing access requests."""

    id: str
    team_id: str
    team_name: str
    user_id: str
    user_email: str
    user_name: str | None = None
    status: str
    requested_at: str
    decided_at: str | None = None
    decided_by_id: str | None = None
    decided_by_email: str | None = None
    has_nda_signature: bool = False
    notes: str = ""
