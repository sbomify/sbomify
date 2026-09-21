"""Ops app configuration."""

from django.apps import AppConfig


class OpsConfig(AppConfig):
    """Configuration for the internal ops dashboard."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.ops"
    verbose_name = "Ops"
