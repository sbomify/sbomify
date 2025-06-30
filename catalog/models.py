# Create your models here.
from django.db import models

from core.utils import generate_id
from teams.models import Team


class ComponentType(models.TextChoices):
    SBOM = "sbom", "SBOM"
    # Future example: DOCUMENT = 'doc', 'Document'


class Product(models.Model):
    class Meta:
        db_table = "sboms_products"  # Keep exact table name
        managed = True  # Now Django manages these tables
        unique_together = ("team", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="catalog_products")
    name = models.CharField(max_length=255, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)
    projects = models.ManyToManyField("catalog.Project", through="catalog.ProductProject")

    def __str__(self) -> str:
        return f"{self.name}(Team ID: {self.team_id})"


class Project(models.Model):
    class Meta:
        db_table = "sboms_projects"
        managed = True
        unique_together = ("team", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="catalog_projects")
    name = models.CharField(max_length=255, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    products = models.ManyToManyField(Product, through="catalog.ProductProject")
    components = models.ManyToManyField("catalog.Component", through="catalog.ProjectComponent")

    def __str__(self) -> str:
        return f"<{self.id}> {self.name}"


class Component(models.Model):
    class Meta:
        db_table = "sboms_components"
        managed = True
        unique_together = ("team", "name")
        ordering = ["name"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="catalog_components")
    name = models.CharField(max_length=255, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    component_type = models.CharField(max_length=20, choices=ComponentType.choices, default=ComponentType.SBOM)
    projects = models.ManyToManyField(Project, through="catalog.ProjectComponent")

    def __str__(self) -> str:
        return f"{self.name}"

    # Note: latest_sbom property will be moved to SBOM model


class ProductProject(models.Model):
    class Meta:
        db_table = "sboms_products_projects"
        managed = True
        unique_together = ("product", "project")

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return f"{self.product_id} - {self.project_id}"


class ProjectComponent(models.Model):
    class Meta:
        db_table = "sboms_projects_components"
        managed = True
        unique_together = ("project", "component")

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    component = models.ForeignKey(Component, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return f"{self.project_id} - {self.component_id}"
