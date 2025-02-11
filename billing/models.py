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
    stripe_product_id = models.CharField(max_length=100, null=True)
    stripe_price_monthly_id = models.CharField(max_length=100, null=True)
    stripe_price_annual_id = models.CharField(max_length=100, null=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"
