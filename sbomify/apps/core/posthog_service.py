from __future__ import annotations

import hashlib
import threading
from typing import Any

from django.conf import settings

from sbomify.logging import getLogger

logger = getLogger(__name__)

_lock = threading.Lock()
_client: Any = None
_initialized = False


def _get_client() -> Any:
    """Lazy-initialize the PostHog client. Returns None when disabled."""
    global _client, _initialized
    if _initialized:
        return _client

    with _lock:
        if _initialized:
            return _client

        api_key: str = getattr(settings, "POSTHOG_API_KEY", "")
        if not api_key:
            _initialized = True
            logger.debug("PostHog server-side tracking disabled (no API key)")
            return None

        try:
            from posthog import Posthog

            default_host = "https://us.i.posthog.com"
            host: str = getattr(settings, "POSTHOG_HOST", default_host).strip().rstrip("/")
            if host and not host.startswith(("https://", "http://")):
                host = f"https://{host}"

            # Enforce HTTPS in production
            if host.startswith("http://") and not getattr(settings, "DEBUG", False):
                logger.warning("PostHog host uses insecure HTTP, forcing HTTPS")
                host = host.replace("http://", "https://", 1)

            effective_host = host or default_host
            _client = Posthog(api_key, host=effective_host)  # type: ignore[no-untyped-call]
            _client.debug = getattr(settings, "DEBUG", False)
            _initialized = True
            logger.info("PostHog server-side tracking initialized (host=%s)", effective_host)
        except Exception:
            logger.exception("Failed to initialize PostHog client — analytics disabled for this process")
            _client = None
            _initialized = True

    return _client


def is_enabled() -> bool:
    """Return True if PostHog is configured (API key is set)."""
    return bool(getattr(settings, "POSTHOG_API_KEY", ""))


def hash_email(email: str) -> str:
    """One-way hash an email address for PII minimization.

    Returns a 16-char hex digest. The original email cannot be recovered,
    but the same email always produces the same hash for cohort analysis.
    """
    if not email:
        return ""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]


_MAX_SESSION_ID_LENGTH = 200


def get_distinct_id(request: Any) -> str:
    """Derive a stable distinct_id from the request.

    Returns the user PK for authenticated users, the PostHog session ID
    cookie for anonymous visitors, or an existing Django session key.
    Never creates a new session purely for analytics.
    """
    if hasattr(request, "user") and request.user.is_authenticated:
        return str(request.user.pk)
    session_id = get_session_id(request)
    if session_id:
        return session_id
    if hasattr(request, "session"):
        key: str = request.session.session_key or ""
        if key:
            return key
    return "anonymous"


def get_session_id(request: Any) -> str:
    """Extract the PostHog session ID from the request cookie set by the frontend JS SDK."""
    if not hasattr(request, "COOKIES"):
        return ""
    from urllib.parse import unquote

    value = unquote(request.COOKIES.get("ph_session_id", ""))
    if len(value) > _MAX_SESSION_ID_LENGTH:
        return ""
    return value


def has_opted_out(request: Any) -> bool:
    """Check if the user has opted out of analytics via the PostHog cookie.

    With opt_out_capturing_by_default enabled on the frontend, the absence
    of a consent cookie means the user hasn't opted in yet — treat as opted out.
    """
    if not hasattr(request, "COOKIES"):
        return False
    # PostHog JS SDK stores opt-out state in a cookie prefixed with the project key
    # The standard cookie pattern is: ph_<project_key>_opt_in_out
    # When opted out, the value is "0". When opted in, "1".
    for name, value in request.COOKIES.items():
        if name.startswith("ph_") and name.endswith("_opt_in_out"):
            return bool(value == "0")
    # No consent cookie found — with opt-out-by-default, treat as opted out
    return True


def capture(
    distinct_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
    *,
    groups: dict[str, str] | None = None,
    request: Any = None,
) -> None:
    """Capture a server-side event. No-op when PostHog is disabled or user opted out.

    When ``request`` is provided, consent is checked via the PostHog opt-out
    cookie and the event is skipped if the user declined analytics.

    When ``request`` is ``None`` (signal-based / background task events),
    consent cannot be checked. These events use ``distinct_id="system"``
    and are aggregate workspace-level telemetry — they do not create person
    profiles (PostHog is configured with ``person_profiles: 'identified_only'``).
    """
    client = _get_client()
    if client is None:
        return

    # Respect user's consent choice from the frontend
    if request and has_opted_out(request):
        return

    try:
        merged: dict[str, Any] = dict(properties or {})
        if request:
            session_id = get_session_id(request)
            if session_id:
                merged["$session_id"] = session_id

        kwargs: dict[str, Any] = {}
        if groups:
            kwargs["groups"] = groups
        client.capture(distinct_id, event, properties=merged, **kwargs)
    except Exception:
        logger.exception("Failed to capture PostHog event %s", event)


def identify(
    distinct_id: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Set person properties. No-op when PostHog is disabled."""
    client = _get_client()
    if client is None:
        return

    try:
        client.identify(distinct_id, properties=properties or {})
    except Exception:
        logger.exception("Failed to identify PostHog user %s", distinct_id)


def group_identify(
    group_type: str,
    group_key: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Set group properties. No-op when PostHog is disabled."""
    client = _get_client()
    if client is None:
        return

    try:
        client.group_identify(group_type, group_key, properties=properties or {})
    except Exception:
        logger.exception("Failed to identify PostHog group %s:%s", group_type, group_key)


def shutdown() -> None:
    """Flush and close the client. Call on app shutdown."""
    global _client, _initialized
    if _client is not None:
        try:
            _client.shutdown()
        except Exception:
            logger.exception("Failed to shutdown PostHog client")
    _client = None
    _initialized = False
