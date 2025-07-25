"""Command to migrate users from Django to Keycloak."""

import logging
import os
import secrets
import string

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.keycloak_utils import KeycloakManager
from core.models import User

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Command to migrate users from Django to Keycloak."""

    help = "Migrate existing users from Django to Keycloak"

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            "--send-reset-emails",
            action="store_true",
            help="Send password reset emails to migrated users",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without actually creating users in Keycloak",
        )
        parser.add_argument(
            "--user-email",
            type=str,
            help="Migrate a specific user by email",
        )
        parser.add_argument(
            "--skip-realm-setup",
            action="store_true",
            help="Skip checking and creating realm and client",
        )

    def handle(self, *args, **options):
        """Run the command."""
        dry_run = options["dry_run"]
        send_reset_emails = options["send_reset_emails"]
        specific_email = options["user_email"]
        skip_realm_setup = options["skip_realm_setup"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in dry run mode. No changes will be made in Keycloak."))

        # Initialize Keycloak manager
        try:
            keycloak_manager = KeycloakManager()
        except Exception as e:
            raise CommandError(f"Failed to initialize Keycloak manager: {str(e)}")

        # Check and create realm and client if needed
        if not skip_realm_setup and not dry_run:
            try:
                self.setup_keycloak_realm_and_client(keycloak_manager)
            except Exception as e:
                raise CommandError(f"Failed to setup Keycloak realm and client: {str(e)}")

        # Get users to migrate
        if specific_email:
            users = User.objects.filter(email=specific_email)
            if not users.exists():
                raise CommandError(f"User with email {specific_email} not found")
        else:
            users = User.objects.all()

        self.stdout.write(f"Found {users.count()} users to migrate")

        success_count = 0
        error_count = 0

        # Migrate users
        for user in users:
            try:
                self.migrate_user(user, keycloak_manager, dry_run, send_reset_emails)
                success_count += 1
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"Failed to migrate user {user.email}: {str(e)}"))
                logger.error(f"Failed to migrate user {user.email}: {str(e)}")

        # Report results
        self.stdout.write(
            self.style.SUCCESS(
                f"Migration completed. {success_count} users migrated successfully, {error_count} failed."
            )
        )

    def setup_keycloak_realm_and_client(self, keycloak_manager: KeycloakManager) -> None:
        """Check and create Keycloak realm and client if they don't exist."""
        self.stdout.write("Checking Keycloak realm and client configuration...")

        # Ensure realm and client exist
        client_secret = keycloak_manager.ensure_realm_and_client()

        # If client secret is different from the one in settings, update it
        if client_secret and client_secret != settings.KEYCLOAK_CLIENT_SECRET:
            self.stdout.write(
                self.style.WARNING(
                    f"Client secret in Keycloak is different from the one in settings. "
                    f"You may need to update your .env file with: KEYCLOAK_CLIENT_SECRET={client_secret}"
                )
            )

            # Try to update the .env file if possible
            env_file_path = os.path.join(settings.BASE_DIR, ".env")
            if os.path.exists(env_file_path):
                try:
                    self.update_env_file(env_file_path, "KEYCLOAK_CLIENT_SECRET", client_secret)
                    self.stdout.write(self.style.SUCCESS("Updated KEYCLOAK_CLIENT_SECRET in .env file"))
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Failed to update .env file: {str(e)}. "
                            f"Please manually update KEYCLOAK_CLIENT_SECRET to {client_secret}"
                        )
                    )
            else:
                self.stdout.write(self.style.WARNING(".env file not found. Please manually update your configuration"))

        self.stdout.write(self.style.SUCCESS("Keycloak realm and client are properly configured"))

    def update_env_file(self, file_path: str, key: str, value: str) -> None:
        """Update a value in .env file."""
        with open(file_path, "r") as file:
            lines = file.readlines()

        key_exists = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                key_exists = True
                break

        if not key_exists:
            lines.append(f"{key}={value}\n")

        with open(file_path, "w") as file:
            file.writelines(lines)

    def migrate_user(
        self, user: User, keycloak_manager: KeycloakManager, dry_run: bool, send_reset_email: bool
    ) -> None:
        """Migrate a user to Keycloak."""
        if not user.email:
            self.stdout.write(self.style.WARNING(f"Skipping user {user.username} - no email address"))
            return

        self.stdout.write(f"Migrating user {user.username} ({user.email})")

        # In dry run mode, just log what would happen
        if dry_run:
            self.stdout.write(f"  Would create user {user.username} ({user.email}) in Keycloak")
            if send_reset_email:
                self.stdout.write(f"  Would send password reset email to {user.email}")
            return

        # Create user in Keycloak
        user_id = keycloak_manager.create_user(
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
        )

        self.stdout.write(self.style.SUCCESS(f"  Created user {user.username} in Keycloak with ID {user_id}"))

        # Set a random temporary password (required by Keycloak)
        random_password = self.generate_random_password()
        keycloak_manager.set_temporary_password(user_id, random_password, True)

        # In development mode, indicate that password was set without showing it
        if settings.DEBUG:
            self.stdout.write(
                self.style.WARNING(
                    f"  DEV MODE: Temporary password set for {user.username} (password not displayed for security)"
                )
            )

        # Send password reset email if requested
        if send_reset_email:
            success = keycloak_manager.request_password_reset_email(user.email)
            if success:
                self.stdout.write(self.style.SUCCESS(f"  Sent password reset email to {user.email}"))
            else:
                self.stdout.write(self.style.ERROR(f"  Failed to send password reset email to {user.email}"))

    def generate_random_password(self, length: int = 16) -> str:
        """Generate a random password."""
        alphabet = string.ascii_letters + string.digits + string.punctuation
        return "".join(secrets.choice(alphabet) for _ in range(length))
