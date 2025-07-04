from django.contrib import admin
from django.utils.html import format_html


class DocumentAdmin(admin.ModelAdmin):
    """Admin configuration for Document model."""

    list_display = (
        "name",
        "version",
        "document_type",
        "component",
        "source_display_formatted",
        "file_size_formatted",
        "created_at",
        "public_access_indicator",
    )

    list_filter = (
        "document_type",
        "source",
        "content_type",
        "created_at",
        "component__is_public",
    )

    search_fields = (
        "name",
        "document_filename",
        "description",
        "component__name",
        "component__id",
    )

    readonly_fields = (
        "id",
        "created_at",
        "file_size_formatted",
        "source_display_formatted",
        "public_access_indicator",
    )

    fieldsets = (
        (
            "Document Information",
            {
                "fields": (
                    "id",
                    "name",
                    "version",
                    "document_type",
                    "description",
                )
            },
        ),
        (
            "File Information",
            {
                "fields": (
                    "document_filename",
                    "content_type",
                    "file_size_formatted",
                )
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "source_display_formatted",
                    "component",
                    "created_at",
                    "public_access_indicator",
                )
            },
        ),
    )

    def source_display_formatted(self, obj):
        """Display source with formatting."""
        return format_html('<span style="color: #666; font-style: italic;">{}</span>', obj.source_display)

    source_display_formatted.short_description = "Source"

    def file_size_formatted(self, obj):
        """Display file size in human-readable format."""
        if not obj.file_size:
            return format_html('<span style="color: #666;">Unknown</span>')

        # Convert bytes to human readable format
        size = obj.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return format_html('<span style="color: #417690;">{:.1f} {}</span>', size, unit)
            size /= 1024.0
        return format_html('<span style="color: #417690;">{:.1f} TB</span>', size)

    file_size_formatted.short_description = "File Size"

    def public_access_indicator(self, obj):
        """Display public access status."""
        if obj.public_access_allowed:
            return format_html('<span style="color: #28a745;">✓ Public</span>')
        else:
            return format_html('<span style="color: #dc3545;">✗ Private</span>')

    public_access_indicator.short_description = "Access Level"

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related("component")
