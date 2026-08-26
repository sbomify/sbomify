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

        # Build both API versions now rather than on the first request.
        #
        # Django imports ROOT_URLCONF lazily, so without this the v2 schemas
        # are derived inside whatever state the first request happens to find.
        # Under the e2e suite that is a frozen clock: freezegun replaces
        # datetime.datetime with FakeDatetime, pydantic's type dispatch matches
        # on identity, and regenerating a model with a datetime field raises
        # PydanticSchemaGenerationError. Every later request then re-imports a
        # module whose routers are already attached and fails with a
        # ConfigError naming v1, which is three steps removed from the cause.
        #
        # Building at startup also means a malformed API surface breaks the
        # boot rather than the first caller.
        import sbomify.apis  # noqa: F401
