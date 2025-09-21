"""Module for handling Keycloak user events through polling."""

import logging
import time
from datetime import datetime, timedelta

from django.conf import settings

from sbomify.apps.core.keycloak_utils import KeycloakManager

logger = logging.getLogger(__name__)


class KeycloakEventPoller:
    """Polls Keycloak for user events and processes them."""

    def __init__(self):
        """Initialize the event poller with Keycloak manager."""
        self.keycloak_manager = KeycloakManager()
        self.last_poll_time = datetime.now() - timedelta(minutes=5)  # Start with events from 5 minutes ago

    def poll_events(self) -> list[dict]:
        """
        Poll Keycloak for events since the last poll time.

        Returns:
            List of event dictionaries
        """
        try:
            # Convert to milliseconds timestamp for Keycloak API
            from_time = int(self.last_poll_time.timestamp() * 1000)

            # Get admin client
            admin_client = self.keycloak_manager.admin_client

            # Get events from Keycloak
            events = admin_client.get_events(
                query_params={
                    "dateFrom": from_time,
                    "type": ["LOGIN", "LOGOUT", "REGISTER", "DELETE_ACCOUNT", "UPDATE_PROFILE"],
                }
            )

            # Update last poll time
            self.last_poll_time = datetime.now()

            return events
        except Exception as e:
            logger.error(f"Error polling Keycloak events: {e}", exc_info=True)
            return []

    def process_events(self, events: list[dict]) -> None:
        """
        Process events from Keycloak.

        Args:
            events: List of event dictionaries from Keycloak
        """
        for event in events:
            try:
                event_type = event.get("type")
                user_id = event.get("userId")

                if not user_id:
                    continue

                logger.info(f"Processing Keycloak event: {event_type} for user {user_id}")

                # Handle different event types
                if event_type == "DELETE_ACCOUNT":
                    self._handle_delete_account(user_id)
                elif event_type == "UPDATE_PROFILE":
                    self._handle_update_profile(user_id, event.get("details", {}))
                # Add more event handlers as needed

            except Exception as e:
                logger.error(f"Error processing event {event}: {e}", exc_info=True)

    def _handle_delete_account(self, user_id: str) -> None:
        """
        Handle a DELETE_ACCOUNT event.

        Args:
            user_id: The Keycloak user ID
        """
        # Find the Django user with this Keycloak ID
        from allauth.socialaccount.models import SocialAccount

        try:
            social_account = SocialAccount.objects.get(uid=user_id)
            django_user = social_account.user

            # Log the deletion
            logger.info(f"User {django_user.username} (ID: {django_user.id}) deleted their Keycloak account")

            # Mark the user as inactive in Django
            django_user.is_active = False
            django_user.save()

            # Alternatively, you could delete the user:
            # django_user.delete()

        except SocialAccount.DoesNotExist:
            logger.warning(f"Cannot find Django user for Keycloak user ID {user_id}")

    def _handle_update_profile(self, user_id: str, details: dict) -> None:
        """
        Handle an UPDATE_PROFILE event.

        Args:
            user_id: The Keycloak user ID
            details: The event details
        """
        # Find the Django user with this Keycloak ID
        from allauth.socialaccount.models import SocialAccount

        try:
            social_account = SocialAccount.objects.get(uid=user_id)
            django_user = social_account.user

            # If the event includes updated email
            updated_email = details.get("updated_email")
            if updated_email:
                django_user.email = updated_email
                django_user.save()
                logger.info(f"Updated email for user {django_user.username} to {updated_email}")

        except SocialAccount.DoesNotExist:
            logger.warning(f"Cannot find Django user for Keycloak user ID {user_id}")


def run_event_polling():
    """Run the event polling process."""
    if not settings.USE_KEYCLOAK:
        logger.info("Keycloak is not enabled, skipping event polling")
        return

    logger.info("Starting Keycloak event polling")
    poller = KeycloakEventPoller()

    try:
        while True:
            # Poll for events
            events = poller.poll_events()

            # Process events
            if events:
                logger.info(f"Found {len(events)} Keycloak events")
                poller.process_events(events)

            # Sleep before the next poll
            time.sleep(60)  # Poll every minute
    except KeyboardInterrupt:
        logger.info("Keycloak event polling stopped")
    except Exception as e:
        logger.error(f"Error in Keycloak event polling: {e}", exc_info=True)


if __name__ == "__main__":
    # This allows running the poller as a standalone script
    run_event_polling()
