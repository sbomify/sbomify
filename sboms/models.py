from typing import List

from django.apps import apps
from django.db import models

from core.utils import generate_id
from teams.models import Team


class Product(models.Model):
    class Meta:
        db_table = apps.get_app_config("sboms").name + "_products"
        unique_together = ("team", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)
    projects = models.ManyToManyField("sboms.Project", through="sboms.ProductProject")

    def __str__(self) -> str:
        return f"{self.name}(Team ID: {self.team_id})"


class Project(models.Model):
    class Meta:
        db_table = apps.get_app_config("sboms").name + "_projects"
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
    class Meta:
        db_table = apps.get_app_config("sboms").name + "_products_projects"
        unique_together = ("product", "project")

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return f"{self.product_id} - {self.project_id}"


class Component(models.Model):
    class Meta:
        db_table = apps.get_app_config("sboms").name + "_components"
        unique_together = ("team", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    projects = models.ManyToManyField(Project, through="sboms.ProjectComponent")

    def __str__(self) -> str:
        return f"{self.name}"

    @property
    def latest_sbom(self) -> "SBOM":
        return self.sbom_set.order_by("-created_at").first()


class ProjectComponent(models.Model):
    class Meta:
        db_table = apps.get_app_config("sboms").name + "_projects_components"
        unique_together = ("project", "component")

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    component = models.ForeignKey(Component, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return f"{self.project_id} - {self.component_id}"


class LicenseComponent(models.Model):
    """Represents an individual license identifier."""

    class Meta:
        db_table = apps.get_app_config("sboms").name + "_license_components"
        ordering = ["identifier"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    identifier = models.CharField(max_length=100)  # SPDX identifier
    name = models.CharField(max_length=255)  # Human readable name
    type = models.CharField(max_length=20)  # spdx, custom

    # Metadata
    is_spdx = models.BooleanField(default=False)  # Whether this is a valid SPDX license
    is_recognized = models.BooleanField(default=False)  # Whether this is a recognized license
    is_deprecated = models.BooleanField(default=False)
    is_osi_approved = models.BooleanField(default=False)
    is_fsf_approved = models.BooleanField(default=False)
    url = models.URLField(null=True)
    text = models.TextField(null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.identifier} ({self.name})"


class LicenseExpression(models.Model):
    """Represents a license expression as a tree structure.

    This model can represent any valid SPDX license expression, including:
    - Simple licenses (MIT, Apache-2.0)
    - Compound expressions (MIT AND Apache-2.0)
    - Expressions with exceptions (GPL-2.0 WITH Classpath-exception-2.0)
    - Nested expressions ((MIT OR Apache-2.0) AND BSD-3-Clause)
    """

    class Meta:
        db_table = apps.get_app_config("sboms").name + "_license_expressions"
        ordering = ["-created_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)

    # Tree structure
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.CASCADE)
    operator = models.CharField(max_length=10, null=True, blank=True)  # AND, OR, WITH, or None for leaves
    component = models.ForeignKey(LicenseComponent, null=True, blank=True, on_delete=models.SET_NULL)

    # Expression data
    expression = models.TextField()  # Raw expression for this node/subtree
    normalized_expression = models.TextField()

    # Metadata
    source = models.CharField(max_length=50)  # spdx, cyclonedx, etc.
    validation_status = models.CharField(max_length=20)  # valid, invalid, unknown
    validation_errors = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    order = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.normalized_expression or self.expression

    def is_leaf(self) -> bool:
        """Check if this is a leaf node (no children)."""
        return not self.children.exists()

    def is_exception(self) -> bool:
        """Check if this is an exception node."""
        return self.operator == "WITH" and self.component is not None

    def get_all_components(self) -> List[LicenseComponent]:
        """Get all license components used in this expression tree."""
        components = []
        if self.component:
            components.append(self.component)
        for child in self.children.all():
            components.extend(child.get_all_components())
        return components

    def get_all_operators(self) -> List[str]:
        """Get all operators used in this expression tree."""
        operators = []
        if self.operator:
            operators.append(self.operator)
        for child in self.children.all():
            operators.extend(child.get_all_operators())
        return operators

    def to_string(self) -> str:
        """Convert the tree back to a license expression string."""
        if self.is_leaf():
            return self.component.identifier if self.component else ""

        if self.is_exception():
            if not self.children.exists():
                return ""
            return f"{self.children.order_by('order').first().to_string()} WITH {self.component.identifier}"

        # For AND/OR, recursively combine children in order
        if not self.children.exists():
            return ""

        child_exprs = [child.to_string() for child in self.children.order_by("order")]
        if len(child_exprs) == 1:
            return child_exprs[0]

        # Add parentheses if needed (for nested expressions)
        child_exprs = [f"({expr})" if " " in expr else expr for expr in child_exprs]
        return f" {self.operator} ".join(child_exprs)


class SBOM(models.Model):
    class Meta:
        db_table = apps.get_app_config("sboms").name + "_sboms"
        ordering = ["-created_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    name = models.CharField(max_length=255, blank=False)  # qualified sbom name like com.github.sbomify/backend
    version = models.CharField(max_length=255, default="")
    format = models.CharField(max_length=255, default="spdx")  # spdx, cyclonedx, etc
    format_version = models.CharField(max_length=20, default="")
    licenses = models.JSONField(default=list)  # DEPRECATED: Do not use. Scheduled for deletion.
    packages_licenses = models.JSONField(default=dict)
    sbom_filename = models.CharField(max_length=255, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    # Where the sbom came from (file-upload, api, github-action, etc)
    source = models.CharField(max_length=255, null=True)
    component = models.ForeignKey(Component, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return self.name

    @property
    def public_access_allowed(self) -> bool:
        return self.component.is_public
