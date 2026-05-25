from django.apps import AppConfig


class OIDCConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.oidc"
    label = "oidc"
    verbose_name = "OIDC Trusted Publishing"

    def ready(self) -> None:
        # Import to register the post_delete handler (reaps the synthetic
        # bot User when a binding is removed) AND the pre_save handler on
        # Member (forbids ``role="bot"`` outside the OIDC provisioning
        # flow).
        import sbomify.apps.oidc.signals  # noqa: F401
