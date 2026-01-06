"""Django app configuration for the plugins framework."""

from django.apps import AppConfig


class PluginsConfig(AppConfig):
    """Configuration for the plugins app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.plugins"
    label = "plugins"
