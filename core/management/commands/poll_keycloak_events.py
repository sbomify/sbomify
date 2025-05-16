"""Django management command to poll Keycloak events."""

from django.core.management.base import BaseCommand

from core.keycloak_events import run_event_polling


class Command(BaseCommand):
    """Command to poll Keycloak events and process them."""

    help = "Polls Keycloak events and processes them"

    def handle(self, *args, **options):
        """Run the command."""
        self.stdout.write(self.style.SUCCESS("Starting Keycloak event polling"))
        run_event_polling()
