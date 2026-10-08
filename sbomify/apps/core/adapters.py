from __future__ import annotations

import hashlib
import logging
import time
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter, get_adapter
from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpRequest

logger = logging.getLogger(__name__)
User = get_user_model()


def _provider_confirmed_email(sociallogin: SocialLogin) -> bool:
    """Whether the identity provider confirmed the address this login carries.

    allauth fills ``email_addresses`` from the provider's claims, and its own
    email login trusts nothing else. The claim is not at the top of
    ``extra_data``: since allauth 65.11 OpenID Connect keeps it under
    ``userinfo`` and ``id_token``.
    """
    email = (sociallogin.user.email or "").lower()
    return bool(email) and any(a.verified and a.email.lower() == email for a in sociallogin.email_addresses)


def _account_owns_its_email(user: Any) -> bool:
    """Whether an account's address belongs to whoever signs in to it.

    The identity provider confirmed the address, or nobody can have signed in
    to the account yet: no login and no password, as with one the
    access-request form made. allauth's own confirmation does not count: its
    link binds the address to whichever account asked for it, not to the
    person who clicked.
    """
    return bool(user.email_verified or (user.last_login is None and not user.has_usable_password()))


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


# How long a discovery document is served before we go and ask again. The
# document is deployment configuration rather than per-login state, so this
# only governs how quickly a Keycloak reconfiguration is picked up.
OIDC_CONFIG_REFRESH_AFTER = 60 * 60

# How long the cached copy survives in total. It outlives the refresh interval
# by a long way on purpose: its whole job is to still be there on the day
# Keycloak is the thing that is down.
OIDC_CONFIG_CACHE_TTL = 30 * 24 * 60 * 60

# How long to stop asking after a refresh fails. Without this, a stale entry
# plus an unreachable provider means every single login re-attempts the same
# request and waits out its timeout before falling back to the copy it already
# held -- the cache removed the 500 but not the delay, and turned one slow
# login into a request per sign-in against a provider that is already
# struggling. Short, because the point is to ride out a blip rather than to
# stop noticing a reconfiguration: the refresh resumes a minute later.
OIDC_CONFIG_RETRY_AFTER_FAILURE = 60

# Without these allauth cannot build an authorize or token URL, so a 200
# carrying anything less is not a document worth remembering.
_REQUIRED_OIDC_ENDPOINTS = ("authorization_endpoint", "token_endpoint")


def _oidc_config_cache_key(server_url: str) -> str:
    """A key that is per-provider but safe for every cache backend.

    The server URL is what distinguishes one provider's document from
    another's, and it is also full of characters a memcached key may not
    contain, so it is hashed rather than embedded.
    """
    digest = hashlib.sha256(server_url.encode("utf-8")).hexdigest()
    return f"oidc-discovery:{digest}"


def _fetch_openid_config(server_url: str) -> dict[str, Any]:
    """Read the discovery document the way allauth does.

    Going through allauth's own session keeps whatever it configures there --
    proxies, headers, timeouts -- applied to this request too.
    """
    with get_adapter().get_requests_session() as session:
        response = session.get(server_url)
        response.raise_for_status()
        config = response.json()

    if not isinstance(config, dict) or any(not config.get(name) for name in _REQUIRED_OIDC_ENDPOINTS):
        raise ValueError(f"{server_url} did not return a usable OpenID Connect discovery document")
    return config


def cached_openid_config(adapter: Any) -> dict[str, Any]:
    """``OpenIDConnectOAuth2Adapter.openid_config``, backed by the shared cache.

    Upstream memoises the document on the adapter instance, and allauth builds
    a fresh adapter for every request, so each individual sign-in blocked on a
    live round trip to Keycloak. Anything that interrupted that round trip --
    a 521 from the CDN in front of it, a read timeout -- surfaced as a 500 on
    ``/accounts/oidc/<provider>/login/``, and nobody could log in until the
    blip passed.

    The document is static configuration, so almost all of those round trips
    bought nothing. Caching it means a provider blip is invisible to the
    people signing in: a cached copy that is merely stale is still a correct
    set of endpoints, and serving it is strictly better than refusing a login.
    """
    # Several properties read this within one request; keep upstream's
    # per-instance memo so they share a single lookup.
    if hasattr(adapter, "_openid_config"):
        return adapter._openid_config  # type: ignore[no-any-return]

    server_url = adapter.get_provider().server_url
    key = _oidc_config_cache_key(server_url)
    entry = cache.get(key)
    now = time.time()

    config: dict[str, Any]
    cached = entry if isinstance(entry, dict) else None
    # Two reasons to serve what we hold without asking again: it is still
    # fresh, or a refresh just failed and we agreed to wait before retrying.
    # The second is what keeps a provider outage from costing every login a
    # timeout -- see OIDC_CONFIG_RETRY_AFTER_FAILURE.
    serve_cached = cached is not None and (
        now - cached.get("fetched_at", 0) < OIDC_CONFIG_REFRESH_AFTER or now < cached.get("retry_after", 0)
    )

    if cached is not None and serve_cached:
        config = cached["config"]
    else:
        try:
            config = _fetch_openid_config(server_url)
        except Exception as exc:
            # Only a copy we already hold can rescue the login; with nothing
            # cached there is no endpoint to send the user to.
            if cached is None:
                raise
            logger.warning(
                "OpenID Connect discovery at %s failed (%s); serving the cached copy instead",
                server_url,
                exc,
            )
            # Hold off the next attempt, without extending how long this copy
            # survives in total: the remaining TTL is measured from the last
            # successful fetch, so a long outage still lets the entry expire
            # on its original schedule rather than pinning a stale document
            # in the cache for as long as the provider stays down.
            remaining = OIDC_CONFIG_CACHE_TTL - (now - cached.get("fetched_at", 0))
            if remaining > 0:
                cache.set(
                    key,
                    {**cached, "retry_after": now + OIDC_CONFIG_RETRY_AFTER_FAILURE},
                    remaining,
                )
            config = cached["config"]
        else:
            cache.set(key, {"config": config, "fetched_at": now}, OIDC_CONFIG_CACHE_TTL)

    adapter._openid_config = config
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
            if User.objects.filter(email__iexact=existing_user.email, deleted_at__isnull=False).exists():
                from allauth.exceptions import ImmediateHttpResponse
                from django.shortcuts import render

                raise ImmediateHttpResponse(render(request, "account/account_deactivated.html.j2", status=403))

            holders = User.objects.filter(email__iexact=existing_user.email, is_active=True, deleted_at__isnull=True)
            try:
                existing_user = holders.get()
                # Only an address the provider confirmed may claim an existing account, and only an
                # account that owns that address too.
                if _provider_confirmed_email(sociallogin) and _account_owns_its_email(existing_user):
                    sociallogin.connect(request, existing_user)
            except User.DoesNotExist:
                pass
            except User.MultipleObjectsReturned:
                ids = sorted(holders.values_list("id", flat=True))
                logger.warning("Social sign-in refused: accounts %s share one email address", ids)
                from allauth.core.exceptions import ImmediateHttpResponse
                from django.shortcuts import render

                raise ImmediateHttpResponse(
                    render(
                        request,
                        "socialaccount/authentication_error.html.j2",
                        {"error_message": "More than one account uses this email address. Contact support to sign in."},
                        status=409,
                    )
                )

        # Sync email_verified status from social provider on every login
        extra_data = sociallogin.account.extra_data or {}
        provider = sociallogin.account.provider

        # Extract email_verified from provider-specific field
        if provider == "keycloak":
            email_verified = _provider_confirmed_email(sociallogin)
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
            user.email_verified = _provider_confirmed_email(sociallogin)

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
