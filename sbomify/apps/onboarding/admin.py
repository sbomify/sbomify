"""
Admin interface for onboarding models.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import OnboardingEmail, OnboardingStatus


@admin.register(OnboardingStatus)
class OnboardingStatusAdmin(admin.ModelAdmin):
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

    def user_email(self, obj) -> str:
        """Get user email."""
        return obj.user.email

    user_email.short_description = "Email"
    user_email.admin_order_field = "user__email"

    def progress_indicator(self, obj) -> str:
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

    progress_indicator.short_description = "Progress"


@admin.register(OnboardingEmail)
class OnboardingEmailAdmin(admin.ModelAdmin):
    """Admin interface for OnboardingEmail."""

    list_display = [
        "user_email",
        "email_type",
        "success",
        "subject",
        "sent_at",
    ]

    list_filter = [
        "email_type",
        "success",
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
        "success",
        "error_message",
    ]

    ordering = ["-sent_at"]

    def user_email(self, obj) -> str:
        """Get user email."""
        return obj.user.email

    user_email.short_description = "Email"
    user_email.admin_order_field = "user__email"

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related("user")
