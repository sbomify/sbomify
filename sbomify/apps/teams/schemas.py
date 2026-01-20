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
    """Schema representing a contact person tied to a contact entity.

    A contact can have multiple roles indicated by boolean flags:
    - is_author: Person who authored the SBOM
    - is_security_contact: Security/vulnerability reporting contact (CRA requirement)
    - is_technical_contact: Technical point of contact
    """

    name: str
    email: str  # Required
    phone: str | None = None
    order: int | None = None
    # Role flags - a contact can have multiple roles
    is_author: bool = False
    is_security_contact: bool = False
    is_technical_contact: bool = False


class AuthorContactSchema(BaseModel):
    """Schema representing an author contact (CycloneDX aligned).

    Authors are individuals, not organizations, and link directly to the profile.
    """

    name: str
    email: str  # Required
    phone: str | None = None
    order: int | None = None


class ContactEntitySchema(BaseModel):
    """Schema for a contact entity (organization/company).

    An entity can be a manufacturer, supplier, author, or a combination of roles.
    When is_author is the ONLY role, name and email are optional (authors are individuals).
    """

    id: str
    name: str | None = None  # Optional for author-only entities
    email: str | None = None  # Optional for author-only entities
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
    def validate_entity_role(self):
        if not (self.is_manufacturer or self.is_supplier or self.is_author):
            raise ValueError("At least one role (Manufacturer, Supplier, or Author) must be selected")
        return self


class ContactEntityCreateSchema(BaseModel):
    """Schema for creating a contact entity (CycloneDX aligned).

    When is_author is the ONLY role, name and email are optional.
    """

    name: str | None = Field(default=None, max_length=255)  # Optional for author-only
    email: str | None = Field(default=None, max_length=255)  # Optional for author-only
    phone: str | None = None
    address: str | None = None
    website_urls: list[str] = Field(default_factory=list)
    is_manufacturer: bool = False
    is_supplier: bool = False
    is_author: bool = False
    contacts: list[ContactProfileContactSchema] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entity_role(self):
        if not (self.is_manufacturer or self.is_supplier or self.is_author):
            raise ValueError("At least one role (Manufacturer, Supplier, or Author) must be selected")
        # If not author-only, name and email are required
        is_author_only = self.is_author and not self.is_manufacturer and not self.is_supplier
        if not is_author_only:
            if not self.name:
                raise ValueError("Entity name is required for Manufacturer/Supplier entities")
            if not self.email:
                raise ValueError("Entity email is required for Manufacturer/Supplier entities")
        return self


class ContactEntityUpdateSchema(BaseModel):
    """Schema for updating a contact entity (CycloneDX aligned)."""

    id: str | None = None  # For identifying existing entity
    name: str | None = Field(default=None, max_length=255)
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
        """Ensure entity has a valid role after update.

        For partial updates, we only validate when all role fields are provided.
        The model's clean() method provides final validation before save.
        """
        # If no role fields are provided, no validation needed (partial update preserves existing)
        if self.is_manufacturer is None and self.is_supplier is None and self.is_author is None:
            return self

        # If all role flags are provided and all are False, reject the update
        if (
            self.is_manufacturer is not None
            and self.is_supplier is not None
            and self.is_author is not None
            and not (self.is_manufacturer or self.is_supplier or self.is_author)
        ):
            raise ValueError("At least one role (Manufacturer, Supplier, or Author) must be selected")

        return self


class ContactProfileSchema(BaseModel):
    """Schema for returning workspace contact profiles (CycloneDX aligned)."""

    id: str
    name: str
    # Entity-based structure (manufacturer and supplier)
    entities: list[ContactEntitySchema] = Field(default_factory=list)
    # Authors (individuals, not organizations) - CycloneDX aligned
    authors: list[AuthorContactSchema] = Field(default_factory=list)
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
    is_component_private: bool = False  # True if profile is owned by a specific component
    created_at: str
    updated_at: str


class ContactProfileCreateSchema(BaseModel):
    """Schema for creating a workspace contact profile (CycloneDX aligned)."""

    name: str = Field(..., max_length=255, min_length=1)
    # Entity-based creation (manufacturer and supplier)
    entities: list[ContactEntityCreateSchema] | None = None
    # Authors (individuals) - CycloneDX aligned
    authors: list[AuthorContactSchema] = Field(default_factory=list)
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
    """Schema for updating a workspace contact profile (CycloneDX aligned)."""

    name: str | None = Field(default=None, max_length=255, min_length=1)
    # Entity-based updates - accepts both update (existing) and create (new) schemas
    entities: list[ContactEntityUpdateSchema | ContactEntityCreateSchema] | None = None
    # Authors (individuals) - CycloneDX aligned
    authors: list[AuthorContactSchema] | None = None
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
