"""
Admin interface for onboarding models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html

from .models import OnboardingEmail, OnboardingStatus

if TYPE_CHECKING:
    from django.db.models import QuerySet

    _OnboardingStatusAdmin = admin.ModelAdmin[OnboardingStatus]
    _OnboardingEmailAdmin = admin.ModelAdmin[OnboardingEmail]
else:
    _OnboardingStatusAdmin = admin.ModelAdmin
    _OnboardingEmailAdmin = admin.ModelAdmin


@admin.register(OnboardingStatus)
class OnboardingStatusAdmin(_OnboardingStatusAdmin):
    """Admin interface for OnboardingStatus."""

    list_display = [
        "user_email",
        "user_role",
        "days_since_signup",
        "progress_indicator",
        "welcome_email_sent",
        "has_created_component",
        "has_uploaded_sbom",
        "created_at",
    ]

    list_filter = [
        "has_created_component",
        "has_uploaded_sbom",
        "has_completed_wizard",
        "welcome_email_sent",
        "created_at",
    ]

    search_fields = [
        "user__email",
        "user__username",
        "user__first_name",
        "user__last_name",
    ]

    readonly_fields = [
        "user",
        "created_at",
        "updated_at",
        "first_component_created_at",
        "first_sbom_uploaded_at",
        "wizard_completed_at",
        "welcome_email_sent_at",
    ]

    ordering = ["-created_at"]

    @admin.display(description="Email", ordering="user__email")
    def user_email(self, obj: OnboardingStatus) -> str:
        """Get user email."""
        return str(obj.user.email)

    @admin.display(description="Progress")
    def progress_indicator(self, obj: OnboardingStatus) -> str:
        """Show visual progress indicator."""
        progress = 0
        steps = []

        if obj.welcome_email_sent:
            progress += 25
            steps.append("✓ Welcome")
        else:
            steps.append("○ Welcome")

        if obj.has_created_component:
            progress += 25
            steps.append("✓ Component")
        else:
            steps.append("○ Component")

        if obj.has_uploaded_sbom:
            progress += 25
            steps.append("✓ SBOM")
        else:
            steps.append("○ SBOM")

        if obj.has_completed_wizard:
            progress += 25
            steps.append("✓ Wizard")
        else:
            steps.append("○ Wizard")

        color = "green" if progress >= 75 else "orange" if progress >= 50 else "red"

        return format_html('<div style="color: {};">{} ({}%)</div>', color, " → ".join(steps), progress)


@admin.register(OnboardingEmail)
class OnboardingEmailAdmin(_OnboardingEmailAdmin):
    """Admin interface for OnboardingEmail."""

    list_display = [
        "user_email",
        "email_type",
        "status",
        "subject",
        "sent_at",
    ]

    list_filter = [
        "email_type",
        "status",
        "sent_at",
    ]

    search_fields = [
        "user__email",
        "user__username",
        "subject",
    ]

    readonly_fields = [
        "user",
        "email_type",
        "subject",
        "sent_at",
        "status",
        "error_message",
    ]

    ordering = ["-sent_at"]

    @admin.display(description="Email", ordering="user__email")
    def user_email(self, obj: OnboardingEmail) -> str:
        """Get user email."""
        return str(obj.user.email)

    def get_queryset(self, request: HttpRequest) -> QuerySet[OnboardingEmail]:
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related("user")
