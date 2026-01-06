from django.contrib import admin

from .models import SBOM


class SBOMAdmin(admin.ModelAdmin):
    """Admin configuration for SBOM model.

    Note: NTIA compliance data is now available via AssessmentRun records
    in the plugins app (plugin_name="ntia-minimum-elements-2021").
    """

    list_display = (
        "name",
        "version",
        "format",
        "format_version",
        "component",
        "workspace",
        "created_at",
    )

    list_filter = (
        "format",
        "component__team",
        "created_at",
    )

    search_fields = (
        "name",
        "version",
        "sbom_filename",
        "component__name",
        "component__team__name",
    )

    readonly_fields = (
        "id",
        "created_at",
    )

    def workspace(self, obj):
        """Display the workspace (team) name for the SBOM."""
        return obj.component.team.name if obj.component and obj.component.team else "No Team"

    workspace.short_description = "Workspace"
    workspace.admin_order_field = "component__team__name"


# Product, Project, Component admin moved to core app
admin.site.register(SBOM, SBOMAdmin)
