from django.conf import settings
from pydantic import BaseModel, Field


class TeamUpdateSchema(BaseModel):
    """Schema for updating team information."""

    class Config:
        str_strip_whitespace = True

    name: str = Field(..., max_length=255, min_length=1)


class TeamPatchSchema(BaseModel):
    """Schema for partially updating team information."""

    class Config:
        str_strip_whitespace = True

    name: str | None = Field(None, max_length=255, min_length=1)


class TeamResponseSchema(BaseModel):
    """Schema for team response data."""

    key: str
    name: str
    created_at: str
    has_completed_wizard: bool
    billing_plan: str | None


class TeamListItemSchema(BaseModel):
    """Schema for team list item in dashboard."""

    key: str
    name: str
    role: str
    member_count: int
    invitation_count: int
    is_default_team: bool
    membership_id: str


class UserSchema(BaseModel):
    """Schema for user data."""

    id: int
    first_name: str
    last_name: str
    email: str


class MemberSchema(BaseModel):
    """Schema for team member data."""

    id: int
    user: UserSchema
    role: str
    is_default_team: bool


class InvitationSchema(BaseModel):
    """Schema for team invitation data."""

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
