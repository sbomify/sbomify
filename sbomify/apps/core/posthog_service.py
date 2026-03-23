from __future__ import annotations

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

        _initialized = True
        api_key: str = getattr(settings, "POSTHOG_API_KEY", "")
        if not api_key:
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

            _client = Posthog(api_key, host=host or default_host)  # type: ignore[no-untyped-call]
            _client.debug = getattr(settings, "DEBUG", False)
            logger.info("PostHog server-side tracking initialized (host=%s)", host)
        except Exception:
            logger.exception("Failed to initialize PostHog client")
            _client = None

    return _client


def capture(
    distinct_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
    *,
    groups: dict[str, str] | None = None,
) -> None:
    """Capture a server-side event. No-op when PostHog is disabled."""
    client = _get_client()
    if client is None:
        return

    try:
        kwargs: dict[str, Any] = {}
        if groups:
            kwargs["groups"] = groups
        client.capture(distinct_id, event, properties=properties or {}, **kwargs)
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
