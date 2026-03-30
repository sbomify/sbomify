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
        self._validate_storage_credentials()

    @staticmethod
    def _validate_storage_credentials() -> None:
        from django.conf import settings

        from sbomify.apps.core.object_store import _VALID_BUCKET_TYPES

        if getattr(settings, "STORAGE_BACKEND", "s3") != "s3":
            return

        for bucket_type in _VALID_BUCKET_TYPES:
            access_key = getattr(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID", None) or None
            secret_key = getattr(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY", None) or None
            if (access_key is None) != (secret_key is None):
                raise ValueError(
                    f"AWS_{bucket_type}_ACCESS_KEY_ID and AWS_{bucket_type}_SECRET_ACCESS_KEY "
                    f"must both be set or both be empty"
                )
