from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter, get_adapter
from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpRequest

logger = logging.getLogger(__name__)
User = get_user_model()


class SpaceEncodedOAuth2Client(OAuth2Client):  # type: ignore[misc]
    """An authorize URL whose spaces are ``%20``, not ``+``.

    ``urlencode`` writes a space as ``+``, which reads back as a space only
    under form-urlencoding rules. A generic URI reader follows RFC 3986,
    where ``+`` is a literal character, so any hop that decodes this query
    and re-encodes it conservatively escapes the scope separators to
    ``%2B``. Keycloak then reads all three scopes as one unknown scope
    named ``openid+email+profile`` and refuses the login.

    That is the shape of the failures: the value is correct when it leaves
    here, most logins work, and a minority arrive escaped. ``%20`` means a
    space to both readers and comes back unchanged from a decode/encode
    round trip, so the ambiguity the mangling relies on is gone.

    Nothing else about the URL moves. A literal ``+``, which a PKCE
    challenge can contain, is ``%2B`` either way.
    """

    def get_redirect_url(self, authorization_url: str, scope: Any, extra_params: dict[str, Any]) -> str:
        url: str = super().get_redirect_url(authorization_url, scope, extra_params)
        base, separator, query = url.partition("?")
        if not separator:
            return url
        # Re-encode what the base class built rather than rebuilding the
        # parameters here, so a parameter allauth adds later still travels.
        pairs = parse_qsl(query, keep_blank_values=True)
        return f"{base}?{urlencode(pairs, quote_via=quote)}"


# The OpenID Connect discovery document, keyed by the URL it was fetched from so
# a changed ``server_url`` cannot read back the previous provider's endpoints.
_OIDC_DISCOVERY_PREFIX = "oidc:discovery:"

# Enough of the document that the login and callback views can complete. Anything
# short of this is a body we parsed but cannot act on — a proxy's JSON error page,
# a realm that is still starting — and caching it would turn one bad minute into a
# cached hour of the same failure.
_OIDC_REQUIRED_KEYS = ("authorization_endpoint", "token_endpoint")


def _oidc_discovery_cache_keys(server_url: str) -> tuple[str, str]:
    """The fresh key and the stale-fallback key for one discovery URL."""
    digest = hashlib.sha256(server_url.encode("utf-8")).hexdigest()[:32]
    return f"{_OIDC_DISCOVERY_PREFIX}fresh:{digest}", f"{_OIDC_DISCOVERY_PREFIX}stale:{digest}"


def _oidc_cache_get(key: str) -> dict[str, Any] | None:
    """``cache.get`` that cannot be the reason a login fails.

    The ``default`` alias already swallows Redis failures (``IGNORE_EXCEPTIONS``),
    but this path exists to keep logins up when something is down, so it does not
    rely on that being configured — a cache that raises is a cache miss here.
    """
    try:
        value = cache.get(key)
    except Exception:  # pragma: no cover - defensive, alias swallows these
        logger.warning("OIDC discovery cache read failed for %s", key, exc_info=True)
        return None
    return value if isinstance(value, dict) else None


def _oidc_cache_set(key: str, config: dict[str, Any], timeout: int) -> None:
    """``cache.set`` that cannot be the reason a login fails."""
    try:
        cache.set(key, config, timeout)
    except Exception:  # pragma: no cover - defensive, alias swallows these
        logger.warning("OIDC discovery cache write failed for %s", key, exc_info=True)


def load_openid_config(server_url: str) -> dict[str, Any]:
    """The provider's discovery document, cached, with the last good copy as a floor.

    allauth memoises this document on the adapter instance, and the adapter is
    built per request, so every single login and callback made a blocking HTTPS
    GET to the identity provider's ``.well-known`` endpoint before it could
    redirect. That put the provider's worst latency directly in front of the
    login page with nothing between them: when Keycloak answered slowly the
    five-second read timeout expired and the user got a 500, and when it
    answered 521 the ``raise_for_status`` did the same. Both were live in
    production, on the login path, which is the one page a user cannot route
    around.

    So the document is cached, which removes the fetch from almost every login,
    and a longer-lived copy is kept as a fallback for when the fetch fails
    anyway. A discovery document is derived from the realm URL and changes
    essentially never, so serving the last good copy through a provider outage
    is both safe and the difference between a slow login and no login at all.
    If the fetch fails and there is no copy to fall back to, the error is raised
    as before — there is nothing better to do with it.
    """
    fresh_key, stale_key = _oidc_discovery_cache_keys(server_url)

    config = _oidc_cache_get(fresh_key)
    if config is not None:
        return config

    try:
        with get_adapter().get_requests_session() as sess:
            resp = sess.get(server_url)
            resp.raise_for_status()
            config = resp.json()
        if not isinstance(config, dict) or not all(config.get(key) for key in _OIDC_REQUIRED_KEYS):
            raise ValueError(f"OIDC discovery document from {server_url} is missing {_OIDC_REQUIRED_KEYS}")
    except Exception:
        stale = _oidc_cache_get(stale_key)
        if stale is None:
            raise
        logger.warning(
            "OIDC discovery fetch from %s failed; serving the last known good document",
            server_url,
            exc_info=True,
        )
        return stale

    _oidc_cache_set(fresh_key, config, settings.OIDC_DISCOVERY_CACHE_SECONDS)
    _oidc_cache_set(stale_key, config, settings.OIDC_DISCOVERY_STALE_SECONDS)
    return config


def cached_openid_config(self: Any) -> dict[str, Any]:
    """Replacement for ``OpenIDConnectOAuth2Adapter.openid_config``.

    Keeps allauth's per-instance memoisation — several properties read this
    document within one request — and puts the shared cache behind it.
    """
    config: dict[str, Any] | None = getattr(self, "_openid_config", None)
    if config is None:
        config = load_openid_config(self.get_provider().server_url)
        self._openid_config = config
    return config


class CustomAccountAdapter(DefaultAccountAdapter):  # type: ignore[misc]
    """Custom account adapter for username/password authentication."""

    def save_user(self, request: HttpRequest, user: Any, form: Any, commit: Any = True) -> Any:
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


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):  # type: ignore[misc]
    """Custom social account adapter for Keycloak authentication."""

    def on_authentication_error(
        self,
        request: Any,
        provider: Any,
        error: Any = None,
        exception: Any = None,
        extra_context: Any = None,
    ) -> Any:
        """Redirect already-authenticated users home instead of showing an error page."""
        if request.user.is_authenticated:
            from allauth.exceptions import ImmediateHttpResponse
            from django.shortcuts import redirect

            raise ImmediateHttpResponse(redirect("/"))

    def pre_social_login(self, request: HttpRequest, sociallogin: SocialLogin) -> None:
        """
        Handle user account connecting or creation.

        Also syncs email_verified status from social providers on every login for existing users.

        Args:
            request: The current HTTP request
            sociallogin: The social login instance
        """
        logger.debug(f"Pre-social login: {sociallogin.account.provider} - {sociallogin.account.uid}")
        logger.debug(f"Extra data: {sociallogin.account.extra_data}")

        # If we found an existing user with the same email
        existing_user = sociallogin.user
        if existing_user.id is None and existing_user.email:
            # Block soft-deleted users from re-authenticating via SSO
            if User.objects.filter(email=existing_user.email, deleted_at__isnull=False).exists():
                from allauth.exceptions import ImmediateHttpResponse
                from django.shortcuts import render

                return ImmediateHttpResponse(render(request, "account/account_deactivated.html.j2", status=403))  # type: ignore[no-any-return]

            try:
                existing_user = User.objects.get(
                    email=existing_user.email,
                    is_active=True,
                    deleted_at__isnull=True,
                )
                sociallogin.connect(request, existing_user)
            except User.DoesNotExist:
                pass

        # Sync email_verified status from social provider on every login
        extra_data = sociallogin.account.extra_data or {}
        provider = sociallogin.account.provider

        # Extract email_verified from provider-specific field
        if provider == "keycloak":
            email_verified = extra_data.get("email_verified", False)
        elif provider == "github":
            email_verified = extra_data.get("email_verified", False)
        elif provider == "google":
            email_verified = extra_data.get("verified_email", False)
        else:
            email_verified = None  # Unknown provider, don't sync

        # Update existing user's email_verified status if changed
        user = sociallogin.user
        if email_verified is not None and user.pk is not None and user.email_verified != email_verified:
            user.email_verified = email_verified
            user.save(update_fields=["email_verified"])
            logger.info(f"Synced email_verified={email_verified} for user {user.username} from {provider}")

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

    def save_user(self, request: Any, sociallogin: Any, form: Any = None) -> Any:
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
