"""Models for the plugin-based assessment framework.

This module defines the core models for storing assessment runs, team settings,
and registered plugins.
"""

import uuid

from django.apps import apps
from django.db import models

from .sdk.enums import AssessmentCategory, RunReason, RunStatus


class RegisteredPlugin(models.Model):
    """Admin-managed registry of available assessment plugins.

    This model allows administrators to enable/disable plugins system-wide.
    Teams can only enable plugins that are registered and enabled here.

    Attributes:
        name: Unique plugin identifier (e.g., "checksum", "ntia", "osv").
        display_name: Human-readable name for UI display.
        description: Description of what the plugin does.
        category: Assessment category for classification.
        version: Current version of the plugin.
        plugin_class_path: Python import path to the plugin class.
        is_enabled: Whether the plugin is available for teams to use.
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
        db_table = apps.get_app_config("plugins").label + "_team_settings"
        verbose_name = "Team Plugin Settings"
        verbose_name_plural = "Team Plugin Settings"
        indexes = [
            models.Index(fields=["team"]),
        ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.OneToOneField(
        "teams.Team",
        on_delete=models.CASCADE,
        related_name="plugin_settings",
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

    def get_plugin_config(self, plugin_name: str) -> dict:
        """Get the configuration for a specific plugin.

        Args:
            plugin_name: The plugin identifier.

        Returns:
            Plugin configuration dict, or empty dict if not configured.
        """
        return (self.plugin_configs or {}).get(plugin_name, {})


class AssessmentRun(models.Model):
    """Immutable record of a single assessment execution.

    Each execution produces a new AssessmentRun record, enabling historical
    analysis and audit trails. Results are stored as JSON following the
    AssessmentResult schema.

    Attributes:
        id: UUID primary key.
        sbom: Foreign key to the SBOM being assessed.
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
        max_length=30,
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
