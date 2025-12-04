from django import forms
from django.contrib import admin
from django.utils.html import format_html

from sbomify.apps.billing.models import BillingPlan

from .models import Invitation, Member, Team


class TeamAdminForm(forms.ModelForm):
    """Custom form for Team admin with billing plan dropdown."""

    class Meta:
        model = Team
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Create choices for billing_plan field
        billing_plan_choices = [("", "---------")]  # Empty choice

        # Get all available billing plans
        for plan in BillingPlan.objects.all():
            label = f"{plan.name}"
            if plan.description:
                label += f" - {plan.description}"
            billing_plan_choices.append((plan.key, label))

        # Override the billing_plan field with a Select widget
        self.fields["billing_plan"] = forms.ChoiceField(
            choices=billing_plan_choices, required=False, help_text="Select the billing plan for this team"
        )

        # Make branding_info not required since it's user-managed
        if "branding_info" in self.fields:
            self.fields["branding_info"].required = False
            self.fields["branding_info"].help_text = "User-managed branding information"

        # Make billing_plan_limits not required - it will be auto-populated
        if "billing_plan_limits" in self.fields:
            self.fields["billing_plan_limits"].required = False
            self.fields["billing_plan_limits"].help_text = "Auto-populated based on selected billing plan"

    def clean(self):
        """Auto-populate billing plan limits based on selected plan."""
        cleaned_data = super().clean()
        billing_plan = cleaned_data.get("billing_plan")

        if billing_plan:
            try:
                plan = BillingPlan.objects.get(key=billing_plan)

                # Auto-populate billing plan limits based on the selected plan
                billing_plan_limits = {}

                # Set plan limits
                if plan.max_products is not None:
                    billing_plan_limits["max_products"] = plan.max_products
                if plan.max_projects is not None:
                    billing_plan_limits["max_projects"] = plan.max_projects
                if plan.max_components is not None:
                    billing_plan_limits["max_components"] = plan.max_components

                # For enterprise plans, preserve existing Stripe IDs if they exist
                if billing_plan == "enterprise":
                    existing_limits = self.instance.billing_plan_limits if self.instance.pk else {}
                    if existing_limits:
                        billing_plan_limits["stripe_customer_id"] = existing_limits.get("stripe_customer_id")
                        billing_plan_limits["stripe_subscription_id"] = existing_limits.get("stripe_subscription_id")

                cleaned_data["billing_plan_limits"] = billing_plan_limits

            except BillingPlan.DoesNotExist:
                pass
        else:
            # If no billing plan selected, clear the limits
            cleaned_data["billing_plan_limits"] = None

        return cleaned_data


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """Admin configuration for Team model."""

    form = TeamAdminForm

    list_display = (
        "name",
        "key",
        "billing_plan_display",
        "member_count",
        "custom_domain_display",
        "has_completed_wizard",
        "created_at",
        "billing_status_display",
    )

    list_filter = (
        "billing_plan",
        "custom_domain_validated",
        "has_completed_wizard",
        "created_at",
    )

    search_fields = (
        "name",
        "key",
        "billing_plan",
        "custom_domain",
    )

    readonly_fields = (
        "created_at",
        "member_count",
        "billing_status_display",
        "billing_plan_display",
        "custom_domain_status_display",
        "branding_info",
        "billing_plan_limits",
    )

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "name",
                    "key",
                    "has_completed_wizard",
                    "created_at",
                )
            },
        ),
        (
            "Billing",
            {
                "fields": (
                    "billing_plan",
                    "billing_plan_display",
                    "billing_plan_limits",
                    "billing_status_display",
                ),
                "description": (
                    "Billing and subscription information for this team. "
                    "Plan limits are auto-populated based on selected plan."
                ),
            },
        ),
        (
            "Custom Domain",
            {
                "fields": (
                    "custom_domain",
                    "custom_domain_validated",
                    "custom_domain_status_display",
                    "custom_domain_verification_failures",
                    "custom_domain_last_checked_at",
                ),
                "description": (
                    "Custom domain configuration for this workspace. Available on Business and Enterprise plans."
                ),
            },
        ),
        (
            "Branding",
            {
                "fields": ("branding_info",),
                "classes": ("collapse",),
                "description": "User-managed branding settings. This is read-only in admin.",
            },
        ),
    )

    def member_count(self, obj):
        """Display the number of members in the team."""
        count = obj.members.count()
        return format_html('<span style="color: #417690;">{} member{}</span>', count, "s" if count != 1 else "")

    member_count.short_description = "Members"

    def billing_plan_display(self, obj):
        """Display billing plan with enhanced formatting."""
        if not obj.billing_plan:
            return format_html('<span style="color: #666;">No plan</span>')

        try:
            plan = BillingPlan.objects.get(key=obj.billing_plan)
            return format_html(
                '<span style="color: #28a745; font-weight: bold;">{}</span><br><small style="color: #666;">{}</small>',
                plan.name,
                plan.description or "No description",
            )
        except BillingPlan.DoesNotExist:
            return format_html('<span style="color: #dc3545;">Invalid plan: {}</span>', obj.billing_plan)

    billing_plan_display.short_description = "Billing Plan"

    def billing_status_display(self, obj):
        """Display billing status information."""
        if not obj.billing_plan_limits:
            return format_html('<span style="color: #666;">No billing data</span>')

        limits = obj.billing_plan_limits
        stripe_customer = limits.get("stripe_customer_id")
        stripe_subscription = limits.get("stripe_subscription_id")

        if stripe_customer and stripe_subscription:
            return format_html(
                '<span style="color: #28a745;">✓ Active</span><br>'
                "<small>Customer: {}</small><br>"
                "<small>Subscription: {}</small>",
                stripe_customer[:12] + "..." if len(stripe_customer) > 12 else stripe_customer,
                stripe_subscription[:12] + "..." if len(stripe_subscription) > 12 else stripe_subscription,
            )
        else:
            return format_html('<span style="color: #ffc107;">⚠ Setup incomplete</span>')

    billing_status_display.short_description = "Billing Status"

    def custom_domain_display(self, obj):
        """Display custom domain with validation status."""
        if not obj.custom_domain:
            return format_html('<span style="color: #666;">—</span>')

        if obj.custom_domain_validated:
            return format_html(
                '<span style="color: #28a745;">✓</span> <span style="color: #417690;">{}</span>',
                obj.custom_domain,
            )
        else:
            return format_html(
                '<span style="color: #ffc107;">⚠</span> <span style="color: #666;">{}</span>',
                obj.custom_domain,
            )

    custom_domain_display.short_description = "Custom Domain"

    def custom_domain_status_display(self, obj):
        """Display detailed custom domain status."""
        if not obj.custom_domain:
            return format_html('<span style="color: #666;">No custom domain configured</span>')

        status_parts = []

        if obj.custom_domain_validated:
            status_parts.append('<span style="color: #28a745; font-weight: bold;">✓ Validated</span>')
        else:
            status_parts.append('<span style="color: #ffc107; font-weight: bold;">⚠ Pending Validation</span>')

        if obj.custom_domain_verification_failures > 0:
            status_parts.append(
                f'<small style="color: #dc3545;">'
                f"Verification failures: {obj.custom_domain_verification_failures}"
                f"</small>"
            )

        if obj.custom_domain_last_checked_at:
            from django.utils.timesince import timesince

            status_parts.append(
                f'<small style="color: #666;">Last checked: {timesince(obj.custom_domain_last_checked_at)} ago</small>'
            )

        return format_html("<br>".join(status_parts))

    custom_domain_status_display.short_description = "Domain Status"

    def get_queryset(self, request):
        """Optimize queryset with prefetch_related for members."""
        return super().get_queryset(request).prefetch_related("members")


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    """Admin configuration for Member model."""

    list_display = (
        "user",
        "team",
        "role",
        "is_default_team",
        "joined_at",
    )

    list_filter = (
        "role",
        "is_default_team",
        "joined_at",
    )

    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "team__name",
    )

    readonly_fields = ("joined_at",)

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related("user", "team")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    """Admin configuration for Invitation model."""

    list_display = (
        "email",
        "team",
        "role",
        "created_at",
        "expires_at",
        "expiry_status",
    )

    list_filter = (
        "role",
        "created_at",
        "expires_at",
    )

    search_fields = (
        "email",
        "team__name",
    )

    readonly_fields = ("created_at", "expiry_status")

    def expiry_status(self, obj):
        """Display expiration status."""
        if obj.has_expired:
            return format_html('<span style="color: #dc3545;">✗ Expired</span>')
        else:
            return format_html('<span style="color: #28a745;">✓ Valid</span>')

    expiry_status.short_description = "Status"

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related("team")
