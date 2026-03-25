from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from sbomify.apps.core.utils import generate_id


class ControlCatalog(models.Model):
    class Source(models.TextChoices):
        BUILTIN = "builtin", "Built-in"
        CUSTOM = "custom", "Custom"

    class Meta:
        db_table = "controls_catalog"
        unique_together = ("team", "name", "version")
        ordering = ["-created_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="control_catalogs")
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=50)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.BUILTIN)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} {self.version}"


class Control(models.Model):
    class Meta:
        db_table = "controls_control"
        unique_together = ("catalog", "control_id")
        ordering = ["sort_order", "control_id"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    catalog = models.ForeignKey(ControlCatalog, on_delete=models.CASCADE, related_name="controls")
    group = models.CharField(max_length=255)
    control_id = models.CharField(max_length=50)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.control_id}: {self.title}"


class ControlStatus(models.Model):
    class Status(models.TextChoices):
        COMPLIANT = "compliant", "Compliant"
        PARTIAL = "partial", "Partial"
        NOT_IMPLEMENTED = "not_implemented", "Not Implemented"
        NOT_APPLICABLE = "not_applicable", "Not Applicable"

    class Meta:
        db_table = "controls_status"
        ordering = ["control__sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["control", "product"],
                condition=Q(product__isnull=False),
                name="unique_control_product",
            ),
            models.UniqueConstraint(
                fields=["control"],
                condition=Q(product__isnull=True),
                name="unique_control_global",
            ),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    control = models.ForeignKey(Control, on_delete=models.CASCADE, related_name="statuses")
    product = models.ForeignKey(
        "core.Product", on_delete=models.CASCADE, null=True, blank=True, related_name="control_statuses"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_IMPLEMENTED)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self) -> str:
        scope = self.product.name if self.product else "Global"
        return f"{self.control.control_id} ({scope}): {self.status}"
