"""Django app configuration for the plugins framework."""

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class PluginsConfig(AppConfig):
    """Configuration for the plugins app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.plugins"
    label = "plugins"

    def ready(self) -> None:
        """Connect to post_migrate signal to register built-in plugins."""
        from django.db.models.signals import post_migrate

        post_migrate.connect(self._on_post_migrate, sender=self)

    def _on_post_migrate(self, **kwargs) -> None:
        """Register built-in plugins after migrations complete."""
        self._register_builtin_plugins()

    def _register_builtin_plugins(self) -> None:
        """Register all built-in plugins."""
        from django.db.utils import OperationalError, ProgrammingError

        from .models import RegisteredPlugin

        try:
            # NTIA Minimum Elements 2021 Plugin
            RegisteredPlugin.objects.update_or_create(
                name="ntia-minimum-elements-2021",
                defaults={
                    "display_name": "NTIA Minimum Elements (2021)",
                    "description": (
                        "Validates SBOMs against the NTIA Minimum Elements for a Software Bill "
                        "of Materials as defined in the July 2021 report. Checks for: Supplier Name, "
                        "Component Name, Version, Unique Identifiers, Dependency Relationship, "
                        "SBOM Author, and Timestamp."
                    ),
                    "category": "compliance",
                    "version": "1.0.0",
                    "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
                    "is_enabled": True,
                    "default_config": {},
                },
            )
        except (OperationalError, ProgrammingError) as e:
            # Table doesn't exist yet (e.g., during initial migrations)
            logger.debug("Could not register built-in plugins (table may not exist yet): %s", e)
