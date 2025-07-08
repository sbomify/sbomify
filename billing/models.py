from django.apps import apps
from django.db import models


# Create your models here.
class BillingPlan(models.Model):
    class Meta:
        db_table = apps.get_app_config("billing").name + "_plans"
        indexes = [models.Index(fields=["key"])]
        ordering = ["name"]

    key = models.CharField(max_length=30, unique=True, null=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    max_products = models.IntegerField(null=True)
    max_projects = models.IntegerField(null=True)
    max_components = models.IntegerField(null=True)
    max_users = models.IntegerField(
        null=True, help_text="Maximum number of users/members allowed in a team. Null means unlimited."
    )
    stripe_product_id = models.CharField(max_length=100, null=True)
    stripe_price_monthly_id = models.CharField(max_length=100, null=True)
    stripe_price_annual_id = models.CharField(max_length=100, null=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"

    @property
    def has_ntia_compliance(self) -> bool:
        """Check if this plan includes NTIA Minimum Elements compliance checking."""
        return self.key in ["business", "enterprise"]

    @property
    def has_vulnerability_scanning(self) -> bool:
        """Check if this plan includes vulnerability scanning."""
        return self.key in ["business", "enterprise"]

    @property
    def allows_unlimited_users(self) -> bool:
        """Check if this plan allows unlimited users."""
        return self.max_users is None
