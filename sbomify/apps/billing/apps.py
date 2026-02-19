from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.billing"
    label = "billing"
    verbose_name = "Billing"

    def ready(self):
        # Import signals and tasks to register them with Django and Dramatiq
        from . import signals, tasks  # noqa: F401
