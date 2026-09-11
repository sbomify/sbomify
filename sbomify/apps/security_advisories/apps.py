from django.apps import AppConfig


class SecurityAdvisoriesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.security_advisories"
    label = "security_advisories"

    def ready(self) -> None:
        from sbomify.apps.security_advisories import signals  # noqa: F401
