from django.conf import settings
from pydantic import BaseModel, Field

from core.schemas import PaginationMeta


class TeamUpdateSchema(BaseModel):
    """Schema for updating workspace information.

    Note: This schema is used for workspaces (previously called teams).
    """

    class Config:
        str_strip_whitespace = True

    name: str = Field(..., max_length=255, min_length=1)


class TeamPatchSchema(BaseModel):
    """Schema for partially updating workspace information.

    Note: This schema is used for workspaces (previously called teams).
    """

    class Config:
        str_strip_whitespace = True

    name: str | None = Field(None, max_length=255, min_length=1)


class TeamResponseSchema(BaseModel):
    """Schema for workspace response data.

    Note: This schema is used for workspaces (previously called teams).
    """

    key: str
    name: str
    created_at: str
    has_completed_wizard: bool
    billing_plan: str | None


class TeamListItemSchema(BaseModel):
    """Schema for workspace list item in dashboard.

    Note: This schema is used for workspaces (previously called teams).
    """

    key: str
    name: str
    role: str
    member_count: int
    invitation_count: int
    product_count: int
    project_count: int
    component_count: int
    is_default_team: bool
    membership_id: str


class UserSchema(BaseModel):
    """Schema for user data."""

    id: int
    first_name: str
    last_name: str
    email: str


class MemberSchema(BaseModel):
    """Schema for workspace member data.

    Note: This schema is used for workspace members (workspaces were previously called teams).
    """

    id: int
    user: UserSchema
    role: str
    is_default_team: bool


class InvitationSchema(BaseModel):
    """Schema for workspace invitation data.

    Note: This schema is used for workspace invitations (workspaces were previously called teams).
    """

    id: int
    email: str
    role: str
    created_at: str
    expires_at: str


class BrandingInfo(BaseModel):
    icon: str = ""
    logo: str = ""
    prefer_logo_over_icon: bool | None = None
    brand_color: str = ""
    accent_color: str = ""

    @property
    def brand_icon_url(self) -> str:
        if self.icon:
            return f"{settings.AWS_ENDPOINT_URL_S3}/{settings.AWS_MEDIA_STORAGE_BUCKET_NAME}/{self.icon}"

        return ""

    @property
    def brand_logo_url(self) -> str:
        if self.logo:
            return f"{settings.AWS_ENDPOINT_URL_S3}/{settings.AWS_MEDIA_STORAGE_BUCKET_NAME}/{self.logo}"

        return ""

    @property
    def brand_image(self) -> str:
        if self.icon and self.logo:
            return self.brand_logo_url if self.prefer_logo_over_icon else self.brand_icon_url
        elif self.icon:
            return self.brand_icon_url
        elif self.logo:
            return self.brand_logo_url
        else:
            return ""


class BrandingInfoWithUrls(BrandingInfo):
    icon_url: str = ""
    logo_url: str = ""


class PaginatedTeamsResponse(BaseModel):
    """Paginated response for teams/workspaces list."""

    items: list[TeamListItemSchema]
    pagination: PaginationMeta


class DependencyTrackServerCreateSchema(BaseModel):
    """Schema for creating a new DT server."""

    class Config:
        str_strip_whitespace = True

    name: str = Field(..., max_length=255, min_length=1)
    url: str = Field(..., max_length=500, min_length=1)
    api_key: str = Field(..., max_length=255, min_length=1)
    priority: int = Field(100, ge=1, le=1000)
    max_concurrent_scans: int = Field(100, ge=1, le=1000)


class DependencyTrackServerUpdateSchema(BaseModel):
    """Schema for updating a DT server."""

    class Config:
        str_strip_whitespace = True

    name: str | None = Field(None, max_length=255, min_length=1)
    url: str | None = Field(None, max_length=500, min_length=1)
    api_key: str | None = Field(None, max_length=255, min_length=1)
    priority: int | None = Field(None, ge=1, le=1000)
    max_concurrent_scans: int | None = Field(None, ge=1, le=1000)


class DependencyTrackServerSchema(BaseModel):
    """Schema for DT server response."""

    id: str
    name: str
    url: str
    is_active: bool
    priority: int
    max_concurrent_scans: int
    current_scan_count: int
    health_status: str
    last_health_check: str | None = None
    created_at: str
    updated_at: str

    # For security, we don't expose the API key
    api_key_set: bool = Field(description="Whether an API key is configured")


class DependencyTrackServerListSchema(BaseModel):
    """Schema for listing DT servers."""

    servers: list[DependencyTrackServerSchema]
