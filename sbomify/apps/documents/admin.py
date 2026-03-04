from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from .models import Document

if TYPE_CHECKING:
    _DocumentAdminBase = admin.ModelAdmin[Document]
else:
    _DocumentAdminBase = admin.ModelAdmin


class DocumentAdmin(_DocumentAdminBase):
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
        "component__visibility",
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

    @admin.display(description="Source")
    def source_display_formatted(self, obj: Any) -> str:
        """Display source with formatting."""
        return format_html('<span style="color: #666; font-style: italic;">{}</span>', obj.source_display)

    @admin.display(description="File Size")
    def file_size_formatted(self, obj: Any) -> str:
        """Display file size in human-readable format."""
        if not obj.file_size:
            return format_html('<span style="color: #666;">Unknown</span>')

        # Convert bytes to human readable format
        size = float(obj.file_size)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return format_html('<span style="color: #417690;">{} {}</span>', f"{size:.1f}", unit)
            size /= 1024.0
        return format_html('<span style="color: #417690;">{} TB</span>', f"{size:.1f}")

    @admin.display(description="Access Level")
    def public_access_indicator(self, obj: Any) -> str:
        """Display public access status."""
        if obj.public_access_allowed:
            return format_html('<span style="color: #28a745;">✓ Public</span>')
        else:
            return format_html('<span style="color: #dc3545;">✗ Private</span>')

    def get_queryset(self, request: HttpRequest) -> QuerySet[Document]:
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related("component")
