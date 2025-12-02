from datetime import datetime

from django.conf import settings
from pydantic import BaseModel, Field

from sbomify.apps.billing.config import is_billing_enabled


class TeamUpdateSchema(BaseModel):
    """Schema for updating workspace information.

    Note: This schema is used for workspaces (previously called teams).
    """

    class Config:
        str_strip_whitespace = True

    name: str = Field(..., max_length=255, min_length=1)
    is_public: bool | None = None


class TeamPatchSchema(BaseModel):
    """Schema for partially updating workspace information.

    Note: This schema is used for workspaces (previously called teams).
    """

    class Config:
        str_strip_whitespace = True

    name: str | None = Field(None, max_length=255, min_length=1)
    is_public: bool | None = None


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
    is_public: bool
    created_at: datetime
    has_completed_wizard: bool
    billing_plan: str | None
    billing_plan_limits: dict | None
    can_be_private: bool
    custom_domain: str | None
    custom_domain_validated: bool = False
    custom_domain_verification_failures: int = 0
    custom_domain_last_checked_at: datetime | None = None
    members: list[MemberSchema]
    invitations: list[InvitationSchema]

    def can_be_private(self) -> bool:
        """
        Mirror Team.can_be_private for schema instances (used by views/templates).
        Billing-disabled environments always allow private; otherwise any non-community,
        non-blank plan may be private.
        """
        if not is_billing_enabled():
            return True
        plan = (self.billing_plan or "").strip().lower()
        if not plan:
            return False
        return plan != "community"


class TeamDomainSchema(BaseModel):
    """Schema for updating workspace custom domain."""

    domain: str = Field(..., max_length=255)


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


class UpdateTeamBrandingSchema(BaseModel):
    brand_color: str | None = None
    accent_color: str | None = None
    prefer_logo_over_icon: bool = False
    icon_pending_deletion: bool = False
    logo_pending_deletion: bool = False


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
