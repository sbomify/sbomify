from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.core"
    label = "core"

    def ready(self) -> None:
        # Import signals + cron to register them with Django and Dramatiq.
        # Without importing cron here the `purge_soft_deleted_users` actor is
        # never registered with the dramatiq worker, so messages from the
        # scheduler container would accumulate undelivered.
        import atexit

        import sbomify.apps.core.cron  # noqa: F401
        import sbomify.apps.core.signals  # noqa: F401
        from sbomify.apps.core.posthog_service import shutdown

        atexit.register(shutdown)
        self._validate_storage_credentials()

    @staticmethod
    def _validate_storage_credentials() -> None:
        import os

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

        # The documents credentials fall back to the SBOMs ones per variable, so
        # supplying only the access key resolves to a pair that looks complete
        # and is not: the documents key alongside the SBOMs secret. The loop
        # above reads the resolved settings and cannot see that, so ask the
        # environment what was actually provided. MEDIA and SBOMS have no
        # fallback and need no equivalent.
        doc_access = os.environ.get("AWS_DOCUMENTS_ACCESS_KEY_ID") or None
        doc_secret = os.environ.get("AWS_DOCUMENTS_SECRET_ACCESS_KEY") or None
        if (doc_access is None) != (doc_secret is None):
            raise ValueError(
                "AWS_DOCUMENTS_ACCESS_KEY_ID and AWS_DOCUMENTS_SECRET_ACCESS_KEY must both be "
                "set or both be empty. Setting only one pairs it with the SBOMs credential it "
                "falls back to, which will fail against the documents bucket."
            )
