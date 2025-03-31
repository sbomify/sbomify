"""Command to migrate users from Django to Keycloak."""

import logging
import secrets
import string

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

    def handle(self, *args, **options):
        """Run the command."""
        dry_run = options["dry_run"]
        send_reset_emails = options["send_reset_emails"]
        specific_email = options["user_email"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in dry run mode. No users will be created in Keycloak."))

        # Initialize Keycloak manager
        try:
            keycloak_manager = KeycloakManager()
        except Exception as e:
            raise CommandError(f"Failed to initialize Keycloak manager: {str(e)}")

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
