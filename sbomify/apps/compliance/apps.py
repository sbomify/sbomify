from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.compliance"
    label = "compliance"

    def ready(self) -> None:
        from . import checks, signals, tasks  # noqa: F401
