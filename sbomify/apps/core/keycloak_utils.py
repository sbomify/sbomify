"""Utility functions for Keycloak user management."""

import json
import logging
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model

from keycloak import KeycloakAdmin, KeycloakOpenID

logger = logging.getLogger(__name__)
User = get_user_model()


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

        # Initialize master realm admin client
        self.master_admin = KeycloakAdmin(
            server_url=self.server_url,
            username=self.admin_username,
            password=self.admin_password,
            realm_name="master",  # Admin accounts are in the master realm
            verify=True,
        )

        # Initialize realm admin client by cloning master admin and switching realm
        self.admin_client = KeycloakAdmin(
            server_url=self.master_admin.server_url,
            username=self.master_admin.username,
            password=self.master_admin.password,
            realm_name=self.realm,  # Set target realm directly
            verify=True,
            token=self.master_admin.token,  # Reuse the authentication token
        )
        logger.info(f"Configured KeycloakAdmin for realm: {self.admin_client.realm_name}")

        # Initialize OpenID client
        self.openid_client = self._get_openid_client()

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
                "emailVerified": True,  # Assume emails are verified since they were verified in social login
                "attributes": {
                    "company": [],
                    "supplier_contact": [],
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

    def create_realm(self) -> bool:
        """Create the realm in Keycloak if it doesn't exist.

        Returns:
            bool: True if realm was created, False if it already existed.
        """
        try:
            # Check if realm exists
            realms = self.master_admin.get_realms()
            for realm in realms:
                if realm.get("realm") == self.realm:
                    logger.info(f"Realm '{self.realm}' already exists in Keycloak")
                    return False

            # Realm configuration
            realm_representation = {
                "realm": self.realm,
                "enabled": True,
                "displayName": self.realm,
                "registrationAllowed": False,
                "resetPasswordAllowed": True,
                "loginWithEmailAllowed": True,
                "duplicateEmailsAllowed": False,
                "sslRequired": "external",
            }

            # Create the realm
            self.master_admin.create_realm(payload=realm_representation, skip_exists=True)
            logger.info(f"Created realm '{self.realm}' in Keycloak")
            return True
        except Exception as e:
            logger.error(f"Failed to create realm: {str(e)}")
            raise

    def create_client(self) -> str | None:
        """Create the client in the realm if it doesn't exist.

        Returns:
            str | None: The client secret if client was created, None if it already existed.
        """
        try:
            # Check if client exists
            clients = self.admin_client.get_clients()
            for client in clients:
                if client.get("clientId") == self.client_id:
                    logger.info(f"Client '{self.client_id}' already exists in realm '{self.realm}'")
                    return None

            # Prepare redirect URIs
            redirect_uris = [f"{settings.APP_BASE_URL}/*"]

            # Add WEBSITE_BASE_URL if it exists
            if hasattr(settings, "WEBSITE_BASE_URL"):
                redirect_uris.append(f"{settings.WEBSITE_BASE_URL}/*")
            # If not available, check if defined in environment but not loaded in settings
            elif hasattr(settings, "VITE_WEBSITE_BASE_URL"):
                redirect_uris.append(f"{settings.VITE_WEBSITE_BASE_URL}/*")

            # Client configuration
            client_representation = {
                "clientId": self.client_id,
                "name": self.client_id,
                "enabled": True,
                "clientAuthenticatorType": "client-secret",
                "secret": self.client_secret or str(uuid.uuid4()),
                "redirectUris": redirect_uris,
                "webOrigins": ["+"],
                "publicClient": False,
                "protocol": "openid-connect",
                "bearerOnly": False,
                "standardFlowEnabled": True,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": True,
                "serviceAccountsEnabled": True,
                "authorizationServicesEnabled": False,
            }

            # Create the client
            client_id = self.admin_client.create_client(payload=client_representation)
            logger.info(f"Created client '{self.client_id}' in realm '{self.realm}'")

            # Get the client secret
            client_secret = self.admin_client.get_client_secrets(client_id)["value"]
            logger.info(f"Generated client secret for client '{self.client_id}'")

            return client_secret
        except Exception as e:
            logger.error(f"Failed to create client: {str(e)}")
            raise

    def ensure_realm_and_client(self) -> str | None:
        """Ensure the realm and client exist, creating them if necessary.

        Returns:
            str | None: The client secret if a new client was created, None if client already existed.
        """
        # Create realm if needed
        self.create_realm()

        # Create client if needed and return the client secret
        return self.create_client()

    def create_user_data(self, user: User) -> dict:
        """Create user data for Keycloak."""
        return {
            "username": user.username,
            "email": user.email,
            "firstName": user.first_name,
            "lastName": user.last_name,
            "enabled": True,
            "emailVerified": True,  # Assume emails are verified since they were verified in social login
            "attributes": {
                "company": [user.company] if hasattr(user, "company") else [],
                "supplier_contact": [json.dumps(user.supplier_contact)] if hasattr(user, "supplier_contact") else [],
            },
        }
