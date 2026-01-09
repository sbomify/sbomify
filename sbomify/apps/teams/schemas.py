from datetime import datetime

from django.conf import settings
from pydantic import BaseModel, Field, model_validator


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
    token: str
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
    can_set_private: bool | None = None
    custom_domain: str | None
    custom_domain_validated: bool = False
    custom_domain_verification_failures: int = 0
    custom_domain_last_checked_at: datetime | None = None
    members: list[MemberSchema]
    invitations: list[InvitationSchema]


class TeamDomainSchema(BaseModel):
    """Schema for updating workspace custom domain."""

    domain: str = Field(..., max_length=255)


class BrandingInfo(BaseModel):
    icon: str = ""
    logo: str = ""
    prefer_logo_over_icon: bool = False
    branding_enabled: bool = False
    brand_color: str = ""
    accent_color: str = ""
    trust_center_description: str = ""

    @property
    def brand_icon_url(self) -> str:
        if self.icon:
            return _build_media_url(self.icon)
        return ""

    @property
    def brand_logo_url(self) -> str:
        return _build_media_url(self.logo)

    @property
    def brand_image(self) -> str:
        """Primary brand image for public pages (logo-first, icon as fallback)."""
        if self.logo:
            return self.brand_logo_url
        if self.icon:
            return self.brand_icon_url
        return ""


class BrandingInfoWithUrls(BrandingInfo):
    icon_url: str = ""
    logo_url: str = ""


def _build_media_url(key: str) -> str:
    """Construct a public media URL for branding assets."""
    if not key:
        return ""

    bucket_url = getattr(settings, "AWS_MEDIA_STORAGE_BUCKET_URL", None)
    if bucket_url:
        return f"{bucket_url.rstrip('/')}/{key.lstrip('/')}"
    return ""


class UpdateTeamBrandingSchema(BaseModel):
    brand_color: str | None = None
    accent_color: str | None = None
    prefer_logo_over_icon: bool = False
    branding_enabled: bool | None = None
    icon_pending_deletion: bool = False
    logo_pending_deletion: bool = False
    trust_center_description: str | None = None


class ContactProfileContactSchema(BaseModel):
    """Schema representing a contact person tied to a contact entity."""

    name: str
    email: str  # Required
    phone: str | None = None
    order: int | None = None


class ContactEntitySchema(BaseModel):
    """Schema for a contact entity (organization/company/individual)."""

    id: str
    name: str  # Required
    email: str  # Required
    phone: str | None = None
    address: str | None = None
    website_urls: list[str] = Field(default_factory=list)
    is_manufacturer: bool = False
    is_supplier: bool = False
    is_author: bool = False
    contacts: list[ContactProfileContactSchema] = Field(default_factory=list)
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def validate_at_least_one_role(self):
        if not (self.is_manufacturer or self.is_supplier or self.is_author):
            raise ValueError("At least one role flag must be True")
        return self


class ContactEntityCreateSchema(BaseModel):
    """Schema for creating a contact entity."""

    name: str = Field(..., max_length=255, min_length=1)  # Required
    email: str = Field(..., max_length=255)  # Required
    phone: str | None = None
    address: str | None = None
    website_urls: list[str] = Field(default_factory=list)
    is_manufacturer: bool = False
    is_supplier: bool = False
    is_author: bool = False
    contacts: list[ContactProfileContactSchema] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_at_least_one_role(self):
        if not (self.is_manufacturer or self.is_supplier or self.is_author):
            raise ValueError("At least one of is_manufacturer, is_supplier, or is_author must be True")
        return self


class ContactEntityUpdateSchema(BaseModel):
    """Schema for updating a contact entity."""

    id: str | None = None  # For identifying existing entity
    name: str | None = Field(default=None, max_length=255, min_length=1)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = None
    address: str | None = None
    website_urls: list[str] | None = None
    is_manufacturer: bool | None = None
    is_supplier: bool | None = None
    is_author: bool | None = None
    contacts: list[ContactProfileContactSchema] | None = None

    @model_validator(mode="after")
    def validate_roles(self):
        """Ensure at least one role flag is True after update.

        For partial updates, we validate that if any role fields are provided,
        at least one of the provided fields must be True. This prevents turning
        off all roles in a single update. The model's clean() method will enforce
        final validation before saving.
        """
        # If no role fields are provided, no validation needed (partial update preserves existing)
        if self.is_manufacturer is None and self.is_supplier is None and self.is_author is None:
            return self

        # Check if all provided role fields are False
        provided_manufacturer = self.is_manufacturer if self.is_manufacturer is not None else None
        provided_supplier = self.is_supplier if self.is_supplier is not None else None
        provided_author = self.is_author if self.is_author is not None else None

        # Collect only the provided (non-None) values
        provided_roles = [v for v in [provided_manufacturer, provided_supplier, provided_author] if v is not None]

        # If we have provided role values and all are False, raise error
        if provided_roles and not any(provided_roles):
            raise ValueError("At least one of is_manufacturer, is_supplier, or is_author must be True")

        return self


class ContactProfileSchema(BaseModel):
    """Schema for returning workspace contact profiles."""

    id: str
    name: str
    # New field for entity-based structure
    entities: list[ContactEntitySchema] = Field(default_factory=list)
    # Legacy fields for backward compatibility (populated from first entity)
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
    # New field for entity-based creation
    entities: list[ContactEntityCreateSchema] | None = None
    # Legacy fields for backward compatibility
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
    # New field for entity-based updates - accepts both update (existing) and create (new) schemas
    entities: list[ContactEntityUpdateSchema | ContactEntityCreateSchema] | None = None
    # Legacy fields for backward compatibility
    company: str | None = Field(default=None, max_length=255)
    supplier_name: str | None = Field(default=None, max_length=255)
    vendor: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None)
    website_urls: list[str] | None = None
    contacts: list[ContactProfileContactSchema] | None = None
    is_default: bool | None = None
