from django.apps import AppConfig


class SbomsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.sboms"
    label = "sboms"

    def ready(self):
        import sbomify.apps.sboms.signals  # noqa
