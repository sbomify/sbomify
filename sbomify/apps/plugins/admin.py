"""Django admin configuration for the plugins app.

This module provides admin interfaces for managing plugins and
viewing assessment runs.
"""

from django.contrib import admin

from .models import AssessmentRun, RegisteredPlugin, TeamPluginSettings


@admin.register(RegisteredPlugin)
class RegisteredPluginAdmin(admin.ModelAdmin):
    """Admin interface for managing registered plugins.

    Allows administrators to enable/disable plugins system-wide and
    configure their default settings.
    """

    list_display = [
        "display_name",
        "name",
        "version",
        "category",
        "is_enabled",
        "is_beta",
        "updated_at",
    ]
    list_filter = ["is_enabled", "is_beta", "category"]
    search_fields = ["name", "display_name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["category", "name"]

    fieldsets = [
        (
            None,
            {
                "fields": ["name", "display_name", "description"],
            },
        ),
        (
            "Plugin Configuration",
            {
                "fields": ["category", "version", "plugin_class_path", "default_config"],
            },
        ),
        (
            "Status",
            {
                "fields": ["is_enabled", "is_beta"],
            },
        ),
        (
            "Metadata",
            {
                "fields": ["id", "created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    actions = ["enable_plugins", "disable_plugins", "mark_as_beta", "mark_as_stable"]

    @admin.action(description="Enable selected plugins")
    def enable_plugins(self, request, queryset) -> None:
        """Bulk enable selected plugins."""
        count = queryset.update(is_enabled=True)
        self.message_user(request, f"{count} plugin(s) enabled.")

    @admin.action(description="Disable selected plugins")
    def disable_plugins(self, request, queryset) -> None:
        """Bulk disable selected plugins."""
        count = queryset.update(is_enabled=False)
        self.message_user(request, f"{count} plugin(s) disabled.")

    @admin.action(description="Mark selected plugins as beta")
    def mark_as_beta(self, request, queryset) -> None:
        """Bulk mark selected plugins as beta."""
        count = queryset.update(is_beta=True)
        self.message_user(request, f"{count} plugin(s) marked as beta.")

    @admin.action(description="Mark selected plugins as stable")
    def mark_as_stable(self, request, queryset) -> None:
        """Bulk mark selected plugins as stable (not beta)."""
        count = queryset.update(is_beta=False)
        self.message_user(request, f"{count} plugin(s) marked as stable.")


@admin.register(TeamPluginSettings)
class TeamPluginSettingsAdmin(admin.ModelAdmin):
    """Admin interface for viewing team plugin settings."""

    list_display = ["team", "enabled_plugins_count", "updated_at"]
    search_fields = ["team__name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["team"]

    fieldsets = [
        (
            None,
            {
                "fields": ["team"],
            },
        ),
        (
            "Plugin Configuration",
            {
                "fields": ["enabled_plugins", "plugin_configs"],
            },
        ),
        (
            "Metadata",
            {
                "fields": ["id", "created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    def enabled_plugins_count(self, obj) -> int:
        """Return count of enabled plugins for display."""
        return len(obj.enabled_plugins) if obj.enabled_plugins else 0

    enabled_plugins_count.short_description = "Enabled Plugins"


@admin.register(AssessmentRun)
class AssessmentRunAdmin(admin.ModelAdmin):
    """Admin interface for viewing assessment runs.

    This is primarily a read-only view for debugging and auditing purposes.
    """

    list_display = [
        "id",
        "sbom",
        "plugin_name",
        "plugin_version",
        "category",
        "status",
        "run_reason",
        "created_at",
    ]
    list_filter = ["status", "category", "plugin_name", "run_reason"]
    search_fields = ["sbom__name", "plugin_name", "error_message"]
    readonly_fields = [
        "id",
        "sbom",
        "plugin_name",
        "plugin_version",
        "plugin_config_hash",
        "category",
        "run_reason",
        "status",
        "started_at",
        "completed_at",
        "error_message",
        "triggered_by_user",
        "triggered_by_token",
        "input_content_digest",
        "result",
        "result_schema_version",
        "raw_output_key",
        "created_at",
        "duration_display",
    ]
    raw_id_fields = ["sbom", "triggered_by_user", "triggered_by_token"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"

    fieldsets = [
        (
            "Assessment",
            {
                "fields": ["id", "sbom", "plugin_name", "plugin_version", "category"],
            },
        ),
        (
            "Execution",
            {
                "fields": [
                    "run_reason",
                    "status",
                    "started_at",
                    "completed_at",
                    "duration_display",
                    "error_message",
                ],
            },
        ),
        (
            "Audit Trail",
            {
                "fields": [
                    "triggered_by_user",
                    "triggered_by_token",
                    "input_content_digest",
                    "plugin_config_hash",
                ],
            },
        ),
        (
            "Results",
            {
                "fields": ["result", "result_schema_version", "raw_output_key"],
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {
                "fields": ["created_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    def duration_display(self, obj) -> str:
        """Format duration for display."""
        duration = obj.duration_seconds
        if duration is None:
            return "-"
        return f"{duration:.2f}s"

    duration_display.short_description = "Duration"

    def has_add_permission(self, request) -> bool:
        """Disable manual creation of assessment runs."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Disable editing of assessment runs."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Allow deletion for cleanup purposes."""
        return True
