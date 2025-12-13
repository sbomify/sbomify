from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from sbomify.apps.core.utils import generate_id

# Import the original models to create proxy models
from sbomify.apps.sboms.models import (
    Component as SbomComponent,
)
from sbomify.apps.sboms.models import (
    Product as SbomProduct,
)
from sbomify.apps.sboms.models import (
    ProductProject as SbomProductProject,
)
from sbomify.apps.sboms.models import (
    Project as SbomProject,
)
from sbomify.apps.sboms.models import (
    ProjectComponent as SbomProjectComponent,
)

# Release constants
LATEST_RELEASE_NAME = "latest"
DEFAULT_LATEST_DESCRIPTION = "Automatically updated release containing the latest artifacts from all components"


class User(AbstractUser):
    """Custom user model."""

    email_verified = models.BooleanField(default=False)
    """Whether the user's email has been verified."""

    class Meta:
        db_table = "core_users"


# Proxy models for sbom entities - provides clean core app interface
# while keeping data in original sbom tables for backward compatibility


class Product(SbomProduct):
    """Proxy model for sboms.Product - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"


class Project(SbomProject):
    """Proxy model for sboms.Project - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"


class Component(SbomComponent):
    """Proxy model for sboms.Component - moved to core app for better organization.

    Components contain artifacts, which can be either SBOMs or Documents.
    """

    class Meta:
        proxy = True
        app_label = "core"

    def get_latest_sboms_by_format(self) -> dict:
        """Get the latest SBOM for each format (CycloneDX, SPDX, etc.).

        Returns:
            Dict mapping format names to their latest SBOM objects.
            Example: {'cyclonedx': <SBOM>, 'spdx': <SBOM>}
        """
        from django.db.models import Max

        # Get the latest created_at for each format
        latest_by_format = self.sbom_set.values("format").annotate(latest_created=Max("created_at"))

        latest_sboms = {}
        for format_info in latest_by_format:
            format_name = format_info["format"]
            latest_created = format_info["latest_created"]

            # Get the actual SBOM object for this format and creation time
            sbom = self.sbom_set.filter(format=format_name, created_at=latest_created).first()

            if sbom:
                latest_sboms[format_name] = sbom

        return latest_sboms

    def get_latest_documents_by_type(self) -> dict:
        """Get the latest Document for each document type (FCC, CE, etc.).

        Returns:
            Dict mapping document types to their latest Document objects.
            Example: {'fcc': <Document>, 'ce': <Document>}
        """
        from django.db.models import Max

        from sbomify.apps.documents.models import Document

        # Get the latest created_at for each document type
        latest_by_type = (
            Document.objects.filter(component=self).values("document_type").annotate(latest_created=Max("created_at"))
        )

        latest_documents = {}
        for type_info in latest_by_type:
            doc_type = type_info["document_type"] or "default"  # Handle empty document_type
            latest_created = type_info["latest_created"]

            # Get the actual Document object for this type and creation time
            document = Document.objects.filter(
                component=self,
                document_type=type_info["document_type"],  # Use original value (may be empty string)
                created_at=latest_created,
            ).first()

            if document:
                latest_documents[doc_type] = document

        return latest_documents

    def get_latest_artifacts_by_type(self) -> dict:
        """Get the latest artifacts of each type/format for this component.

        Returns:
            Dict with 'sboms' and 'documents' keys containing the latest artifacts.
            Example: {
                'sboms': {'cyclonedx': <SBOM>, 'spdx': <SBOM>},
                'documents': {'fcc': <Document>, 'ce': <Document>}
            }
        """
        return {"sboms": self.get_latest_sboms_by_format(), "documents": self.get_latest_documents_by_type()}

    def get_all_artifacts(self):
        """Get all artifacts (SBOMs and Documents) for this component ordered by creation date.

        Returns:
            A list of all artifacts (both SBOMs and Documents) ordered by most recent first.
        """
        from sbomify.apps.documents.models import Document

        artifacts = []

        # Add all SBOMs
        for sbom in self.sbom_set.all():
            artifacts.append(sbom)

        # Add all Documents
        for document in Document.objects.filter(component=self):
            artifacts.append(document)

        # Sort by created_at descending (most recent first)
        artifacts.sort(key=lambda x: x.created_at, reverse=True)

        return artifacts

    def get_artifacts_by_type(self, artifact_type: str):
        """Get artifacts of a specific type.

        Args:
            artifact_type: Either 'sbom' or 'document'

        Returns:
            QuerySet of artifacts of the specified type.
        """
        if artifact_type.lower() == "sbom":
            return self.sbom_set.order_by("-created_at")
        elif artifact_type.lower() == "document":
            from sbomify.apps.documents.models import Document

            return Document.objects.filter(component=self).order_by("-created_at")
        else:
            raise ValueError("artifact_type must be either 'sbom' or 'document'")

    def get_products(self):
        """Get all products that contain this component through projects.

        Returns:
            QuerySet of Product objects that contain this component.
        """
        # Components are related to products through projects
        # Component -> Projects -> Products
        return Product.objects.filter(projects__components=self).distinct()


class ProductProject(SbomProductProject):
    """Proxy model for sboms.ProductProject - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"


class ProjectComponent(SbomProjectComponent):
    """Proxy model for sboms.ProjectComponent - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"


# New Release models


class Release(models.Model):
    """Represents a release of a product containing specific artifacts."""

    class Meta:
        db_table = "core_releases"
        unique_together = ("product", "name")
        ordering = [models.F("released_at").desc(nulls_last=True), "-created_at"]
        indexes = [
            models.Index(fields=["product", "-released_at"], name="core_rel_prod_released_idx"),
            models.Index(fields=["is_latest"], name="core_rel_is_latest_idx"),
            models.Index(fields=["is_prerelease"], name="core_rel_is_prerel_idx"),
            models.Index(fields=["product", "is_latest"], name="core_rel_prod_latest_idx"),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="releases")
    name = models.CharField(max_length=255, help_text="Release name (e.g., 'v1.0.0', 'latest')")
    description = models.TextField(blank=True, help_text="Optional release description")
    created_at = models.DateTimeField(default=timezone.now, help_text="When this release record was created")
    released_at = models.DateTimeField(blank=True, null=True, help_text="When this release became available")
    is_latest = models.BooleanField(
        default=False, help_text="Whether this is the default 'latest' release that auto-updates with new artifacts"
    )
    is_prerelease = models.BooleanField(
        default=False, help_text="Whether this is a pre-release version (alpha, beta, RC, etc.)"
    )

    def __str__(self) -> str:
        return f"{self.product.name} - {self.name}"

    @property
    def slug(self) -> str:
        """Generate a URL-safe slug from the release name.

        Note: Computed property - see Product.slug in sboms/models.py for rationale.

        Returns:
            URL-safe slug string derived from the release name.
        """
        return slugify(self.name, allow_unicode=True)

    def clean(self):
        """Ensure only one latest release per product and valid release dates."""
        if self.is_latest:
            # Check if another release is already marked as latest for this product
            existing_latest = Release.objects.filter(product=self.product, is_latest=True).exclude(pk=self.pk)

            if existing_latest.exists():
                raise ValidationError("A product can only have one latest release.")

        if self.created_at and self.released_at and self.released_at < self.created_at:
            raise ValidationError("Release date cannot be earlier than creation date.")

    def save(self, *args, **kwargs):
        if not self.created_at:
            self.created_at = timezone.now()

        if self._state.adding and self.released_at is None:
            # Default release date to creation time for new records only
            self.released_at = self.created_at

        self.clean()
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_latest_release(cls, product: "Product") -> "Release":
        """Get or create the default 'latest' release for a product.

        Args:
            product: The product to get/create the latest release for

        Returns:
            The latest release for the product
        """
        latest_release, created = cls.objects.get_or_create(
            product=product,
            name=LATEST_RELEASE_NAME,
            defaults={
                "is_latest": True,
                "description": DEFAULT_LATEST_DESCRIPTION,
            },
        )

        if created:
            # If we created a new latest release, refresh its artifacts
            latest_release.refresh_latest_artifacts()

        return latest_release

    def refresh_latest_artifacts(self):
        """Refresh this release to contain the latest artifacts from all components in the product.

        This method should only be called on releases marked as is_latest=True.
        It replaces all current artifacts with the latest ones from each component.
        """
        if not self.is_latest:
            raise ValueError("refresh_latest_artifacts() can only be called on latest releases")

        # Clear existing artifacts
        self.artifacts.all().delete()

        # Get all components that belong to this product (via projects)
        components = Component.objects.filter(projects__products=self.product).distinct()

        for component in components:
            # Add latest artifacts from each component
            self._add_latest_artifacts_from_component(component)

    def _add_latest_artifacts_from_component(self, component: "Component"):
        """Add the latest artifacts from a component to this release.

        Args:
            component: The component to add artifacts from
        """
        # Add latest SBOMs by format
        latest_sboms = component.get_latest_sboms_by_format()
        for format_name, sbom in latest_sboms.items():
            ReleaseArtifact.objects.create(release=self, sbom=sbom)

        # Add latest Documents by type
        latest_documents = component.get_latest_documents_by_type()
        for doc_type, document in latest_documents.items():
            ReleaseArtifact.objects.create(release=self, document=document)

    def add_artifact_to_latest_release(self, artifact):
        """Add or update an artifact in the latest release.

        This method handles adding a new artifact to the latest release,
        replacing any existing artifact of the same type/format from the same component.

        Args:
            artifact: SBOM or Document instance to add
        """
        if not self.is_latest:
            raise ValueError("add_artifact_to_latest_release() can only be called on latest releases")

        # Determine if this is an SBOM or Document
        if hasattr(artifact, "format"):  # SBOM
            # Remove any existing SBOM of the same format from the same component
            self.artifacts.filter(sbom__component=artifact.component, sbom__format=artifact.format).delete()

            # Add the new SBOM
            ReleaseArtifact.objects.create(release=self, sbom=artifact)

        elif hasattr(artifact, "document_type"):  # Document
            # Remove any existing Document of the same type from the same component
            self.artifacts.filter(
                document__component=artifact.component, document__document_type=artifact.document_type
            ).delete()

            # Add the new Document
            ReleaseArtifact.objects.create(release=self, document=artifact)

    def get_artifacts(self):
        """Get all artifacts (ReleaseArtifact objects) in this release.

        Returns:
            QuerySet of ReleaseArtifact objects ordered by creation date.
        """
        return self.artifacts.order_by("-created_at")

    def get_sboms(self):
        """Get all SBOM objects in this release.

        Returns:
            List of SBOM objects from the release artifacts.
        """
        sbom_artifacts = self.artifacts.filter(sbom__isnull=False).select_related("sbom")
        return [artifact.sbom for artifact in sbom_artifacts]

    def get_documents(self):
        """Get all Document objects in this release.

        Returns:
            List of Document objects from the release artifacts.
        """
        document_artifacts = self.artifacts.filter(document__isnull=False).select_related("document")
        return [artifact.document for artifact in document_artifacts]

    def add_sbom(self, sbom):
        """Add an SBOM to this release.

        Args:
            sbom: SBOM instance to add to the release.
        """
        ReleaseArtifact.objects.create(release=self, sbom=sbom)

    def add_document(self, document):
        """Add a Document to this release.

        Args:
            document: Document instance to add to the release.
        """
        ReleaseArtifact.objects.create(release=self, document=document)

    def remove_sbom(self, sbom):
        """Remove an SBOM from this release.

        Args:
            sbom: SBOM instance to remove from the release.
        """
        self.artifacts.filter(sbom=sbom).delete()

    def remove_document(self, document):
        """Remove a Document from this release.

        Args:
            document: Document instance to remove from the release.
        """
        self.artifacts.filter(document=document).delete()


class ReleaseArtifact(models.Model):
    """Junction table linking releases to specific artifacts (SBOMs or Documents)."""

    class Meta:
        db_table = "core_release_artifacts"
        # Ensure an artifact can only be included once per release
        unique_together = [
            ("release", "sbom"),  # An SBOM can only be in a release once
            ("release", "document"),  # A document can only be in a release once
        ]
        indexes = [
            models.Index(fields=["release", "-created_at"], name="core_art_rel_created_idx"),
            models.Index(fields=["sbom"], name="core_art_sbom_idx"),
            models.Index(fields=["document"], name="core_art_document_idx"),
            models.Index(fields=["release", "sbom"], name="core_art_rel_sbom_idx"),
            models.Index(fields=["release", "document"], name="core_art_rel_doc_idx"),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="artifacts")

    # Either sbom OR document will be set, never both
    sbom = models.ForeignKey(
        "sboms.SBOM",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="SBOM artifact included in this release",
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Document artifact included in this release",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        if self.sbom:
            return f"{self.release.name} - SBOM: {self.sbom.name}"
        elif self.document:
            return f"{self.release.name} - Document: {self.document.name}"
        return f"{self.release.name} - Invalid artifact"

    def clean(self):
        """Validate that exactly one of sbom or document is set."""
        if not self.sbom and not self.document:
            raise ValidationError("Either sbom or document must be specified.")

        if self.sbom and self.document:
            raise ValidationError("Cannot specify both sbom and document for the same artifact.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def artifact_type(self) -> str:
        """Return the type of artifact ('sbom' or 'document')."""
        if self.sbom:
            return "sbom"
        elif self.document:
            return "document"
        return "unknown"

    @property
    def artifact_name(self) -> str:
        """Return the name of the artifact."""
        if self.sbom:
            return self.sbom.name
        elif self.document:
            return self.document.name
        return "Unknown"

    @property
    def component(self):
        """Return the component that this artifact belongs to."""
        if self.sbom:
            return self.sbom.component
        elif self.document:
            return self.document.component
        return None
