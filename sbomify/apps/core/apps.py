from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.core"
    label = "core"

    def ready(self) -> None:
        # Import signals to register them
        import atexit

        import sbomify.apps.core.signals  # noqa: F401
        from sbomify.apps.core.posthog_service import shutdown

        atexit.register(shutdown)
