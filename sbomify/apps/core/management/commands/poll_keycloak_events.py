"""Django management command to poll Keycloak events."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from sbomify.apps.core.keycloak_events import run_event_polling


class Command(BaseCommand):
    """Command to poll Keycloak events and process them."""

    help = "Polls Keycloak events and processes them"

    def handle(self, *args: Any, **options: Any) -> Any:
        """Run the command."""
        self.stdout.write(self.style.SUCCESS("Starting Keycloak event polling"))
        run_event_polling()
