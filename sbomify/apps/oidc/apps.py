from django.apps import AppConfig


class OIDCConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.oidc"
    label = "oidc"
    verbose_name = "OIDC Trusted Publishing"

    def ready(self) -> None:
        # Import to register the post_delete handler that reaps the
        # synthetic bot User when a binding is removed.
        import sbomify.apps.oidc.signals  # noqa: F401
