import logging
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .utils import PRICE_VALIDATION_TOLERANCE, is_test_environment

logger = logging.getLogger(__name__)


class BillingPlan(models.Model):
    """Billing plan model with plan key constants."""

    # Plan key constants
    KEY_COMMUNITY = "community"
    KEY_BUSINESS = "business"
    KEY_ENTERPRISE = "enterprise"

    class Meta:
        db_table = apps.get_app_config("billing").label + "_plans"
        indexes = [
            models.Index(fields=["key"]),
            models.Index(fields=["stripe_product_id"]),
        ]
        ordering = ["name"]
        verbose_name = "Billing Plan"
        verbose_name_plural = "Billing Plans"

    key = models.CharField(max_length=30, unique=True, null=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    max_products = models.IntegerField(
        null=True, blank=True, help_text="Maximum number of products allowed. Leave blank for unlimited."
    )
    max_projects = models.IntegerField(
        null=True, blank=True, help_text="Maximum number of projects allowed. Leave blank for unlimited."
    )
    max_components = models.IntegerField(
        null=True, blank=True, help_text="Maximum number of components allowed. Leave blank for unlimited."
    )
    max_users = models.IntegerField(
        null=True, blank=True, help_text="Maximum number of users/members allowed in a team. Leave blank for unlimited."
    )
    stripe_product_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    stripe_price_monthly_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    stripe_price_annual_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    monthly_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="The cost per month for monthly billing (Display only - must match Stripe).",
    )
    annual_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="The cost per year for annual billing (Display only - must match Stripe).",
    )
    discount_percent_monthly = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Promotional discount percentage for monthly billing.",
    )
    discount_percent_annual = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Promotional discount percentage for annual billing.",
    )
    promo_message = models.CharField(
        max_length=255, null=True, blank=True, help_text="Optional promotional message to display."
    )
    last_synced_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of last Stripe price sync.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Flag to skip team updates during pricing sync (set by StripePricingService)
        self._skip_team_update = False

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"

    @property
    def has_ntia_compliance(self) -> bool:
        """Check if this plan includes NTIA Minimum Elements compliance checking."""
        return self.key in ["business", "enterprise"]

    @property
    def has_vulnerability_scanning(self) -> bool:
        """Check if this plan includes vulnerability scanning.

        Note: OSV vulnerability scanning is available for ALL teams.
        This property now indicates if Dependency Track is available.
        """
        return True

    @property
    def has_dependency_track_access(self) -> bool:
        """Check if this plan includes Dependency Track access."""
        return self.key in ["business", "enterprise"]

    @property
    def allows_unlimited_users(self) -> bool:
        """Check if this plan allows unlimited users."""
        return self.max_users is None

    @property
    def has_custom_domain_access(self) -> bool:
        """Check if this plan includes custom domain feature."""
        return self.key in ["business", "enterprise"]

    @property
    def monthly_price_discounted(self) -> Decimal | None:
        """Calculate discounted monthly price."""
        if self.monthly_price is None:
            return None
        discount = Decimal(self.discount_percent_monthly) / Decimal("100")
        return self.monthly_price * (Decimal("1") - discount)

    @property
    def annual_price_discounted(self) -> Decimal | None:
        """Calculate discounted annual price."""
        if self.annual_price is None:
            return None
        discount = Decimal(self.discount_percent_annual) / Decimal("100")
        return self.annual_price * (Decimal("1") - discount)

    @property
    def monthly_savings(self) -> Decimal | None:
        """Calculate savings amount for monthly billing if discount is applied."""
        if self.monthly_price is None or self.discount_percent_monthly == 0:
            return None
        return self.monthly_price - self.monthly_price_discounted

    @property
    def annual_savings(self) -> Decimal | None:
        """Calculate savings amount for annual billing if discount is applied."""
        if self.annual_price is None or self.discount_percent_annual == 0:
            return None
        return self.annual_price - self.annual_price_discounted

    @property
    def annual_vs_monthly_savings(self) -> Decimal | None:
        """Calculate total savings when choosing annual over monthly billing."""
        if self.monthly_price is None or self.annual_price is None:
            return None
        monthly_yearly_total = self.monthly_price_discounted * Decimal("12")
        annual_total = self.annual_price_discounted
        return monthly_yearly_total - annual_total

    @property
    def annual_discount_percent(self) -> Decimal | None:
        """Calculate percentage discount of annual vs monthly billing."""
        if self.monthly_price is None or self.annual_price is None:
            return None
        monthly_yearly_total = self.monthly_price_discounted * Decimal("12")
        if monthly_yearly_total == 0:
            return None
        annual_total = self.annual_price_discounted
        discount = ((monthly_yearly_total - annual_total) / monthly_yearly_total) * Decimal("100")
        return discount.quantize(Decimal("0.1"))

    @property
    def total_annual_savings(self) -> Decimal | None:
        """Calculate total savings when choosing annual billing."""
        annual_vs_monthly = (
            self.annual_vs_monthly_savings if self.annual_vs_monthly_savings is not None else Decimal("0")
        )
        promo_savings = self.annual_savings if self.annual_savings is not None else Decimal("0")
        total = annual_vs_monthly + promo_savings
        return total if total > 0 else None

    def clean(self):
        """Validate prices against Stripe when price IDs are set."""
        from sbomify.apps.billing.stripe_client import StripeClient, StripeError

        # Skip validation in test environments
        if is_test_environment():
            return

        # Community plan doesn't require Stripe IDs
        if self.key == "community":
            return

        # Only validate if we have Stripe price IDs
        if not (self.stripe_price_monthly_id or self.stripe_price_annual_id):
            return

        try:
            stripe_client = StripeClient()

            # Validate monthly price
            if self.stripe_price_monthly_id and self.monthly_price is not None:
                try:
                    stripe_price = stripe_client.get_price(self.stripe_price_monthly_id)
                    stripe_amount = (
                        Decimal(stripe_price.unit_amount) / Decimal("100") if stripe_price.unit_amount else Decimal("0")
                    )
                    price_diff = abs(Decimal(str(self.monthly_price)) - stripe_amount)
                    if price_diff > PRICE_VALIDATION_TOLERANCE:
                        raise ValidationError(
                            {
                                "monthly_price": (
                                    f"Monthly price ${self.monthly_price} does not match "
                                    f"Stripe price ${stripe_amount} for price ID {self.stripe_price_monthly_id}"
                                )
                            }
                        )
                except StripeError as e:
                    logger.error("Failed to validate monthly price for plan %s: %s", self.key, str(e))
                    # Don't raise - allow save to proceed if Stripe is temporarily unavailable
                    # This prevents blocking admin updates during Stripe outages

            # Validate annual price
            if self.stripe_price_annual_id and self.annual_price is not None:
                try:
                    stripe_price = stripe_client.get_price(self.stripe_price_annual_id)
                    stripe_amount = (
                        Decimal(stripe_price.unit_amount) / Decimal("100") if stripe_price.unit_amount else Decimal("0")
                    )
                    price_diff = abs(Decimal(str(self.annual_price)) - stripe_amount)
                    if price_diff > PRICE_VALIDATION_TOLERANCE:
                        raise ValidationError(
                            {
                                "annual_price": (
                                    f"Annual price ${self.annual_price} does not match "
                                    f"Stripe price ${stripe_amount} for price ID {self.stripe_price_annual_id}"
                                )
                            }
                        )
                except StripeError as e:
                    logger.error("Failed to validate annual price for plan %s: %s", self.key, str(e))
                    # Don't raise - allow save to proceed if Stripe is temporarily unavailable

        except ValidationError:
            raise
        except Exception:
            logger.exception("Unexpected error during price validation for plan %s", self.key)

    def _update_teams_with_new_limits(self):
        """
        Update all teams using this plan with the current limits from the model.

        Uses bulk_update for efficiency when updating multiple teams.
        Only updates teams whose limits actually changed (idempotent).
        """
        from sbomify.apps.teams.models import Team

        teams = Team.objects.filter(billing_plan=self.key)
        team_count = teams.count()

        if team_count == 0:
            return

        # Prepare updates for bulk operation - only for teams that actually need updates
        teams_to_update = []
        new_limit_values = {
            "max_products": self.max_products,
            "max_projects": self.max_projects,
            "max_components": self.max_components,
            "max_users": self.max_users,
        }

        for team in teams:
            existing_limits = team.billing_plan_limits or {}

            # Check if limits actually changed (idempotency check)
            needs_update = False
            for key, new_value in new_limit_values.items():
                if existing_limits.get(key) != new_value:
                    needs_update = True
                    break

            if not needs_update:
                continue

            new_limits = existing_limits.copy()
            new_limits.update(new_limit_values)
            team.billing_plan_limits = new_limits
            teams_to_update.append(team)

        # Use bulk_update for better performance
        if teams_to_update:
            Team.objects.bulk_update(teams_to_update, ["billing_plan_limits"], batch_size=100)

    def save(self, *args, **kwargs):
        """
        Override save to call clean() for validation.

        Always validates pricing fields when they are present, regardless of update_fields.
        This prevents bypassing validation by excluding pricing fields from update_fields.
        """
        update_fields = kwargs.get("update_fields")

        # Always validate if not using update_fields
        if not update_fields:
            self.full_clean()
        else:
            # Check if any pricing fields are being updated
            pricing_fields = {
                "monthly_price",
                "annual_price",
                "stripe_price_monthly_id",
                "stripe_price_annual_id",
            }
            if pricing_fields.intersection(set(update_fields)):
                # Validate all pricing fields, not just the ones being updated
                # This ensures consistency and prevents partial invalid states
                self.full_clean()

        super().save(*args, **kwargs)

    @property
    def has_fda_compliance(self) -> bool:
        """Check if this plan includes FDA Medical Device Cybersecurity compliance checking."""
        return self.key in ["business", "enterprise"]
