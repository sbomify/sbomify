from django.apps import apps
from django.core.validators import URLValidator
from django.db import models

from sbomify.apps.core.utils import generate_id
from sbomify.apps.teams.models import Team

# LEGACY MODELS - kept here for data persistence only
# All logic has been moved to core app with proxy models
# Do not add new functionality here - use core.models instead


class Product(models.Model):
    """Legacy Product model for data persistence only."""

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_products"
        unique_together = ("team", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=False)
    description = models.TextField(blank=True, help_text="Optional product description")
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)
    projects = models.ManyToManyField("sboms.Project", through="sboms.ProductProject")

    def __str__(self) -> str:
        return f"{self.name}(Team ID: {self.team_id})"


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
        """Override save to ensure team consistency with product."""
        if self.product_id:
            self.team = self.product.team
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
        unique_together = ("team", "link_type", "url")
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

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_components"
        unique_together = ("team", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=False)
    component_type = models.CharField(
        max_length=20,
        choices=ComponentType.choices,
        default=ComponentType.SBOM,
        help_text="Type of component (SBOM, Document, etc.)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)

    # Native fields for contact information (migrated from JSONField)
    supplier_name = models.CharField(max_length=255, blank=True, null=True, help_text="The name of the supplier")
    supplier_url = models.JSONField(default=list, help_text="List of supplier URLs")
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

    # Keep the original metadata field for backward compatibility and migration
    metadata = models.JSONField(default=dict)
    projects = models.ManyToManyField(Project, through="sboms.ProjectComponent")

    def __str__(self) -> str:
        return f"{self.name}"

    @property
    def latest_sbom(self) -> "SBOM | None":
        """Get the latest SBOM for this component.

        Returns:
            The most recent SBOM object or None if no SBOMs exist.
        """
        return self.sbom_set.order_by("-created_at").first()


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
    """

    class NTIAComplianceStatus(models.TextChoices):
        """NTIA compliance status choices."""

        COMPLIANT = "compliant", "Compliant"
        NON_COMPLIANT = "non_compliant", "Non-Compliant"
        UNKNOWN = "unknown", "Unknown"

    class Meta:
        db_table = apps.get_app_config("sboms").label + "_sboms"
        ordering = ["-created_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    name = models.CharField(max_length=255, blank=False)  # qualified sbom name like com.github.sbomify/backend
    version = models.CharField(max_length=255, default="")
    format = models.CharField(max_length=255, default="spdx")  # spdx, cyclonedx, etc
    format_version = models.CharField(max_length=20, default="")
    sbom_filename = models.CharField(max_length=255, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    # Where the sbom came from (file-upload, api, github-action, etc)
    source = models.CharField(max_length=255, null=True)
    component = models.ForeignKey(Component, on_delete=models.CASCADE)

    # NTIA compliance fields
    ntia_compliance_status = models.CharField(
        max_length=20,
        choices=NTIAComplianceStatus.choices,
        default=NTIAComplianceStatus.UNKNOWN,
        help_text="NTIA minimum elements compliance status",
    )
    ntia_compliance_details = models.JSONField(
        default=dict, blank=True, help_text="Detailed NTIA compliance validation results"
    )
    ntia_compliance_checked_at = models.DateTimeField(
        null=True, blank=True, help_text="When the NTIA compliance check was last performed"
    )

    def __str__(self) -> str:
        return self.name

    @property
    def public_access_allowed(self) -> bool:
        """Check if public access is allowed for this SBOM.

        Returns:
            True if the component is public, False otherwise.
        """
        return self.component.is_public

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

    @property
    def is_ntia_compliant(self) -> bool:
        """Check if the SBOM is NTIA compliant.

        Returns:
            True if the SBOM is NTIA compliant, False otherwise.
        """
        return self.ntia_compliance_status == self.NTIAComplianceStatus.COMPLIANT

    @property
    def ntia_compliance_display(self) -> str:
        """Return a user-friendly display name for NTIA compliance status.

        Returns:
            A human-readable string representing the NTIA compliance status.
        """
        return self.get_ntia_compliance_status_display()

    def get_ntia_compliance_errors(self) -> list:
        """Get NTIA compliance errors from the details.

        Returns:
            List of NTIA compliance errors.
        """
        if not self.ntia_compliance_details:
            return []
        return self.ntia_compliance_details.get("errors", [])

    def get_ntia_compliance_error_count(self) -> int:
        """Get the number of NTIA compliance errors.

        Returns:
            Number of NTIA compliance errors.
        """
        return len(self.get_ntia_compliance_errors())

    def needs_ntia_compliance_check(self) -> bool:
        """Check if the SBOM needs an NTIA compliance check.

        Returns:
            True if the SBOM needs to be checked for NTIA compliance.
        """
        return self.ntia_compliance_status == self.NTIAComplianceStatus.UNKNOWN
