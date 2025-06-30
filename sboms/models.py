from django.apps import apps
from django.db import models

from catalog.models import Component as CatalogComponent
from catalog.models import Product as CatalogProduct
from catalog.models import ProductProject as CatalogProductProject
from catalog.models import Project as CatalogProject
from catalog.models import ProjectComponent as CatalogProjectComponent
from core.utils import generate_id


class SBOM(models.Model):
    """
    Represents a Software Bill of Materials document.

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

    class Meta:
        db_table = apps.get_app_config("sboms").name + "_sboms"
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
    component = models.ForeignKey("sboms.Component", on_delete=models.CASCADE)

    def __str__(self) -> str:
        return self.name

    @property
    def public_access_allowed(self) -> bool:
        return self.component.is_public

    @property
    def source_display(self) -> str:
        """Return a user-friendly display name for the source."""
        source_display_map = {
            "api": "API",
            "manual_upload": "Manual Upload",
        }
        return source_display_map.get(self.source, self.source or "Unknown")


# =============================================================================
# BACKWARD COMPATIBILITY PROXY MODELS
# =============================================================================
# These proxy models provide backward compatibility during the migration
# from sboms to catalog app. They will be removed after the migration is complete.


class Product(CatalogProduct):
    """Backward compatibility proxy for catalog.models.Product."""

    class Meta:
        proxy = True


class Project(CatalogProject):
    """Backward compatibility proxy for catalog.models.Project."""

    class Meta:
        proxy = True


class Component(CatalogComponent):
    """Backward compatibility proxy for catalog.models.Component."""

    class Meta:
        proxy = True

    @property
    def latest_sbom(self) -> "SBOM":
        """Backward compatibility property for getting the latest SBOM."""
        return self.sbom_set.order_by("-created_at").first()


class ProductProject(CatalogProductProject):
    """Backward compatibility proxy for catalog.models.ProductProject."""

    class Meta:
        proxy = True


class ProjectComponent(CatalogProjectComponent):
    """Backward compatibility proxy for catalog.models.ProjectComponent."""

    class Meta:
        proxy = True
