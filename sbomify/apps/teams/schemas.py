from datetime import datetime

from django.conf import settings
from pydantic import BaseModel, Field


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
    is_me: bool = False


class InvitationSchema(BaseModel):
    """Schema for workspace invitation data.

    Note: This schema is used for workspace invitations (workspaces were previously called teams).
    """

    id: int
    email: str
    role: str
    created_at: datetime
    expires_at: datetime


class TeamSchema(BaseModel):
    key: str
    name: str
    created_at: datetime
    has_completed_wizard: bool
    billing_plan: str | None
    billing_plan_limits: dict | None
    members: list[MemberSchema]
    invitations: list[InvitationSchema]


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


class ContactProfileContactSchema(BaseModel):
    """Schema representing a contact tied to a workspace contact profile."""

    name: str
    email: str | None = None
    phone: str | None = None
    order: int | None = None


class ContactProfileSchema(BaseModel):
    """Schema for returning workspace contact profiles."""

    id: str
    name: str
    company: str | None = None
    supplier_name: str | None = None
    vendor: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    website_urls: list[str] = Field(default_factory=list)
    contacts: list[ContactProfileContactSchema] = Field(default_factory=list)
    is_default: bool = False
    created_at: str
    updated_at: str


class ContactProfileCreateSchema(BaseModel):
    """Schema for creating a workspace contact profile."""

    name: str = Field(..., max_length=255, min_length=1)
    company: str | None = Field(default=None, max_length=255)
    supplier_name: str | None = Field(default=None, max_length=255)
    vendor: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None)
    website_urls: list[str] = Field(default_factory=list)
    contacts: list[ContactProfileContactSchema] = Field(default_factory=list)
    is_default: bool = False


class ContactProfileUpdateSchema(BaseModel):
    """Schema for updating a workspace contact profile."""

    name: str | None = Field(default=None, max_length=255, min_length=1)
    company: str | None = Field(default=None, max_length=255)
    supplier_name: str | None = Field(default=None, max_length=255)
    vendor: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None)
    website_urls: list[str] | None = None
    contacts: list[ContactProfileContactSchema] | None = None
    is_default: bool | None = None
