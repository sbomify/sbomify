from django.apps import AppConfig


class SbomsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sboms"

    def ready(self):
        import sboms.signals  # noqa
