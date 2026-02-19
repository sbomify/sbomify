from django.apps import AppConfig


class TeaConfig(AppConfig):
    """Django app configuration for Transparency Exchange API (TEA)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.tea"
    verbose_name = "Transparency Exchange API"
