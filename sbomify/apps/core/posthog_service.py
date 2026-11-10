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


#: The tenant word in event names. ``team:*`` is emitted beside ``workspace:*``
#: until the PostHog dashboards are cut over, then the pair below collapses to
#: one and the dual-emit in capture_for_request goes with it.
EVENT_PREFIX = "workspace"
RETIRED_EVENT_PREFIX = "team"


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
_MAX_PERSISTED_COOKIE_LENGTH = 4096


def _persisted_state(request: Any) -> dict[str, Any]:
    """Read the state posthog-js keeps in its ``ph_<project key>_posthog`` cookie.

    The cookie is written on ``.sbomify.com``, so a visitor who accepted
    analytics on the marketing site carries their anonymous ``distinct_id``
    and session into the app before the app has loaded any JavaScript.
    """
    api_key: str = getattr(settings, "POSTHOG_API_KEY", "")
    if not api_key or not hasattr(request, "COOKIES"):
        return {}
    import json
    from urllib.parse import unquote

    raw = request.COOKIES.get(f"ph_{api_key}_posthog", "")
    if not raw or len(raw) > _MAX_PERSISTED_COOKIE_LENGTH:
        return {}
    try:
        state = json.loads(unquote(raw))
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def get_distinct_id(request: Any) -> str:
    """Derive a stable distinct_id from the request.

    Returns the user PK for authenticated users. For anonymous visitors it
    returns the browser's own PostHog ``distinct_id``, so a server-side event
    lands on the same person as the pages they viewed, then falls back to
    the PostHog session ID cookie or an existing Django session key.
    Never creates a new session purely for analytics.
    """
    if hasattr(request, "user") and request.user.is_authenticated:
        return str(request.user.pk)
    browser_id = _persisted_state(request).get("distinct_id")
    if isinstance(browser_id, str) and 0 < len(browser_id) <= _MAX_SESSION_ID_LENGTH:
        return browser_id
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
    if not value:
        # posthog-js stores the session as [last activity, session id, start].
        sesid = _persisted_state(request).get("$sesid")
        if isinstance(sesid, list) and len(sesid) > 1 and isinstance(sesid[1], str):
            value = sesid[1]
    if len(value) > _MAX_SESSION_ID_LENGTH:
        return ""
    return value


def consent_cookie_name() -> str:
    """Name of the cookie posthog-js keeps the visitor's consent in.

    The app initialises posthog-js with ``opt_out_capturing_persistence_type:
    'cookie'``, so the decision is written as ``__ph_opt_in_out_<project key>``
    on ``.sbomify.com`` with the value ``1`` or ``0``. The marketing site
    writes the same cookie, which makes one decision hold on both, and lets
    the server read it here.
    """
    return f"__ph_opt_in_out_{getattr(settings, 'POSTHOG_API_KEY', '')}"


def consent_status(request: Any) -> bool | None:
    """Return True if the visitor opted in, False if they declined, None if they have not chosen."""
    if not hasattr(request, "COOKIES"):
        return None
    value = request.COOKIES.get(consent_cookie_name())
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    return None


def has_opted_out(request: Any) -> bool:
    """Check whether server-side capture must be skipped for this request.

    With opt_out_capturing_by_default enabled on the frontend, a visitor who
    has not chosen yet is treated as opted out.
    """
    return consent_status(request) is not True


_CLIENT_EVENTS_SESSION_KEY = "posthog_client_events"
_MAX_CLIENT_EVENTS = 10


def queue_client_event(request: Any, event: str, properties: dict[str, Any] | None = None) -> None:
    """Hold an event in the session for the browser to send on its next full page.

    For events that must land on the person, not the workspace: the browser
    sends them after ``posthog.identify``, which merges the visitor's
    anonymous history (the marketing pages they read first) into the user.
    A visitor who has not chosen yet keeps the event until they do; one
    who declined never has it queued.
    """
    if not is_enabled() or not hasattr(request, "session") or consent_status(request) is False:
        return
    queued = list(request.session.get(_CLIENT_EVENTS_SESSION_KEY, []))[-(_MAX_CLIENT_EVENTS - 1) :]
    queued.append({"event": event, "properties": properties or {}})
    request.session[_CLIENT_EVENTS_SESSION_KEY] = queued


def take_client_events(request: Any) -> list[dict[str, Any]]:
    """Hand queued events to the page once the visitor opted in, and drop them if they declined."""
    if not hasattr(request, "session"):
        return []
    status = consent_status(request)
    if status is None:
        return []
    queued: list[dict[str, Any]] = request.session.pop(_CLIENT_EVENTS_SESSION_KEY, [])
    return queued if status else []


def capture_for_request(
    request: Any,
    event: str,
    properties: dict[str, Any] | None = None,
    *,
    workspace_key: str | None = None,
) -> None:
    """Capture an event from a view, applying the standard guards.

    Distinct_id convention (matches PR #822 and the Tier 1 signal pattern):
    workspace key is preferred over user PK so server-side events attribute
    to the workspace, not the user. Cross-correlation of users → workspaces
    is exactly what we want to avoid in PostHog.

    Three cases for ``workspace_key``:

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
      ``groups={"workspace": workspace_key}``.

    Short-circuits when PostHog is disabled or the request resolves to
    ``anonymous`` so the cookie/session work in ``get_distinct_id`` is
    skipped on disabled deployments. Forwards ``request`` so the
    cookie-based consent gate in ``capture`` still applies.
    """
    if not is_enabled():
        return

    if workspace_key is None:
        # Genuinely user-scoped event.
        distinct_id = get_distinct_id(request)
        groups: dict[str, str] | None = None
    elif workspace_key == "":
        # Workspace-intent that failed to resolve a key. Better to drop
        # the event than to mis-attribute it to a user PK.
        logger.debug("Skipping workspace-scoped event %s — empty team_key", event)
        return
    else:
        distinct_id = workspace_key
        groups = {"workspace": workspace_key}

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

        # Dual-emit while the dashboards migrate. Here rather than in
        # capture_for_request, because not every emission goes through a view:
        # team:role_changed fires from a signal inside transaction.on_commit
        # with no request in hand, and a twin emitted one layer up would have
        # missed it forever. The twin skips the registry check on purpose; it
        # is the same payload under the migrating name, and warning on every
        # fire for the whole window is noise, not drift.
        if event.startswith(f"{RETIRED_EVENT_PREFIX}:"):
            renamed = f"{EVENT_PREFIX}{event.removeprefix(RETIRED_EVENT_PREFIX)}"
            client.capture(distinct_id, renamed, properties=merged, **kwargs)
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
