"""Subscriptions to components published on other TEA servers.

A subscription component references a component another TEA 1.0 server
publishes. sbomify keeps that server's metadata, never its artifacts, and
checks it on a schedule. Remote identifiers are kept as the server spells them.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from sbomify.apps.core.utils import generate_id


class TeaSubscription(models.Model):
    """The remote component a subscription component follows, and how its checks are going."""

    class Status(models.TextChoices):
        PENDING = "pending", "Not checked yet"
        OK = "ok", "Up to date"
        UNREACHABLE = "unreachable", "Server unreachable"
        NOT_FOUND = "not_found", "Not found on the server"
        ERROR = "error", "Check failed"

    class Meta:
        db_table = "tea_subscriptions"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    component = models.OneToOneField("sboms.Component", on_delete=models.CASCADE, related_name="tea_subscription")
    api_base_url = models.URLField(max_length=500, help_text="Versioned TEA API base, e.g. https://host/tea/v1.0.0")
    spec_version = models.CharField(max_length=32)
    source_tei = models.CharField(max_length=2048, blank=True)
    remote_component_uuid = models.CharField(max_length=64)
    remote_name = models.CharField(max_length=255, blank=True)
    remote_identifiers = models.JSONField(default=list, blank=True)
    latest_release = models.ForeignKey(
        "TeaRemoteRelease",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The newest upstream release, the one the latest release follows",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    last_error = models.TextField(blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_changed_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(default=timezone.now, db_index=True)
    lease_until = models.DateTimeField(
        null=True, blank=True, help_text="Set while a worker checks this subscription; the check writes only under it"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.remote_name or self.remote_component_uuid} on {self.api_base_url}"


class TeaRemoteRelease(models.Model):
    """One release of the remote component, as its server lists it."""

    class Lifecycle(models.TextChoices):
        ACTIVE = "active", "Active"
        END_OF_SUPPORT = "end_of_support", "Out of support"
        END_OF_LIFE = "end_of_life", "End of life"
        NO_LONGER_DISTRIBUTED = "no_longer_distributed", "No longer distributed"

    class Meta:
        db_table = "tea_remote_releases"
        constraints = [
            models.UniqueConstraint(fields=["subscription", "uuid"], name="tea_remote_release_unique_uuid"),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    subscription = models.ForeignKey(TeaSubscription, on_delete=models.CASCADE, related_name="releases")
    uuid = models.CharField(max_length=64)
    version = models.CharField(max_length=255)
    created_date = models.DateTimeField(null=True, blank=True)
    release_date = models.DateTimeField(null=True, blank=True)
    pre_release = models.BooleanField(default=False)
    tracked = models.BooleanField(default=False, help_text="Picked in the import wizard, so always watched")
    collection_version = models.PositiveIntegerField(null=True, blank=True)
    lifecycle = models.CharField(max_length=24, choices=Lifecycle.choices, default=Lifecycle.ACTIVE)
    gone_at = models.DateTimeField(null=True, blank=True, help_text="When the server stopped listing this release")
    checked_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.version} ({self.uuid})"


class TeaRemoteArtifact(models.Model):
    """One artifact revision seen in a watched collection.

    ``snapshot`` and ``snapshot_fingerprint`` record the revision as first seen and
    are never updated: a pin points at this row, so what a release pinned stays
    what it pinned. A revision the server rewrites in place gets a new row. The
    live fields say how the server's copy compares now.
    """

    class State(models.TextChoices):
        CURRENT = "current", "Current"
        REPLACED = "replaced", "Replaced upstream"
        CHANGED = "changed", "Changed upstream"
        GONE = "gone", "Gone upstream"

    class Meta:
        db_table = "tea_remote_artifacts"
        constraints = [
            models.UniqueConstraint(
                fields=["release", "uuid", "version", "snapshot_fingerprint"],
                name="tea_remote_artifact_unique_snapshot",
            ),
        ]
        indexes = [models.Index(fields=["uuid", "version"], name="tea_remote_artifact_uuid_idx")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    release = models.ForeignKey(TeaRemoteRelease, on_delete=models.CASCADE, related_name="artifacts")
    uuid = models.CharField(max_length=64)
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=255, blank=True)
    artifact_type = models.CharField(max_length=32, blank=True)
    snapshot = models.JSONField(help_text="The artifact as first seen, in TEA's wire shape")
    snapshot_fingerprint = models.CharField(max_length=64)
    live_fingerprint = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.CURRENT)
    state_changed_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name or self.uuid} v{self.version}"


class TeaSubscriptionEvent(models.Model):
    """What a check found that differs from the check before it."""

    class Kind(models.TextChoices):
        RELEASE_ADDED = "release_added", "New upstream release"
        RELEASE_REMOVED = "release_removed", "Upstream release removed"
        COLLECTION_UPDATED = "collection_updated", "Collection updated"
        ARTIFACT_ADDED = "artifact_added", "Artifact added"
        ARTIFACT_REPLACED = "artifact_replaced", "Artifact replaced upstream"
        ARTIFACT_CHANGED = "artifact_changed", "Artifact changed upstream"
        ARTIFACT_GONE = "artifact_gone", "Artifact gone upstream"
        LIFECYCLE_CHANGED = "lifecycle_changed", "Lifecycle changed"
        CHECK_FAILED = "check_failed", "Check failed"
        CHECK_RECOVERED = "check_recovered", "Check recovered"

    class Meta:
        db_table = "tea_subscription_events"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["subscription", "-created_at"], name="tea_sub_event_created_idx")]

    subscription = models.ForeignKey(TeaSubscription, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    release = models.ForeignKey(TeaRemoteRelease, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    artifact = models.ForeignKey(TeaRemoteArtifact, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.get_kind_display()} at {self.created_at:%Y-%m-%d %H:%M}"
