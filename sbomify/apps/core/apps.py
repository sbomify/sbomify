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

        # allauth builds the OpenID Connect provider's URLs from a fixed
        # adapter class, so client_class is the seam it leaves for choosing a
        # client. Pointing it at ours is what stops the authorize URL spelling
        # its scope separators with a character that only means a space under
        # form-urlencoding rules.
        from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter

        from sbomify.apps.core.adapters import SpaceEncodedOAuth2Client

        OpenIDConnectOAuth2Adapter.client_class = SpaceEncodedOAuth2Client
