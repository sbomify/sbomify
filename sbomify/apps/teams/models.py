import uuid
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db import models
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.utils import generate_id, number_to_random_token


def format_workspace_name(name: str) -> str:
    """
    Format a workspace name from a given name/company.

    This function centralizes workspace naming to support future i18n.
    The possessive format (name's Workspace) may need locale-specific
    handling for languages that don't use apostrophe-s for possession.

    Args:
        name: The name to use (company name, user's first name, etc.)

    Returns:
        A formatted workspace name string
    """
    # TODO: Before launching in non-English markets, use django.utils.translation.gettext and
    # consider locale-specific possessive patterns
    return f"{name}'s Workspace"


def get_team_name_for_user(user) -> str:
    """
    Get the team name for a user based on available information.

    Prioritizes first_name, then extracts a clean name from username
    (handling email-based usernames like "user@example.com" or "user.example.com").

    Args:
        user: The user to generate a team name for

    Returns:
        A human-friendly team name string
    """
    if user.first_name:
        return format_workspace_name(user.first_name)

    if hasattr(user, "username") and user.username:
        # Extract clean name from email-based usernames
        # Examples:
        #   "john@example.com" -> "john"
        #   "john.example.com" -> "john"
        #   "john.example.com_1" -> "john"
        #   "alice" -> "alice"
        username = user.username

        # First, remove any numbered suffix (e.g., "_1", "_2")
        if "_" in username:
            username = username.split("_")[0]

        # Then extract the part before @ or . (whichever comes first)
        if "@" in username:
            name = username.split("@")[0]
        elif "." in username:
            name = username.split(".")[0]
        else:
            name = username

        return format_workspace_name(name)

    return "My Workspace"


class Team(models.Model):
    class Plan(models.TextChoices):
        COMMUNITY = "community", "Community"
        BUSINESS = "business", "Business"
        ENTERPRISE = "enterprise", "Enterprise"

    class Meta:
        db_table = apps.get_app_config("teams").label + "_teams"
        indexes = [
            models.Index(fields=["key"]),
            models.Index(fields=["custom_domain"]),
            # Composite index for verification task queries
            models.Index(fields=["custom_domain_validated", "custom_domain_last_checked_at"]),
            # Dashboard and analytics indexes
            models.Index(fields=["created_at"]),
            models.Index(fields=["billing_plan"]),
            models.Index(fields=["is_public"]),
        ]
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    # Both IDs present
                    (
                        models.Q(billing_plan_limits__stripe_subscription_id__isnull=False)
                        & models.Q(billing_plan_limits__stripe_customer_id__isnull=False)
                    )
                    |
                    # Both IDs null
                    (
                        models.Q(billing_plan_limits__stripe_subscription_id__isnull=True)
                        & models.Q(billing_plan_limits__stripe_customer_id__isnull=True)
                    )
                ),
                name="valid_billing_relationship",
            )
        ]

    key = models.CharField(max_length=30, unique=True, null=True, validators=[MinLengthValidator(9)])
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    branding_info = models.JSONField(default=dict)
    has_completed_wizard = models.BooleanField(default=False)
    onboarding_goal = models.TextField(blank=True, default="")
    is_public = models.BooleanField(
        default=True, help_text="Controls whether the workspace Trust Center is publicly accessible."
    )
    billing_plan = models.CharField(max_length=30, null=True, choices=Plan.choices)
    billing_plan_limits = models.JSONField(null=True)  # As enterprise plan can have varying limits
    has_selected_billing_plan = models.BooleanField(default=False)
    custom_domain = models.CharField(max_length=255, unique=True, null=True, blank=True)
    custom_domain_validated = models.BooleanField(default=False)
    custom_domain_verification_failures = models.PositiveIntegerField(default=0)
    custom_domain_last_checked_at = models.DateTimeField(null=True, blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, through="Member")

    def __str__(self) -> str:
        return f"{self.name} ({self.pk})"

    @property
    def display_name(self) -> str:
        """
        User-friendly workspace name.

        Removes a trailing "'s Workspace"/"’s Workspace"/"Workspace" suffix if present,
        otherwise returns the raw name. Avoids brittle substring replacement.
        """
        if not self.name:
            return "Workspace"

        trimmed = str(self.name).strip()
        lowered = trimmed.casefold()

        # Remove explicit "'s workspace"/"’s workspace" suffixes
        for suffix in ("'s workspace", "’s workspace"):
            if lowered.endswith(suffix):
                return trimmed[: -len(suffix)].rstrip()

        # Remove trailing "workspace" if it's the last word
        workspace_suffix = "workspace"
        if lowered.endswith(workspace_suffix):
            return trimmed[: -len(workspace_suffix)].rstrip(" -–—_:")

        return trimmed

    @property
    def public_url(self) -> str | None:
        """
        Return the public URL for this workspace's Trust Center.

        Returns:
            URL string if workspace is public and has a key, None otherwise.

        Usage:
            In templates: {{ team.public_url }}
            In views: team.public_url
        """
        if not self.key or not self.is_public:
            return None

        from django.urls import reverse

        return reverse("core:workspace_public", kwargs={"workspace_key": self.key})

    def can_be_private(self) -> bool:
        """
        Determine if this workspace can be set to private based on billing status.
        """
        plan = (self.billing_plan or "").strip().lower()
        if not plan:
            return False

        allowed_plans = {choice.value for choice in Team.Plan}
        if plan in allowed_plans:
            return plan != Team.Plan.COMMUNITY

        # Custom plan keys that exist in BillingPlan are treated as paid/allowed
        if BillingPlan.objects.filter(key__iexact=plan).exists():
            return True

        return False

    @property
    def is_in_grace_period(self):
        """Check if team is in payment grace period."""
        from django.conf import settings

        limits = self.billing_plan_limits or {}
        if limits.get("subscription_status") != "past_due":
            return False

        failed_at_str = limits.get("payment_failed_at")
        if not failed_at_str:
            # If past_due but no date, assume grace period (safe default vs lockout)
            return True

        try:
            import datetime

            failed_at = datetime.datetime.fromisoformat(failed_at_str)
            grace_days = getattr(settings, "PAYMENT_GRACE_PERIOD_DAYS", 3)
            return (timezone.now() - failed_at).days <= grace_days
        except (ValueError, TypeError):
            return True

    @property
    def is_payment_restricted(self):
        """Check if team is restricted due to payment failure (past grace period)."""
        limits = self.billing_plan_limits or {}
        if limits.get("subscription_status") != "past_due":
            return False
        return not self.is_in_grace_period

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        current_plan = (self.billing_plan or "").strip().lower()

        is_paid_plan = bool(current_plan) and current_plan != Team.Plan.COMMUNITY

        # Default paid plans to private only at creation time (opt-in later for upgrades)
        if is_new and is_paid_plan and self.is_public:
            self.is_public = False

        # Community or unset (anything not in paid plans) must remain public
        if (not self.can_be_private()) and (not self.is_public):
            self.is_public = True
            # If we're forcing public due to plan constraints, ensure it gets saved
            if "update_fields" in kwargs:
                # Convert to set to avoid duplicates, then list for compatibility
                fields = set(kwargs["update_fields"])
                fields.add("is_public")
                kwargs["update_fields"] = list(fields)

        # Track custom_domain changes for cache invalidation
        old_custom_domain = None
        if not is_new:
            try:
                old_instance = Team.objects.only("custom_domain").get(pk=self.pk)
                old_custom_domain = old_instance.custom_domain
            except Team.DoesNotExist:
                pass

        super().save(*args, **kwargs)

        # Invalidate cache if custom_domain changed
        new_custom_domain = self.custom_domain
        if old_custom_domain != new_custom_domain:
            from sbomify.apps.teams.utils import invalidate_custom_domain_cache

            # Invalidate both old and new domains
            if old_custom_domain:
                invalidate_custom_domain_cache(old_custom_domain)
            if new_custom_domain:
                invalidate_custom_domain_cache(new_custom_domain)

        if not is_new or self.key is not None:
            return

        self.key = number_to_random_token(self.pk)
        super().save(update_fields=["key"])

    def get_or_create_company_wide_component(self):
        """Get or create the company-wide component for storing company documents.

        This component is used to store company-wide documents like NDAs.
        It is not visible in normal component lists and has visibility=PUBLIC.

        Returns:
            Component instance for company-wide documents.
        """
        from sbomify.apps.sboms.models import Component

        component_name = "Workspace NDA"
        component, created = Component.objects.get_or_create(
            team=self,
            name=component_name,
            defaults={
                "component_type": Component.ComponentType.DOCUMENT,
                "visibility": Component.Visibility.PUBLIC,
                "is_global": True,
            },
        )

        # Ensure visibility is PUBLIC (update existing if needed)
        if component.visibility != Component.Visibility.PUBLIC:
            component.visibility = Component.Visibility.PUBLIC
            component.is_global = True
            component.save()
        elif created:
            component.is_global = True
            component.save()

        return component

    def get_company_nda_document(self):
        """Get the company-wide NDA document.

        Returns:
            Document instance or None if no company-wide NDA exists.
        """
        from sbomify.apps.documents.models import Document

        # Handle case where branding_info is None (can happen with legacy data)
        branding_info = self.branding_info or {}
        company_nda_id = branding_info.get("company_nda_document_id")
        if company_nda_id:
            try:
                return Document.objects.get(id=company_nda_id)
            except Document.DoesNotExist:
                pass

        return None

    def requires_nda_for_gated_access(self):
        """Check if this team requires NDA signing for gated access.

        Returns:
            bool: True if the workspace has a company-wide NDA document,
                  False otherwise.
        """
        return self.get_company_nda_document() is not None


class Member(models.Model):
    class Meta:
        db_table = apps.get_app_config("teams").label + "_members"
        unique_together = ("user", "team")
        indexes = [
            models.Index(fields=["team", "role"], name="teams_member_team_role_idx"),
        ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    role = models.CharField(max_length=255, choices=settings.TEAMS_SUPPORTED_ROLES)
    is_default_team = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user.username} - {self.team.name} ({self.team.pk})"


def calculate_invitation_expiry():
    return timezone.now() + timedelta(days=settings.INVITATION_EXPIRY_DAYS)


class Invitation(models.Model):
    class Meta:
        db_table = apps.get_app_config("teams").label + "_invitations"
        unique_together = ("team", "email")
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["expires_at"]),
        ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    email = models.EmailField()
    role = models.CharField(max_length=255, choices=settings.TEAMS_SUPPORTED_ROLES)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=calculate_invitation_expiry)

    def __str__(self) -> str:
        return f"{self.team.name}({self.team.pk}) - {self.email} - {self.role}"

    @property
    def has_expired(self) -> bool:
        """
        Check if the invitation has expired.
        """
        return timezone.now() > self.expires_at


class ContactProfile(models.Model):
    """Workspace-level contact profile shared across components.

    A profile contains one or more ContactEntity objects, each representing
    an organization, company, or individual with specific roles (manufacturer,
    supplier, author) and their associated contact persons.
    """

    class Meta:
        db_table = apps.get_app_config("teams").label + "_contact_profiles"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(is_default=True),
                name="unique_default_contact_profile_per_team",
            ),
            # Unique name per team, but only for shared (non-component-private) profiles
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(is_component_private=False),
                name="unique_shared_contact_profile_name_per_team",
            ),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="contact_profiles")
    name = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)
    is_component_private = models.BooleanField(
        default=False,
        help_text="If True, this profile is owned by a specific component and not shared at workspace level",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Ensure only one default profile per team and prevent component-private profiles from being default."""
        # Component-private profiles cannot be set as default
        if self.is_component_private:
            self.is_default = False
        elif self.is_default and self.team_id:
            ContactProfile.objects.filter(team=self.team, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.team_id})"


class ContactEntity(models.Model):
    """Entity (Organization/Company) within a contact profile.

    Represents an organization or company associated with a contact profile.
    An entity can be a manufacturer, supplier, author, or a combination of roles.
    Each profile can have at most one manufacturer and one supplier entity.
    Each entity must have at least one contact for communication info.

    Role types:
        - Manufacturer: Organization that manufactures the component
        - Supplier: Organization that supplies the component
        - Author: Group of individual authors (no organization info required)

    When is_author is the ONLY role selected:
        - name and email are optional (authors are individuals, not organizations)
        - Only contacts are required (the actual author individuals)
    """

    class Meta:
        db_table = apps.get_app_config("teams").label + "_contact_entities"
        unique_together = ("profile", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    profile = models.ForeignKey(ContactProfile, on_delete=models.CASCADE, related_name="entities")
    name = models.CharField(max_length=255, blank=True)  # Optional for author-only entities
    email = models.EmailField(blank=True)  # Optional for author-only entities
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    website_urls = models.JSONField(default=list, blank=True)
    is_manufacturer = models.BooleanField(default=False)
    is_supplier = models.BooleanField(default=False)
    is_author = models.BooleanField(
        default=False, help_text="Entity groups individual authors (no organization info required)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_author_only(self) -> bool:
        """Check if this entity only has the Author role (no Manufacturer/Supplier)."""
        return self.is_author and not self.is_manufacturer and not self.is_supplier

    def clean(self):
        """Validate entity constraints.

        Note: There's a theoretical race condition between validation and save.
        This is mitigated by the API layer using transactions (atomic blocks).
        For stricter enforcement, consider a database partial unique index.
        """
        from django.core.exceptions import ValidationError

        # At least one role must be selected
        if not (self.is_manufacturer or self.is_supplier or self.is_author):
            raise ValidationError("At least one role (Manufacturer, Supplier, or Author) must be selected")

        # If not author-only, name and email are required
        if not self.is_author_only:
            if not self.name:
                raise ValidationError("Entity name is required for Manufacturer/Supplier entities")
            if not self.email:
                raise ValidationError("Entity email is required for Manufacturer/Supplier entities")

        # Skip duplicate checks if profile is not saved yet (new profile creation)
        # For unsaved profiles, there can't be any existing entities anyway
        if not self.profile or not self.profile.pk:
            return

        if self.is_manufacturer:
            existing = ContactEntity.objects.filter(profile=self.profile, is_manufacturer=True).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError("A profile can have only one manufacturer entity")

        if self.is_supplier:
            existing = ContactEntity.objects.filter(profile=self.profile, is_supplier=True).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError("A profile can have only one supplier entity")

    def clean_contacts(self):
        """Validate contacts for CycloneDX compliance.

        Note: For backward compatibility with legacy API, entities without contacts
        are allowed. The new entity-based API enforces contacts in _upsert_entities().
        This method is kept for documentation but doesn't enforce the constraint.
        """
        pass

    def save(self, *args, **kwargs):
        """Override save to ensure validation is always called."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.profile_id})"


class ContactProfileContact(models.Model):
    """Contact person information associated with a contact entity.

    Represents an individual contact person within an entity. A contact can have
    multiple roles (author, security contact, technical contact) indicated by
    boolean flags. This allows the same person to serve multiple functions.

    Role flags:
        - is_author: Person who authored the SBOM (CycloneDX metadata.authors)
        - is_security_contact: Security/vulnerability reporting contact (CRA requirement)
        - is_technical_contact: Technical point of contact

    Constraints:
        - Only ONE security contact per profile (across all entities)
    """

    class Meta:
        db_table = apps.get_app_config("teams").label + "_contact_profile_contacts"
        unique_together = ("entity", "name", "email")
        ordering = ["order", "name"]
        indexes = [
            models.Index(fields=["is_author"], name="contact_is_author_idx"),
            models.Index(fields=["is_security_contact"], name="contact_is_security_idx"),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    entity = models.ForeignKey(ContactEntity, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # Role flags - a contact can have multiple roles
    is_author = models.BooleanField(
        default=False, help_text="Person who authored the SBOM (appears in metadata.authors)"
    )
    is_security_contact = models.BooleanField(
        default=False, help_text="Security/vulnerability reporting contact (CRA requirement). Only one per profile."
    )
    is_technical_contact = models.BooleanField(default=False, help_text="Technical point of contact")

    def clean(self):
        """Validate contact constraints.

        Ensures only one security contact exists per profile (across all entities).
        """
        from django.core.exceptions import ValidationError

        if not self.is_security_contact:
            return

        # Check if another security contact exists in this profile
        if not self.entity_id:
            return

        # Get the profile through the entity
        try:
            profile = self.entity.profile
        except (ContactEntity.DoesNotExist, AttributeError):
            return

        if not profile or not profile.pk:
            return

        # Find any existing security contact in this profile (across all entities)
        existing_security_contacts = ContactProfileContact.objects.filter(
            entity__profile=profile, is_security_contact=True
        ).exclude(pk=self.pk)

        if existing_security_contacts.exists():
            raise ValidationError(
                "A security contact already exists in this profile. "
                "Each profile can have only one security/vulnerability reporting contact."
            )

    def save(self, *args, **kwargs):
        """Override save to run validation by default.

        Set perform_validation=False to skip full_clean() for performance-sensitive
        bulk operations. Note: skipping validation bypasses the security contact
        uniqueness constraint.
        """
        perform_validation = kwargs.pop("perform_validation", True)
        if perform_validation:
            self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.entity_id})"
