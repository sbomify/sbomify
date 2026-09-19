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
        # An integration owns this catalog: the workspace's compliance tool is
        # the system of record and every sync overwrites what is here. The
        # value is the provider key, so ``Integration.provider`` and
        # ``ControlCatalog.source`` are the same string and a disconnect can
        # find what it published without a second table.
        VANTA = "vanta", "Vanta"

    class Meta:
        db_table = "controls_catalog"
        unique_together = ("team", "name", "version")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "source", "external_id"], name="controls_catalog_source_idx"),
        ]
        constraints = [
            # A synced catalog is identified by the id its own system gave it,
            # so the database is what stops two concurrent syncs of one account
            # from both creating it. Hand-made catalogs carry no external id and
            # are excluded, or they would all collide on the empty string.
            models.UniqueConstraint(
                fields=["team", "source", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_catalog_per_external_id",
            ),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="control_catalogs", db_column="workspace_id"
    )
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=50)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.BUILTIN)
    # The id this catalog has in the system that owns it, for synced sources.
    # Identity for a sync is this, not the name: a framework that gets renamed
    # upstream must update in place rather than arrive as a second catalog.
    external_id = models.CharField(max_length=255, blank=True, default="")
    # Whether this workspace tracks the framework at all: it appears in the
    # settings UI, and plugin assessments may promote its controls.
    is_active = models.BooleanField(default=True)
    # Whether it appears on the public trust center. Separate from is_active,
    # and default off, because the two are different decisions and only one of
    # them is outward-facing. Tracking SOC 2 internally is not consent to
    # publish a compliance score to your customers, so a catalogue a workspace
    # was already using stays internal until somebody says otherwise.
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} {self.version}"

    @property
    def is_integration_owned(self) -> bool:
        return self.source in INTEGRATION_SOURCES


# The sources an external system owns and rewrites on every sync. A catalogue
# with one of these is not ours to edit: promoting one of its controls from a
# plugin result would overwrite the answer the workspace's own compliance tool
# gave, which is the one thing a synced catalogue is for.
INTEGRATION_SOURCES: frozenset[str] = frozenset({ControlCatalog.Source.VANTA})


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
    # As above, for controls: ``control_id`` is the code a reader recognises
    # ("CC1.1") and can change, this is the upstream row's own id.
    external_id = models.CharField(max_length=255, blank=True, default="")
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


class ControlMapping(models.Model):
    class RelationType(models.TextChoices):
        EQUIVALENT = "equivalent", "Equivalent"
        PARTIAL = "partial", "Partial Overlap"
        RELATED = "related", "Related"

    class Meta:
        db_table = "controls_mapping"
        unique_together = ("source_control", "target_control")

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    source_control = models.ForeignKey(Control, on_delete=models.CASCADE, related_name="mappings_as_source")
    target_control = models.ForeignKey(Control, on_delete=models.CASCADE, related_name="mappings_as_target")
    relation_type = models.CharField(max_length=20, choices=RelationType.choices)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.source_control_id} -> {self.target_control_id} ({self.relation_type})"


class ControlStatusLog(models.Model):
    class Meta:
        db_table = "controls_status_log"
        ordering = ["-created_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    control = models.ForeignKey(Control, on_delete=models.CASCADE, related_name="status_logs")
    product = models.ForeignKey(
        "core.Product", on_delete=models.CASCADE, null=True, blank=True, related_name="control_status_logs"
    )
    old_status = models.CharField(max_length=20, blank=True, default="")
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.control.control_id}: {self.old_status} -> {self.new_status}"


class ControlEvidence(models.Model):
    class EvidenceType(models.TextChoices):
        DOCUMENT = "document", "Document"
        URL = "url", "URL"
        NOTE = "note", "Note"

    class Meta:
        db_table = "controls_evidence"
        ordering = ["-created_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    control_status = models.ForeignKey(ControlStatus, on_delete=models.CASCADE, related_name="evidence")
    evidence_type = models.CharField(max_length=20, choices=EvidenceType.choices)
    title = models.CharField(max_length=255)
    url = models.URLField(blank=True, default="")
    document_id = models.CharField(max_length=20, blank=True, default="")
    description = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.title} ({self.evidence_type})"
