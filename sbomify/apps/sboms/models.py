from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.utils.text import slugify

from sbomify.apps.core.utils import generate_id
from sbomify.apps.teams.models import Team

# LEGACY MODELS - kept here primarily for data persistence.
# Note: While the goal is to move logic to the core app, some domain properties
# (e.g., visibility, access control) currently reside here during migration.
# Exercise caution when adding new business logic.


def check_identifier_collision(team, identifier_type: str, value: str, exclude_model: str, exclude_pk=None) -> None:
    """Check if an identifier would collide with existing product or component identifiers.

    Args:
        team: The team to check within
        identifier_type: The type of identifier (e.g., 'sku', 'purl')
        value: The identifier value
        exclude_model: Either 'product' or 'component' - the model to exclude from checks
        exclude_pk: Optional primary key to exclude (for updates)

    Raises:
        ValidationError: If a collision is detected
    """
    if exclude_model != "product":
        # Check ProductIdentifier
        qs = ProductIdentifier.objects.filter(
            team=team,
            identifier_type=identifier_type,
            value=value,
        )
        if qs.exists():
            raise ValidationError(
                f"An identifier of type '{identifier_type}' with value '{value}' "
                "already exists for a product in this workspace."
            )

    if exclude_model != "component":
        # Check ComponentIdentifier - use late import to avoid circular dependency
        qs = ComponentIdentifier.objects.filter(
            team=team,
            identifier_type=identifier_type,
            value=value,
        )
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if qs.exists():
            raise ValidationError(
                f"An identifier of type '{identifier_type}' with value '{value}' "
                "already exists for a component in this workspace."
            )


class Product(models.Model):
    """Legacy Product model for data persistence only."""

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_products"
        unique_together = ("team", "name")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_public"]),
            models.Index(fields=["team", "created_at"]),
            models.Index(fields=["team", "is_public"]),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=False)
    description = models.TextField(blank=True, help_text="Optional product description")
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)
    projects = models.ManyToManyField("sboms.Project", through="sboms.ProductProject")

    # Lifecycle event fields (aligned with Common Lifecycle Enumeration)
    release_date = models.DateField(blank=True, null=True, help_text="Release date of the product")
    end_of_support = models.DateField(
        blank=True, null=True, help_text="Date when bugfixes stop (security-only after this)"
    )
    end_of_life = models.DateField(blank=True, null=True, help_text="Date when all support ends")

    def __str__(self) -> str:
        return f"{self.name}(Team ID: {self.team_id})"

    @property
    def slug(self) -> str:
        """Generate a URL-safe slug from the product name.

        Note: This is computed on each access rather than cached because:
        1. Caching could return stale values if name changes
        2. slugify() overhead is minimal for typical usage
        3. For high-traffic scenarios, consider adding a database slug field

        Returns:
            URL-safe slug string derived from the product name.
        """
        return slugify(self.name, allow_unicode=True)


class ProductIdentifier(models.Model):
    """Model to store various product identifiers like GTIN, SKU, MPN, etc."""

    class IdentifierType(models.TextChoices):
        """Types of product identifiers."""

        GTIN_12 = "gtin_12", "GTIN-12 (UPC-A)"
        GTIN_13 = "gtin_13", "GTIN-13 (EAN-13)"
        GTIN_14 = "gtin_14", "GTIN-14 / ITF-14"
        GTIN_8 = "gtin_8", "GTIN-8"
        SKU = "sku", "SKU"
        MPN = "mpn", "MPN"
        ASIN = "asin", "ASIN"
        GS1_GPC_BRICK = "gs1_gpc_brick", "GS1 GPC Brick code"
        CPE = "cpe", "CPE"
        PURL = "purl", "PURL"

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_product_identifiers"
        unique_together = ("team", "identifier_type", "value")
        ordering = ["identifier_type", "value"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="identifiers")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    identifier_type = models.CharField(
        max_length=20, choices=IdentifierType.choices, help_text="Type of product identifier"
    )
    value = models.CharField(max_length=255, help_text="The identifier value")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.get_identifier_type_display()}: {self.value}"

    def save(self, *args, **kwargs):
        """Override save to ensure team consistency with product and check for collisions."""
        if self.product_id:
            self.team = self.product.team
        # Check for collision with ComponentIdentifier
        check_identifier_collision(
            team=self.team,
            identifier_type=self.identifier_type,
            value=self.value,
            exclude_model="product",
            exclude_pk=self.pk,
        )
        super().save(*args, **kwargs)


class ProductLink(models.Model):
    """Model to store various product links like website, support, documentation, etc."""

    class LinkType(models.TextChoices):
        """Types of product links."""

        WEBSITE = "website", "Website"
        SUPPORT = "support", "Support"
        DOCUMENTATION = "documentation", "Documentation"
        REPOSITORY = "repository", "Repository"
        CHANGELOG = "changelog", "Changelog"
        RELEASE_NOTES = "release_notes", "Release Notes"
        SECURITY = "security", "Security"
        ISSUE_TRACKER = "issue_tracker", "Issue Tracker"
        DOWNLOAD = "download", "Download"
        CHAT = "chat", "Chat/Community"
        SOCIAL = "social", "Social Media"
        OTHER = "other", "Other"

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_product_links"
        ordering = ["link_type", "title"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="links")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    link_type = models.CharField(max_length=20, choices=LinkType.choices, help_text="Type of product link")
    title = models.CharField(max_length=255, help_text="Display title for the link")
    url = models.URLField(max_length=500, help_text="The URL", validators=[URLValidator()])
    description = models.TextField(blank=True, help_text="Optional description of the link")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.get_link_type_display()}: {self.title}"

    def save(self, *args, **kwargs):
        """Override save to ensure team consistency with product."""
        if self.product_id:
            self.team = self.product.team
        super().save(*args, **kwargs)


class Project(models.Model):
    """Legacy Project model for data persistence only."""

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_projects"
        unique_together = ("team", "name")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_public"]),
            models.Index(fields=["team", "created_at"]),
            models.Index(fields=["team", "is_public"]),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    products = models.ManyToManyField(Product, through="sboms.ProductProject")
    components = models.ManyToManyField("sboms.Component", through="sboms.ProjectComponent")

    def __str__(self) -> str:
        return f"<{self.id}> {self.name}"

    @property
    def slug(self) -> str:
        """Generate a URL-safe slug from the project name.

        Note: Computed property - see Product.slug for rationale.

        Returns:
            URL-safe slug string derived from the project name.
        """
        return slugify(self.name, allow_unicode=True)


class ProductProject(models.Model):
    """Legacy ProductProject through model for data persistence only."""

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_products_projects"
        unique_together = ("product", "project")

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return f"{self.product_id} - {self.project_id}"


class ComponentSupplierContact(models.Model):
    """Contact information for component suppliers."""

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_component_supplier_contacts"
        unique_together = ("component", "name", "email")
        ordering = ["order", "name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    component = models.ForeignKey("Component", on_delete=models.CASCADE, related_name="supplier_contacts")
    name = models.CharField(max_length=255, help_text="The name of the contact")
    email = models.EmailField(blank=True, null=True, help_text="The email address of the contact")
    phone = models.CharField(max_length=50, blank=True, null=True, help_text="The phone number of the contact")
    bom_ref = models.CharField(
        max_length=255, blank=True, null=True, help_text="BOM reference identifier for CycloneDX"
    )
    order = models.PositiveIntegerField(default=0, help_text="Order of the contact in the list")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.component.name})"


class ComponentAuthor(models.Model):
    """Author/contributor information for components."""

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_component_authors"
        unique_together = ("component", "name", "email")
        ordering = ["order", "name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    component = models.ForeignKey("Component", on_delete=models.CASCADE, related_name="authors")
    name = models.CharField(max_length=255, help_text="The name of the author")
    email = models.EmailField(blank=True, null=True, help_text="The email address of the author")
    phone = models.CharField(max_length=50, blank=True, null=True, help_text="The phone number of the author")
    bom_ref = models.CharField(
        max_length=255, blank=True, null=True, help_text="BOM reference identifier for CycloneDX"
    )
    order = models.PositiveIntegerField(default=0, help_text="Order of the author in the list")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.component.name})"


class ComponentLicense(models.Model):
    """License information for components."""

    class LicenseType(models.TextChoices):
        SPDX = "spdx", "SPDX License"
        CUSTOM = "custom", "Custom License"
        EXPRESSION = "expression", "License Expression"

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_component_licenses"
        ordering = ["order", "license_id"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    component = models.ForeignKey("Component", on_delete=models.CASCADE, related_name="licenses")
    license_type = models.CharField(max_length=10, choices=LicenseType.choices, help_text="Type of license")

    # For SPDX licenses and expressions
    license_id = models.CharField(max_length=255, blank=True, null=True, help_text="SPDX license ID or expression")

    # For custom licenses
    license_name = models.CharField(max_length=255, blank=True, null=True, help_text="Custom license name")
    license_url = models.URLField(blank=True, null=True, help_text="Custom license URL")
    license_text = models.TextField(blank=True, null=True, help_text="Custom license text")

    # Common fields
    bom_ref = models.CharField(
        max_length=255, blank=True, null=True, help_text="BOM reference identifier for CycloneDX"
    )
    order = models.PositiveIntegerField(default=0, help_text="Order of the license in the list")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        if self.license_type == self.LicenseType.SPDX:
            return f"{self.license_id} ({self.component.name})"
        elif self.license_type == self.LicenseType.CUSTOM:
            return f"{self.license_name} ({self.component.name})"
        else:  # expression
            return f"{self.license_id} ({self.component.name})"

    def to_dict(self):
        """Convert license to dictionary format for API responses."""
        if self.license_type == self.LicenseType.SPDX:
            return self.license_id
        elif self.license_type == self.LicenseType.EXPRESSION:
            return self.license_id
        else:  # custom
            result = {"name": self.license_name}
            if self.license_url:
                result["url"] = self.license_url
            if self.license_text:
                result["text"] = self.license_text
            return result


class Component(models.Model):
    """Legacy Component model for data persistence only.

    Represents a component which can be of different types such as SBOM or Document.
    All business logic has been moved to core app with proxy models.
    """

    class ComponentType(models.TextChoices):
        """Enumeration of available component types."""

        SBOM = "sbom", "SBOM"
        DOCUMENT = "document", "Document"

    class Visibility(models.TextChoices):
        """Component visibility levels."""

        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"
        GATED = "gated", "Gated"

    class GatingMode(models.TextChoices):
        """Gating mode for gated components."""

        APPROVAL_ONLY = "approval_only", "Approval Only"
        APPROVAL_PLUS_NDA = "approval_plus_nda", "Approval + NDA"

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_components"
        unique_together = ("team", "name")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["visibility"]),
            models.Index(fields=["team", "created_at"]),
            models.Index(fields=["team", "visibility"]),
            models.Index(fields=["component_type"]),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    contact_profile = models.ForeignKey(
        "teams.ContactProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="components",
        help_text="Workspace contact profile linked to this component",
    )
    name = models.CharField(max_length=255, blank=False)
    component_type = models.CharField(
        max_length=20,
        choices=ComponentType.choices,
        default=ComponentType.SBOM,
        help_text="Type of component (SBOM, Document, etc.)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
        help_text="Component visibility level",
    )
    gating_mode = models.CharField(
        max_length=20,
        choices=GatingMode.choices,
        null=True,
        blank=True,
        help_text="Gating mode for gated components (only applies when visibility=gated)",
    )
    nda_document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="component_ndas",
        help_text="Component-specific NDA document (if null and gating_mode=approval_plus_nda, uses company-wide NDA)",
    )
    is_global = models.BooleanField(
        default=False,
        help_text="Whether the component is available at the workspace level rather than scoped to a project",
    )

    # Native fields for contact information (migrated from JSONField)
    supplier_name = models.CharField(max_length=255, blank=True, null=True, help_text="The name of the supplier")
    supplier_url = models.JSONField(default=list, blank=True, help_text="List of supplier URLs")
    supplier_address = models.TextField(blank=True, null=True, help_text="The address of the supplier")
    lifecycle_phase = models.CharField(
        max_length=20,
        choices=[
            ("design", "Design"),
            ("pre-build", "Pre-Build"),
            ("build", "Build"),
            ("post-build", "Post-Build"),
            ("operations", "Operations"),
            ("discovery", "Discovery"),
            ("decommission", "Decommission"),
        ],
        blank=True,
        null=True,
        help_text="The lifecycle phase of the component",
    )

    # Lifecycle event fields (aligned with Common Lifecycle Enumeration)
    release_date = models.DateField(blank=True, null=True, help_text="Release date of the component")
    end_of_support = models.DateField(
        blank=True, null=True, help_text="Date when bugfixes stop (security-only after this)"
    )
    end_of_life = models.DateField(blank=True, null=True, help_text="Date when all support ends")

    # Keep the original metadata field for backward compatibility and migration
    metadata = models.JSONField(default=dict, blank=True)
    projects = models.ManyToManyField(Project, through="sboms.ProjectComponent")

    def __str__(self) -> str:
        return f"{self.name}"

    def clean(self):
        """Validate model fields.

        This is called explicitly via full_clean() in forms/serializers.
        Not called automatically in save() to avoid breaking bulk operations and migrations.
        """
        from django.core.exceptions import ValidationError

        super().clean()

        # gating_mode can only be set when visibility is gated
        if self.visibility != self.Visibility.GATED and self.gating_mode:
            raise ValidationError({"gating_mode": "gating_mode can only be set when visibility is gated"})

        # nda_document can only be set when gating_mode is approval_plus_nda
        if self.gating_mode != self.GatingMode.APPROVAL_PLUS_NDA and self.nda_document_id:
            raise ValidationError(
                {"nda_document": "nda_document can only be set when gating_mode is approval_plus_nda"}
            )

    def save(self, *args, **kwargs):
        """Override save to auto-clear invalid field combinations.

        Instead of raising validation errors, we auto-clear fields when parent
        conditions change. This provides better UX and prevents invalid states.

        Note: This does NOT call full_clean() to avoid:
        - Breaking bulk operations (update(), bulk_create(), bulk_update())
        - Breaking migrations that create Component objects
        - Causing N+1 queries from unique constraint validation
        - Breaking existing tests

        Validation should be done explicitly via full_clean() in forms/serializers/APIs.
        """
        # Auto-clear gating_mode if visibility is not gated
        if self.visibility != self.Visibility.GATED:
            if self.gating_mode:
                self.gating_mode = None
            if self.nda_document_id:
                self.nda_document = None
        # Auto-clear nda_document if gating_mode is not approval_plus_nda
        elif self.gating_mode != self.GatingMode.APPROVAL_PLUS_NDA:
            if self.nda_document_id:
                self.nda_document = None

        super().save(*args, **kwargs)

    @property
    def slug(self) -> str:
        """Generate a URL-safe slug from the component name.

        Note: Computed property - see Product.slug for rationale.

        Returns:
            URL-safe slug string derived from the component name.
        """
        return slugify(self.name, allow_unicode=True)

    @property
    def latest_sbom(self) -> "SBOM | None":
        """Get the latest SBOM for this component.

        Returns:
            The most recent SBOM object or None if no SBOMs exist.
        """
        return self.sbom_set.order_by("-created_at").first()

    @property
    def public_access_allowed(self) -> bool:
        """Check if public access is allowed for this component.

        Gated components are publicly viewable (accessible via public URL)
        but downloads require access approval.

        Returns:
            True if the component visibility is public or gated, False otherwise.
        """
        return self.visibility in (self.Visibility.PUBLIC, self.Visibility.GATED)

    @property
    def is_gated(self) -> bool:
        """Check if component is gated.

        Returns:
            True if visibility is gated, False otherwise.
        """
        return self.visibility == self.Visibility.GATED

    @property
    def is_visible_to_guest_members(self) -> bool:
        """Check if component is visible to guest members.

        Guest members can see public and gated components, but not private.

        Returns:
            True if visible to guest members, False otherwise.
        """
        return self.visibility in (self.Visibility.PUBLIC, self.Visibility.GATED)

    def requires_nda(self) -> bool:
        """Check if component requires NDA signing.

        Returns:
            True if gating_mode is approval_plus_nda, False otherwise.
        """
        return self.gating_mode == self.GatingMode.APPROVAL_PLUS_NDA

    def get_nda_document(self):
        """Get the NDA document for this component.

        Returns component-specific NDA if set, otherwise company-wide NDA from team.

        Returns:
            Document instance or None if no NDA exists.
        """
        if self.nda_document_id:
            return self.nda_document

        from sbomify.apps.documents.models import Document

        company_nda_id = self.team.branding_info.get("company_nda_document_id")
        if company_nda_id:
            try:
                return Document.objects.get(id=company_nda_id)
            except Document.DoesNotExist:
                # Document was deleted or ID is invalid, return None
                pass

        return None

    def get_company_nda_document(self):
        """Get the company-wide NDA document from team.

        Returns:
            Document instance or None if no company-wide NDA exists.
        """
        from sbomify.apps.documents.models import Document

        company_nda_id = self.team.branding_info.get("company_nda_document_id")
        if company_nda_id:
            try:
                return Document.objects.get(id=company_nda_id)
            except Document.DoesNotExist:
                # Document was deleted or ID is invalid, return None
                pass

        return None

    def can_be_accessed_by(self, user, team=None):
        """Check if component can be accessed by user.

        DEPRECATED: Use check_component_access() from core.services.access_control instead.
        This method is kept for backward compatibility but will be removed in a future version.

        Args:
            user: User instance to check access for
            team: Optional team instance (uses self.team if not provided)

        Returns:
            True if user can access, False otherwise.
        """
        if not team:
            team = self.team

        # Use centralized access control logic
        from sbomify.apps.core.services.access_control import _check_gated_access

        if self.visibility == self.Visibility.PUBLIC:
            return True

        if self.visibility == self.Visibility.GATED:
            if not user or not user.is_authenticated:
                return False
            has_access, _ = _check_gated_access(user, team)
            return has_access

        if self.visibility == self.Visibility.PRIVATE:
            if not user or not user.is_authenticated:
                return False
            # For private components, check owner/admin access
            from sbomify.apps.teams.models import Member

            try:
                member = Member.objects.get(team=team, user=user)
                return member.role in ("owner", "admin")
            except Member.DoesNotExist:
                return False

        return False

    def user_has_gated_access(self, user, team=None):
        """Check if user has gated access to this component.

        DEPRECATED: Use check_component_access() from core.services.access_control instead.
        This method is kept for backward compatibility but will be removed in a future version.

        Args:
            user: User instance to check access for
            team: Optional team instance (uses self.team if not provided)

        Returns:
            True if user has gated access, False otherwise.
        """
        if not team:
            team = self.team

        if not user or not user.is_authenticated:
            return False

        # Use centralized access control logic
        from sbomify.apps.core.services.access_control import _check_gated_access

        has_access, _ = _check_gated_access(user, team)
        return has_access


class ComponentIdentifier(models.Model):
    """Model to store various component identifiers like CPE, PURL, SKU, etc.

    Note: Identifiers at the component level are version-less. They identify the
    component itself, not a specific version. Versions are tracked on SBOMs.
    For example, PURL should be 'pkg:npm/@scope/package' without the @version suffix.
    """

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_component_identifiers"
        unique_together = ("team", "identifier_type", "value")
        ordering = ["identifier_type", "value"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    component = models.ForeignKey(Component, on_delete=models.CASCADE, related_name="identifiers")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    identifier_type = models.CharField(
        max_length=20, choices=ProductIdentifier.IdentifierType.choices, help_text="Type of component identifier"
    )
    value = models.CharField(max_length=255, help_text="The identifier value (version-less)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.get_identifier_type_display()}: {self.value}"

    def save(self, *args, **kwargs):
        """Override save to ensure team consistency with component and check for collisions."""
        if self.component_id:
            self.team = self.component.team
        # Check for collision with ProductIdentifier
        check_identifier_collision(
            team=self.team,
            identifier_type=self.identifier_type,
            value=self.value,
            exclude_model="component",
            exclude_pk=self.pk,
        )
        super().save(*args, **kwargs)


class ProjectComponent(models.Model):
    """Legacy ProjectComponent through model for data persistence only."""

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_projects_components"
        unique_together = ("project", "component")

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    component = models.ForeignKey(Component, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return f"{self.project_id} - {self.component_id}"


class SBOM(models.Model):
    """Represents a Software Bill of Materials (SBOM) artifact associated with a component.

    SBOMs are versioned artifacts that contain detailed information about software components,
    dependencies, and their relationships. They can be in various formats (SPDX, CycloneDX, etc.).

    License Data Handling Note (2025-05-29):
    Previously, this model included `licenses` (JSONField) and `packages_licenses` (JSONField)
    to store parsed and categorized license information. This approach had limitations,
    especially with complex SPDX license expressions and custom licenses, leading to
    potential inaccuracies.

    These fields have been removed as part of a transition towards a more robust system
    for license data management. The future direction is to accurately store and process
    standardized license expressions (e.g., SPDX license expressions like "MIT OR Apache-2.0")
    as directly declared in the SBOM, rather than attempting to parse and pre-categorize them.
    This change aims to improve accuracy and adherence to SBOM format specifications.
    The related statistics and detailed license breakdowns on the frontend have also been
    temporarily removed pending this new implementation.

    NTIA Compliance Note (2026-01):
    NTIA compliance checking has been migrated to the plugin-based assessment framework
    (ADR-003). Results are now stored in AssessmentRun records via the plugins app.
    Use the `assessment_runs` related manager to query NTIA compliance results.
    """

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_sboms"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["component", "created_at"]),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    name = models.CharField(max_length=255, blank=False)  # qualified sbom name like com.github.sbomify/backend
    version = models.CharField(max_length=255, default="")
    format = models.CharField(max_length=255, default="spdx")  # spdx, cyclonedx, etc
    format_version = models.CharField(max_length=20, default="")
    sbom_filename = models.CharField(max_length=255, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    # Where the sbom came from (file-upload, api, github-action, etc)
    source = models.CharField(max_length=255, null=True)
    sha256_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="SHA-256 hash of the SBOM file content",
    )
    component = models.ForeignKey(Component, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return self.name

    @property
    def public_access_allowed(self) -> bool:
        """Check if public access is allowed for this SBOM.

        Returns:
            True if the component visibility is public, False otherwise.
        """
        return self.component.visibility == Component.Visibility.PUBLIC

    @property
    def source_display(self) -> str:
        """Return a user-friendly display name for the source.

        Returns:
            A human-readable string representing the SBOM source.
        """
        source_display_map = {
            "api": "API",
            "manual_upload": "Manual Upload",
        }
        return source_display_map.get(self.source, self.source or "Unknown")
