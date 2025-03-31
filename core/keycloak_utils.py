"""Utility functions for Keycloak user management."""

import logging

from django.conf import settings

try:
    # Try importing from python-keycloak
    from python_keycloak import KeycloakAdmin, KeycloakOpenID
except ImportError:
    try:
        # Try importing from keycloak
        from keycloak import KeycloakAdmin, KeycloakOpenID
    except ImportError:
        # For the older versions of python-keycloak
        from keycloak.keycloak_admin import KeycloakAdmin
        from keycloak.keycloak_openid import KeycloakOpenID

logger = logging.getLogger(__name__)


class KeycloakManager:
    """Manager for Keycloak operations."""

    def __init__(self):
        """Initialize the Keycloak manager."""
        self.server_url = settings.KEYCLOAK_SERVER_URL
        self.client_id = settings.KEYCLOAK_CLIENT_ID
        self.client_secret = settings.KEYCLOAK_CLIENT_SECRET
        self.realm = settings.KEYCLOAK_REALM
        self.admin_username = settings.KEYCLOAK_ADMIN_USERNAME
        self.admin_password = settings.KEYCLOAK_ADMIN_PASSWORD

        logger.debug(f"Initializing KeycloakManager with target realm: {self.realm}")

        # Initialize admin client with proper realm configuration
        self.admin_client = self._get_admin_client()

        # Initialize OpenID client
        self.openid_client = self._get_openid_client()

    def _get_admin_client(self) -> KeycloakAdmin:
        """Get a Keycloak admin client.

        First authenticates with the master realm (required for admin),
        then changes to the target realm for operations.
        """
        # First authenticate with the master realm
        admin = KeycloakAdmin(
            server_url=self.server_url,
            username=self.admin_username,
            password=self.admin_password,
            realm_name="master",  # Admin accounts are in the master realm
            verify=True,
        )

        # Now switch to our target realm for subsequent operations
        admin.realm_name = self.realm

        # Log the configuration
        logger.info(f"Configured KeycloakAdmin for realm: {admin.realm_name}")

        return admin

    def _get_openid_client(self) -> KeycloakOpenID:
        """Get a Keycloak OpenID client."""
        return KeycloakOpenID(
            server_url=self.server_url,
            client_id=self.client_id,
            realm_name=self.realm,
            client_secret_key=self.client_secret,
        )

    def create_user(
        self, username: str, email: str, first_name: str = "", last_name: str = "", enabled: bool = True
    ) -> str:
        """Create a user in Keycloak."""
        try:
            # Check if user already exists by email
            existing_user = self.find_user_by_email(email)
            if existing_user:
                logger.info(f"User with email {email} already exists in Keycloak")
                return existing_user[0]["id"]

            # Create user
            user_data = {
                "username": username,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": enabled,
                "emailVerified": True,  # Assume emails are verified since they were verified in Auth0
                "attributes": {
                    "migrated_from_auth0": ["true"],
                    "migration_date": [self._get_current_time()],
                },
            }

            user_id = self.admin_client.create_user(user_data)
            logger.info(f"Created user {username} ({email}) in Keycloak with ID {user_id}")

            return user_id
        except Exception as e:
            logger.error(f"Failed to create user {username} in Keycloak: {str(e)}")
            raise

    def find_user_by_email(self, email: str) -> list[dict]:
        """Find a user in Keycloak by email."""
        try:
            users = self.admin_client.get_users({"email": email})
            return users
        except Exception as e:
            logger.error(f"Failed to find user with email {email} in Keycloak: {str(e)}")
            return []

    def _get_current_time(self) -> str:
        """Get the current time in ISO format."""
        from datetime import datetime

        return datetime.utcnow().isoformat()

    def set_temporary_password(self, user_id: str, password: str, temporary: bool = True) -> None:
        """Set a temporary password for a user."""
        try:
            self.admin_client.set_user_password(user_id, password, temporary)
            logger.info(f"Set temporary password for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to set temporary password for user {user_id}: {str(e)}")
            raise

    def request_password_reset_email(self, email: str) -> bool:
        """Send a password reset email to a user."""
        try:
            users = self.find_user_by_email(email)
            if not users:
                logger.warning(f"Cannot send password reset email: User with email {email} not found in Keycloak")
                return False

            user_id = users[0]["id"]
            # Execute password reset email action
            self.admin_client.send_update_account(user_id=user_id, payload=["UPDATE_PASSWORD"])
            logger.info(f"Sent password reset email to {email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send password reset email to {email}: {str(e)}")
            return False
