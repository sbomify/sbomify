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
    is_public = models.BooleanField(
        default=True, help_text="Controls whether the workspace Trust Center is publicly accessible."
    )
    billing_plan = models.CharField(max_length=30, null=True, choices=Plan.choices)
    billing_plan_limits = models.JSONField(null=True)  # As enterprise plan can have varying limits
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


class Member(models.Model):
    class Meta:
        db_table = apps.get_app_config("teams").label + "_members"
        unique_together = ("user", "team")

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
        unique_together = ("team", "name")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(is_default=True),
                name="unique_default_contact_profile_per_team",
            )
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="contact_profiles")
    name = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Ensure only one default profile per team."""
        if self.is_default and self.team_id:
            ContactProfile.objects.filter(team=self.team, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.team_id})"


class ContactEntity(models.Model):
    """Entity (Organization/Company) within a contact profile.

    Represents an organization or company associated with a contact profile.
    An entity can be a manufacturer, supplier, or both (same entity fulfilling both roles).
    Each profile can have at most one manufacturer and one supplier entity.
    Each entity must have at least one contact for communication info.
    """

    class Meta:
        db_table = apps.get_app_config("teams").label + "_contact_entities"
        unique_together = ("profile", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    profile = models.ForeignKey(ContactProfile, on_delete=models.CASCADE, related_name="entities")
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    website_urls = models.JSONField(default=list, blank=True)
    is_manufacturer = models.BooleanField(default=False)
    is_supplier = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        """Validate entity constraints."""
        from django.core.exceptions import ValidationError

        if not (self.is_manufacturer or self.is_supplier):
            raise ValidationError("At least one role (Manufacturer or Supplier) must be selected")

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

    Represents an individual contact person within an entity, such as a technical
    lead, security contact, or business contact.
    """

    class Meta:
        db_table = apps.get_app_config("teams").label + "_contact_profile_contacts"
        unique_together = ("entity", "name", "email")
        ordering = ["order", "name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    entity = models.ForeignKey(ContactEntity, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.entity_id})"


class AuthorContact(models.Model):
    """Author contact information linked directly to a contact profile.

    Represents an individual author of an SBOM (CycloneDX aligned).
    Authors are individuals, not organizations, so they link directly to the profile
    rather than through an entity.
    """

    class Meta:
        db_table = apps.get_app_config("teams").label + "_author_contacts"
        unique_together = ("profile", "name", "email")
        ordering = ["order", "name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    profile = models.ForeignKey(ContactProfile, on_delete=models.CASCADE, related_name="authors")
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.profile_id})"
