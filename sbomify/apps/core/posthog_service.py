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
    """HMAC-hash an email address for PII minimization.

    Uses Django's SECRET_KEY as the HMAC key so the hash is not reversible
    via rainbow tables. Returns a 32-char hex digest — deterministic per
    installation for cohort analysis, but not portable across deployments.
    """
    if not email:
        return ""
    import hmac

    key = getattr(settings, "SECRET_KEY", "").encode()
    return hmac.new(key, email.lower().strip().encode(), hashlib.sha256).hexdigest()[:32]


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
        key: str = getattr(request.session, "session_key", None) or ""
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
        return True
    # PostHog JS SDK stores opt-out state in a cookie named ph_<project_key>_opt_in_out
    # When opted out, the value is "0". When opted in, "1".
    # Check the exact cookie for the current project key first to avoid
    # reading a stale cookie from a rotated key or a different project.
    api_key: str = getattr(settings, "POSTHOG_API_KEY", "")
    if api_key:
        exact_cookie = f"ph_{api_key}_opt_in_out"
        if exact_cookie in request.COOKIES:
            return bool(request.COOKIES[exact_cookie] == "0")
    # Fallback: scan for any matching cookie (covers edge cases)
    for name, value in request.COOKIES.items():
        if name.startswith("ph_") and name.endswith("_opt_in_out"):
            return bool(value == "0")
    # No consent cookie found — with opt-out-by-default, treat as opted out
    return True


def capture_for_request(
    request: Any,
    event: str,
    properties: dict[str, Any] | None = None,
    *,
    team_key: str | None = None,
) -> None:
    """Capture an event from a view, applying the standard guards.

    Distinct_id convention (matches PR #822 and the Tier 1 signal pattern):
    workspace key is preferred over user PK so server-side events attribute
    to the workspace, not the user. Cross-correlation of users → workspaces
    is exactly what we want to avoid in PostHog.

    Three cases for ``team_key``:

    * ``None`` (kwarg omitted) — caller declared this is a genuinely
      user-scoped event (e.g. ``user:account_deleted``, where there is
      no workspace context). Fall back to the request-derived
      ``get_distinct_id`` (user PK for authenticated, session ID for
      anonymous). The event will not carry a workspace group.
    * ``""`` (empty string) — caller INTENDED workspace context but
      couldn't resolve it (e.g. session missing the ``current_team``
      key, or the key resolution path returned empty). Skipping here
      keeps the Tier 2 attribution guarantee intact: a workspace-scoped
      event must NEVER silently downgrade to user-scoped, otherwise we
      leak user↔workspace correlation into PostHog and break the
      workspace-level rollups. The call site should fix its key
      derivation rather than relying on a fallback.
    * truthy string — use as ``distinct_id`` and set
      ``groups={"workspace": team_key}``.

    Short-circuits when PostHog is disabled or the request resolves to
    ``anonymous`` so the cookie/session work in ``get_distinct_id`` is
    skipped on disabled deployments. Forwards ``request`` so the
    cookie-based consent gate in ``capture`` still applies.
    """
    if not is_enabled():
        return

    if team_key is None:
        # Genuinely user-scoped event.
        distinct_id = get_distinct_id(request)
        groups: dict[str, str] | None = None
    elif team_key == "":
        # Workspace-intent that failed to resolve a key. Better to drop
        # the event than to mis-attribute it to a user PK.
        logger.debug("Skipping workspace-scoped event %s — empty team_key", event)
        return
    else:
        distinct_id = team_key
        groups = {"workspace": team_key}

    if not distinct_id or distinct_id == "anonymous":
        return
    capture(distinct_id, event, properties or {}, groups=groups, request=request)


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
    consent cannot be checked. These events typically use the workspace key
    as ``distinct_id`` for workspace-level attribution, falling back to
    ``"system"`` when no workspace key is available. They do not create
    person profiles (PostHog is configured with ``person_profiles: 'identified_only'``).

    Runtime drift detection: cross-checks the event name + payload against
    ``sbomify.apps.core.analytics.events.validate_payload`` and logs (does
    not raise) any warnings. The event ships regardless so production
    analytics stays resilient — but a typo'd name or an unregistered
    property surfaces in logs immediately rather than waiting for the
    next test run.
    """
    client = _get_client()
    if client is None:
        return

    # Respect user's consent choice from the frontend
    if request and has_opted_out(request):
        return

    # Cross-check against the event registry. Log warnings but never block —
    # the registry is observation, not enforcement (see analytics/events.py
    # module docstring for the rationale).
    try:
        from sbomify.apps.core.analytics.events import validate_payload

        for warning in validate_payload(event, properties):
            logger.warning("PostHog event registry drift: %s", warning)
    except Exception:
        logger.exception("Failed to run registry validation for event %s", event)

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
