import logging
from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from django.contrib.auth import get_user_model
from django.http import HttpRequest

logger = logging.getLogger(__name__)
User = get_user_model()


class CustomAccountAdapter(DefaultAccountAdapter):
    """Custom account adapter for username/password authentication."""

    def save_user(self, request: HttpRequest, user, form, commit=True):
        """
        Save a new user instance using information provided in the signup form.

        Ensures that the email address is populated on the User model immediately,
        rather than only in the EmailAddress table. This allows billing, onboarding,
        and other services to access user.email before email verification.

        Also creates the user's team and sets up their trial subscription during signup,
        ensuring consistent behavior with SSO signups.

        Args:
            request: The current HTTP request
            user: The user instance to save
            form: The signup form containing user data
            commit: Whether to save the user to the database

        Returns:
            The saved user instance
        """
        # Let the parent class handle the default save logic
        user = super().save_user(request, user, form, commit=False)

        # Ensure email is set from the form data
        # With ACCOUNT_USER_MODEL_USERNAME_FIELD=None, allauth stores email in EmailAddress
        # but we need it on the User model for Stripe, onboarding emails, etc.
        if hasattr(form, "cleaned_data"):
            email = form.cleaned_data.get("email")
            if email:
                # Validate and sanitize email
                from django.core.exceptions import ValidationError as DjangoValidationError
                from django.core.validators import EmailValidator

                email = email.strip()
                validator = EmailValidator()
                try:
                    validator(email)
                    user.email = email
                    logger.info(f"Set email for new user during signup: {email}")
                except DjangoValidationError:
                    logger.warning(f"Invalid email format during signup: {email}")

        # Generate username from email if not set
        if not user.username and user.email:
            # Create username from email (e.g., "user@example.com" -> "user.example.com")
            username = user.email.replace("@", ".")

            # Ensure username is unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

            user.username = username
            logger.debug(f"Generated username from email: {username}")

        if commit:
            user.save()

            # Create team and set up subscription (same as SSO flow)
            # Only do this if committing, since team creation requires a saved user
            from sbomify.apps.teams.utils import create_user_team_and_subscription

            create_user_team_and_subscription(user)

        return user


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom social account adapter for Keycloak authentication."""

    def pre_social_login(self, request: HttpRequest, sociallogin: SocialLogin) -> None:
        """
        Handle user account connecting or creation.

        Args:
            request: The current HTTP request
            sociallogin: The social login instance
        """
        logger.debug(f"Pre-social login: {sociallogin.account.provider} - {sociallogin.account.uid}")
        logger.debug(f"Extra data: {sociallogin.account.extra_data}")

        # If we found an existing user with the same email
        existing_user = sociallogin.user
        if existing_user.id is None and existing_user.email:
            try:
                existing_user = User.objects.get(email=existing_user.email)
                sociallogin.connect(request, existing_user)
            except User.DoesNotExist:
                pass

    def populate_user(self, request: HttpRequest, sociallogin: SocialLogin, data: dict[str, Any]) -> Any:
        """
        Populate user instance with data from social account.

        Creates a username from the email address by replacing @ with . to ensure uniqueness.
        Also handles Keycloak-specific data like email verification status.

        Args:
            request: The current HTTP request
            sociallogin: The social login instance being processed
            data: The user data from the social provider

        Returns:
            The populated user instance
        """
        user = super().populate_user(request, sociallogin, data)
        logger.debug(f"Populating user with data: {data}")

        # Handle Keycloak-specific data
        if sociallogin.account.provider == "keycloak":
            # Set email verification status
            user.is_active = True  # Keycloak handles activation
            user.email_verified = data.get("email_verified", False)

            # Map Keycloak name fields directly to Django fields (try both possible keys)
            user.first_name = data.get("given_name") or data.get("first_name", "")
            user.last_name = data.get("family_name") or data.get("last_name", "")

            # Use preferred_username if available
            if "preferred_username" in data:
                user.username = data["preferred_username"]
                return user  # Skip email-based username generation

        if user.email:
            # Create username from email (e.g., "kashif@compulife.com.pk" -> "kashif.compulife.com.pk")
            username = user.email.replace("@", ".")

            # Ensure username is unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

            user.username = username
            logger.debug(f"Generated username: {username}")

        return user

    def is_auto_signup_allowed(self, request: HttpRequest, sociallogin: SocialLogin) -> bool:
        """
        Indicates whether the user should be automatically signed up.

        Always returns True to skip the signup form and create the user automatically.

        Args:
            request: The current HTTP request
            sociallogin: The social login instance being processed

        Returns:
            True to enable automatic signup
        """
        return True

    def save_user(self, request, sociallogin, form=None):
        """
        Save a user from social account signup.

        Ensures email is set and creates team with subscription during signup.

        Args:
            request: The current HTTP request
            sociallogin: The social login instance
            form: Optional signup form

        Returns:
            The saved user instance
        """
        user = super().save_user(request, sociallogin, form)

        # Ensure email is set from sociallogin if not already present
        # This is done before team creation to ensure email is available for billing
        if not user.email and sociallogin.account.extra_data:
            email = sociallogin.account.extra_data.get("email")
            if email:
                # Validate and sanitize email
                from django.core.exceptions import ValidationError as DjangoValidationError
                from django.core.validators import EmailValidator

                email = email.strip()
                validator = EmailValidator()
                try:
                    validator(email)
                    user.email = email
                    user.save(update_fields=["email"])
                    logger.info(f"Set email from social account for user {user.username}: {email}")
                except DjangoValidationError:
                    logger.warning(f"Invalid email from social account for user {user.username}: {email}")

        # Create team and set up subscription (using shared function)
        from sbomify.apps.teams.utils import create_user_team_and_subscription

        create_user_team_and_subscription(user)

        return user
