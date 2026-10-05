"""Models for the plugin-based assessment framework.

This module defines the core models for storing assessment runs, team settings,
and registered plugins.
"""

import uuid
from typing import Any

from django.apps import apps
from django.db import models
from django.utils import timezone

from sbomify.apps.core.utils import generate_id

from .sdk.enums import AssessmentCategory, RunReason, RunStatus


class RegisteredPlugin(models.Model):
    """Admin-managed registry of available assessment plugins.

    This model allows administrators to enable/disable plugins system-wide.
    Teams can only enable plugins that are registered and enabled here.

    Attributes:
        name: Unique plugin identifier (e.g., "checksum", "ntia", "osv").
        display_name: Human-readable name for UI display.
        description: Description of what the plugin does.
        category: Assessment category for classification (security, compliance,
            attestation, license). Under the scan-once-per-SBOM model, all
            plugins run on SBOM upload; release associations update the
            existing run's M2M without triggering a rescan.
        version: Current version of the plugin.
        plugin_class_path: Python import path to the plugin class.
        is_enabled: Whether the plugin is available for teams to use.
        is_builtin: Whether the plugin is managed by the framework (vs admin-created).
        is_beta: Whether the plugin is in beta status.
        default_config: Default configuration for the plugin.
        created_at: When the plugin was registered.
        updated_at: When the plugin was last updated.
    """

    class Meta:
        db_table = apps.get_app_config("plugins").label + "_registered_plugins"
        ordering = ["category", "name"]
        verbose_name = "Registered Plugin"
        verbose_name_plural = "Registered Plugins"
        indexes = [
            models.Index(fields=["is_enabled"]),
            models.Index(fields=["category"]),
            models.Index(fields=["name"]),
        ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Unique plugin identifier (e.g., 'checksum', 'ntia', 'osv')",
    )
    display_name = models.CharField(
        max_length=255,
        help_text="Human-readable name for UI display",
    )
    description = models.TextField(
        blank=True,
        help_text="Description of what the plugin does",
    )
    category = models.CharField(
        max_length=20,
        choices=[(c.value, c.name.title()) for c in AssessmentCategory],
        help_text="Assessment category for classification",
    )
    version = models.CharField(
        max_length=50,
        help_text="Current version of the plugin",
    )
    plugin_class_path = models.CharField(
        max_length=500,
        help_text="Python import path to the plugin class (e.g., 'sbomify.apps.plugins.builtins.ChecksumPlugin')",
    )
    is_enabled = models.BooleanField(
        default=True,
        help_text="Whether the plugin is available for teams to use",
    )
    is_builtin = models.BooleanField(
        default=False,
        help_text="Builtin plugins are registered by the framework and reconciled on deploy.",
    )
    is_beta = models.BooleanField(
        default=False,
        help_text="Whether the plugin is in beta status (shown with beta badge in UI)",
    )
    default_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Default configuration for the plugin",
    )
    config_schema = models.JSONField(
        default=list,
        blank=True,
        help_text="Schema defining configurable fields for this plugin",
    )
    dependencies = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Plugin dependencies specifying required assessments. Schema: "
            '{"requires_one_of": [{"type": "category|plugin", "value": "..."}], '
            '"requires_all": [{"type": "category|plugin", "value": "..."}]}'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        """Return string representation."""
        status = "enabled" if self.is_enabled else "disabled"
        beta = " [BETA]" if self.is_beta else ""
        return f"{self.display_name} v{self.version}{beta} ({status})"


class TeamPluginSettings(models.Model):
    """Team-specific plugin configuration.

    Stores which plugins are enabled for each team and their configurations.
    Teams can only enable plugins that are registered and enabled in RegisteredPlugin.

    Attributes:
        team: The team these settings belong to.
        enabled_plugins: List of enabled plugin names.
        plugin_configs: Plugin-specific configuration overrides.
        created_at: When the settings were created.
        updated_at: When the settings were last updated.
    """

    class Meta:
        db_table = "plugins_workspace_settings"
        verbose_name = "Workspace Plugin Settings"
        verbose_name_plural = "Workspace Plugin Settings"
        indexes = [
            models.Index(fields=["team"]),
        ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.OneToOneField(
        "teams.Team",
        on_delete=models.CASCADE,
        related_name="plugin_settings",
        db_column="workspace_id",
    )
    enabled_plugins = models.JSONField(
        default=list,
        help_text="List of enabled plugin names (e.g., ['checksum', 'ntia', 'osv'])",
    )
    plugin_configs = models.JSONField(
        default=dict,
        help_text="Plugin-specific configuration overrides (e.g., {'license-policy': {'allowed': ['MIT']}})",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        """Return string representation."""
        count = len(self.enabled_plugins) if self.enabled_plugins else 0
        return f"{self.team.name} - {count} plugins enabled"

    def is_plugin_enabled(self, plugin_name: str) -> bool:
        """Check if a plugin is enabled for this team.

        Args:
            plugin_name: The plugin identifier to check.

        Returns:
            True if the plugin is enabled for this team.
        """
        return plugin_name in (self.enabled_plugins or [])

    def get_plugin_config(self, plugin_name: str) -> dict[str, Any]:
        """Get the configuration for a specific plugin.

        Args:
            plugin_name: The plugin identifier.

        Returns:
            Plugin configuration dict, or empty dict if not configured.
        """
        configs: dict[str, Any] = self.plugin_configs or {}
        result: dict[str, Any] = configs.get(plugin_name, {})
        return result


class AssessmentRun(models.Model):
    """Immutable record of a single assessment execution.

    Each execution produces a new AssessmentRun record, enabling historical
    analysis and audit trails. Results are stored as JSON following the
    AssessmentResult schema.

    Unit of work: one scan per (SBOM, plugin) pair. A single run can cover
    multiple releases that share the same SBOM bytes — tracked via the
    ``releases`` M2M. When a new release association is created for an
    already-scanned SBOM, the existing run's M2M is extended and downstream
    integrations (e.g. DT project tags) are updated — no new scan is
    performed. This matches DT's "one project version per unique risk state"
    guidance and avoids redundant scans of identical bytes.

    Attributes:
        id: UUID primary key.
        sbom: Foreign key to the SBOM being assessed.
        releases: M2M to Release (via AssessmentRunRelease). The set of
            releases this run's result applies to. Populated at run
            completion from the current ReleaseArtifact state for the
            SBOM, and updated when new release associations are created
            or removed afterwards.
        plugin_name: Plugin identifier (denormalized from result).
        plugin_version: Plugin version (denormalized from result).
        plugin_config_hash: SHA256 hash of plugin configuration.
        category: Assessment category (denormalized from result).
        run_reason: Why this assessment was triggered.
        status: Current status of the assessment run.
        started_at: When the assessment started.
        completed_at: When the assessment completed.
        error_message: Error details if the assessment failed.
        triggered_by_user: User who triggered a manual run.
        triggered_by_token: API token used to trigger the run.
        input_content_digest: SHA256 of SBOM content for auditability.
        result: JSON containing the AssessmentResult.
        result_schema_version: Version of the result schema.
        raw_output_key: S3 key for raw tool output (optional).
        created_at: When the record was created.
    """

    class Meta:
        db_table = apps.get_app_config("plugins").label + "_assessment_runs"
        verbose_name = "Assessment Run"
        verbose_name_plural = "Assessment Runs"
        indexes = [
            models.Index(fields=["sbom", "plugin_name", "-created_at"]),
            models.Index(fields=["sbom", "plugin_name", "plugin_config_hash", "-created_at"]),
            models.Index(fields=["category", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        ordering = ["-created_at"]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sbom = models.ForeignKey(
        "sboms.SBOM",
        on_delete=models.CASCADE,
        related_name="assessment_runs",
    )
    releases: "models.ManyToManyField[Any, Any]" = models.ManyToManyField(
        "core.Release",
        through="AssessmentRunRelease",
        related_name="assessment_runs",
        blank=True,
        help_text=(
            "Releases whose SBOM this run's result covers. Populated from "
            "ReleaseArtifact state at scan time and updated when new "
            "associations are created. Empty for SBOM-level plugin runs "
            "(e.g. NTIA) that are deterministic on bytes regardless of "
            "release context."
        ),
    )

    # Plugin identification (denormalized for efficient querying)
    plugin_name = models.CharField(
        max_length=100,
        help_text="Plugin identifier (e.g., 'ntia-minimum-elements')",
    )
    plugin_version = models.CharField(
        max_length=50,
        help_text="Plugin version (e.g., '1.2.0')",
    )
    plugin_config_hash = models.CharField(
        max_length=64,
        help_text="SHA256 hash of plugin configuration",
    )
    category = models.CharField(
        max_length=20,
        choices=[(c.value, c.name.title()) for c in AssessmentCategory],
        help_text="Assessment category",
    )

    # Execution metadata
    run_reason = models.CharField(
        max_length=50,
        choices=[(r.value, r.name.replace("_", " ").title()) for r in RunReason],
        help_text="Why this assessment was triggered",
    )
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name.title()) for s in RunStatus],
        default=RunStatus.PENDING.value,
        help_text="Current status of the assessment run",
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the assessment started",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the assessment completed",
    )
    error_message = models.TextField(
        blank=True,
        help_text="Error details if the assessment failed",
    )

    # Audit: who/what triggered this run
    triggered_by_user = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_assessment_runs",
        help_text="User who triggered a manual run (null for automated runs)",
    )
    triggered_by_token = models.ForeignKey(
        "access_tokens.AccessToken",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_assessment_runs",
        help_text="API token used to trigger the run (null for UI or automated runs)",
    )

    # Input reference
    input_content_digest = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA256 of SBOM content for auditability",
    )

    # Results
    result = models.JSONField(
        null=True,
        help_text="Assessment result following AssessmentResult schema",
    )
    # Application-maintained copies of the small hot slices of ``result``. The
    # blob routinely runs to multiple MB (the findings array), and every
    # JSON-path read of it forces Postgres to de-TOAST the whole value — the
    # dashboards only need these slices. Plain columns (populated in ``save``,
    # never by a table-rewriting generated expression, so adding them was
    # instant even on very large tables) stay inline in the heap tuple, and
    # reads that select them never touch the blob's TOAST data. ``result``
    # itself stays untouched. Legacy rows are filled by the
    # ``backfill_result_summaries`` management command.
    result_summary = models.JSONField(
        null=True,
        editable=False,
        help_text="result.summary, copied at write time for blob-free reads",
    )
    result_skipped = models.BooleanField(
        null=True,
        editable=False,
        help_text="result.metadata.skipped, copied at write time for blob-free reads",
    )
    result_schema_version = models.CharField(
        max_length=10,
        default="1.0",
        help_text="Version of the result schema",
    )

    # Large output storage (optional)
    raw_output_key = models.CharField(
        max_length=255,
        blank=True,
        help_text="S3 key for raw tool output (optional)",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    def _populate_result_columns(self) -> None:
        """Copy the hot slices of ``result`` into their dedicated columns."""
        result = self.result if isinstance(self.result, dict) else {}
        summary = result.get("summary")
        self.result_summary = summary if isinstance(summary, dict) else None
        metadata = result.get("metadata")
        skipped = metadata.get("skipped") if isinstance(metadata, dict) else None
        # Tri-state on purpose: only a real JSON boolean lands in the column;
        # anything else (absent, junk value) reads as "unknown", mirroring how
        # the old generated column's jsonb-equality expression behaved.
        self.result_skipped = skipped if isinstance(skipped, bool) else None

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Keep ``result_summary``/``result_skipped`` in lockstep with ``result``.

        Every production write path goes through ``save`` (creates, the
        orchestrator's completion update, the VEX re-annotation), so the
        columns can never drift. When the caller narrows ``update_fields``
        to include ``result``, the derived columns are added so a result
        rewrite can't leave them stale. Saves that don't write ``result``
        (e.g. status-only updates, deferred-field instances) leave the
        columns untouched — recomputing there would be wasted work and, on
        a deferred instance, would silently refetch the multi-MB blob.
        """
        update_fields = kwargs.get("update_fields")
        writes_result = update_fields is None or "result" in update_fields
        if writes_result and "result" not in self.get_deferred_fields():
            self._populate_result_columns()
            if update_fields is not None:
                kwargs["update_fields"] = list(set(update_fields) | {"result_summary", "result_skipped"})
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return string representation."""
        return f"{self.plugin_name} v{self.plugin_version} on {self.sbom_id} ({self.status})"

    @property
    def duration_seconds(self) -> float | None:
        """Calculate the duration of the assessment run.

        Returns:
            Duration in seconds, or None if not completed.
        """
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def is_successful(self) -> bool:
        """Check if the assessment completed successfully.

        Returns:
            True if status is COMPLETED.
        """
        return self.status == RunStatus.COMPLETED.value


class AssessmentRunRelease(models.Model):
    """Through table linking AssessmentRun to Release (M2M).

    One scan (AssessmentRun) covers all Releases that share the scanned SBOM.
    When a new ReleaseArtifact is created for an already-scanned SBOM, a row
    is added here instead of triggering a new scan. When a ReleaseArtifact is
    deleted (or the ``latest`` pointer moves to a different SBOM), the row is
    removed so downstream tag state (e.g. DT project tags) stays consistent.

    Attributes:
        assessment_run: The scan whose result covers this release.
        release: The release the scan result applies to.
        created_at: When this association was created (for audit / ordering).
    """

    class Meta:
        db_table = apps.get_app_config("plugins").label + "_assessment_run_releases"
        unique_together = [("assessment_run", "release")]
        indexes = [
            models.Index(fields=["assessment_run", "release"]),
            models.Index(fields=["release", "assessment_run"]),
        ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment_run = models.ForeignKey(
        AssessmentRun,
        on_delete=models.CASCADE,
        related_name="release_associations",
    )
    release = models.ForeignKey(
        "core.Release",
        on_delete=models.CASCADE,
        related_name="run_associations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.assessment_run_id} ↔ {self.release_id}"


class VulnerabilityLifecycle(models.Model):
    """When a vulnerability first appeared for a component, and when it went away.

    Findings exist per scan run only, so "age of open criticals" and
    mean-time-to-remediate could not be computed: both need a first-seen date
    and a resolved date, and a run is a snapshot rather than a history.

    Derived on write as scan results arrive. The stored run stays immutable
    (ADR-004): this table is a separate index over them, not an edit.

    Keyed on (component, advisory) rather than (sbom, advisory) because that is
    the question being asked. A component publishes many SBOMs over time and the
    same CVE persists across them; keying per SBOM would restart the clock at
    every upload and make every finding look a day old.
    """

    class Meta:
        db_table = apps.get_app_config("plugins").label + "_vulnerability_lifecycle"
        constraints = [
            models.UniqueConstraint(fields=["component", "advisory_id"], name="plugins_vuln_lifecycle_unique"),
        ]
        indexes = [
            models.Index(fields=["component", "resolved_at"], name="plugins_vuln_lc_open_idx"),
            models.Index(fields=["first_seen_at"], name="plugins_vuln_lc_first_seen_idx"),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    component = models.ForeignKey("sboms.Component", on_delete=models.CASCADE, related_name="vulnerability_lifecycles")
    advisory_id = models.CharField(max_length=255, help_text="CVE, GHSA or other advisory identifier")
    severity = models.CharField(max_length=20, blank=True, default="", help_text="Severity at the latest sighting")

    first_seen_at = models.DateTimeField(help_text="When this advisory was first seen for this component")
    last_seen_at = models.DateTimeField(help_text="The most recent scan that still reported it")
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When a scan that did run stopped reporting it. NULL while still open.",
    )

    def __str__(self) -> str:
        return f"{self.advisory_id} on {self.component_id}"

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    @property
    def age_days(self) -> int:
        """Days open, or days it took to remediate once resolved."""
        end = self.resolved_at or timezone.now()
        return max(0, (end - self.first_seen_at).days)
