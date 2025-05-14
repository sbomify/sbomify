import logging
from typing import Any

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from django.contrib.auth import get_user_model
from django.http import HttpRequest

logger = logging.getLogger(__name__)
User = get_user_model()


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

            # Map Keycloak name fields directly to Django fields
            user.first_name = data.get("given_name", "")
            user.last_name = data.get("family_name", "")

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
