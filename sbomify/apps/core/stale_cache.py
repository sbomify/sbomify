"""Serve the last good copy of a public Trust Center page when Postgres is down.

A Trust Center is read far more than it changes, and nearly all of its traffic
is anonymous. When the database stops answering — a failover, a host stalled by
a snapshot, a connection storm — every page still fails, because the workspace
lookup in ``CustomDomainContextMiddleware`` and the session load both query it
before a view runs. Visitors then get an error page for content that has not
changed in days.

``TrustCenterStaleCacheMiddleware`` keeps a copy of each public page in the
default cache (Redis in production, a separate service from Postgres) and, when
a request fails because the database is unavailable, answers with that copy
instead. Only content any anonymous visitor would see is stored:

* the host is a Trust Center (custom domain or Trust Center subdomain),
* a plain ``GET`` with no query string, no session or auth credentials and no
  HTMX headers,
* a complete ``200`` response that sets no cookie, is not marked private or
  ``no-store``, and is at most ``TRUST_CENTER_STALE_CACHE_MAX_BYTES``.

Anything else — gated documents behind a Trust Center session, signed-in users,
forms, downloads — is never cached, so it can never be replayed to someone else.

It sits at the top of the stack because the database errors it is there for are
raised in middleware as well as views. Django turns each of those into a 500
response before it reaches the next layer out, so the cause is recorded on the
request by a ``got_request_exception`` receiver and read back here.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import time
from typing import Any, Callable

from django.conf import settings
from django.core.cache import cache
from django.core.signals import got_request_exception
from django.db import InterfaceError, OperationalError
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

# Database failures that mean "unavailable", not "this query is wrong".
DATABASE_UNAVAILABLE_ERRORS: tuple[type[BaseException], ...] = (OperationalError, InterfaceError)

_DB_UNAVAILABLE_ATTR = "_sbomify_database_unavailable"
_KEY_PREFIX = "tc-stale:v1:"
_FRESH_KEY_PREFIX = "tc-stale-fresh:v1:"

# Headers recomputed for the replayed response, or that must not be replayed.
_SKIPPED_HEADERS = frozenset({"content-length", "set-cookie", "date", "age", "cache-control", "x-cache"})


def _mark_database_unavailable(sender: Any, request: HttpRequest | None = None, **kwargs: Any) -> None:
    """Remember on the request that it failed because the database is unavailable.

    Sent from inside Django's exception handling, so ``sys.exc_info()`` is the
    exception being converted into a 500.
    """
    if request is None:
        return
    if isinstance(sys.exc_info()[1], DATABASE_UNAVAILABLE_ERRORS):
        setattr(request, _DB_UNAVAILABLE_ATTR, True)


got_request_exception.connect(_mark_database_unavailable, dispatch_uid="sbomify.trust_center_stale_cache")


def _ttl() -> int:
    return int(getattr(settings, "TRUST_CENTER_STALE_CACHE_TTL", 0) or 0)


def _cache_key(prefix: str, host: str, path: str) -> str:
    digest = hashlib.sha256(f"{host.lower()}\n{path}".encode()).hexdigest()
    return f"{prefix}{digest}"


def _request_key(prefix: str, request: HttpRequest) -> str:
    # get_host() was validated by the time a response is stored; when serving,
    # an unvalidated host simply misses.
    return _cache_key(prefix, request.get_host(), request.path)


def _is_anonymous_shareable_request(request: HttpRequest) -> bool:
    """Whether the request could only ever be answered with public content."""
    if request.META.get("QUERY_STRING"):
        return False
    if request.META.get("HTTP_AUTHORIZATION"):
        return False
    if request.META.get("HTTP_HX_REQUEST"):
        return False
    # A session cookie means a signed-in user or a Trust Center session that may
    # unlock gated content; neither response may be shared.
    if settings.SESSION_COOKIE_NAME in request.COOKIES:
        return False
    return True


def _is_storable_response(response: HttpResponse) -> bool:
    if response.status_code != 200:
        return False
    if getattr(response, "streaming", False):
        return False
    if response.cookies:
        return False
    cache_control = response.get("Cache-Control", "").lower()
    if "private" in cache_control or "no-store" in cache_control:
        return False
    max_bytes = int(getattr(settings, "TRUST_CENTER_STALE_CACHE_MAX_BYTES", 1024 * 1024))
    return len(response.content) <= max_bytes


class TrustCenterStaleCacheMiddleware:
    """Replay a stored public Trust Center page when the database is unavailable."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        if _ttl() <= 0 or request.method not in ("GET", "HEAD"):
            return response

        if getattr(request, _DB_UNAVAILABLE_ATTR, False) and response.status_code >= 500:
            return self._serve_stale(request) or response

        if (
            request.method == "GET"
            and getattr(request, "is_custom_domain", False)
            and getattr(request, "custom_domain_team", None) is not None
            and _is_anonymous_shareable_request(request)
            and _is_storable_response(response)
        ):
            self._store(request, response)

        return response

    def _store(self, request: HttpRequest, response: HttpResponse) -> None:
        refresh = int(getattr(settings, "TRUST_CENTER_STALE_CACHE_REFRESH", 60))
        try:
            # One small SET NX per URL per refresh window, rather than rewriting
            # the whole page into Redis on every hit.
            if refresh > 0 and not cache.add(_request_key(_FRESH_KEY_PREFIX, request), 1, refresh):
                return
            headers = [(k, v) for k, v in response.items() if k.lower() not in _SKIPPED_HEADERS]
            entry = {"content": response.content, "headers": headers, "stored_at": time.time()}
            cache.set(_request_key(_KEY_PREFIX, request), entry, _ttl())
        except Exception:  # pragma: no cover - the cache must never cost the page
            logger.warning("Could not store Trust Center stale copy", exc_info=True)

    def _serve_stale(self, request: HttpRequest) -> HttpResponse | None:
        # The stored copy is public, so it is served whoever is asking — only the
        # partial responses HTMX expects would be the wrong shape.
        if request.META.get("HTTP_HX_REQUEST") or request.META.get("QUERY_STRING"):
            return None
        try:
            entry = cache.get(_request_key(_KEY_PREFIX, request))
        except Exception:  # pragma: no cover
            logger.warning("Could not read Trust Center stale copy", exc_info=True)
            return None
        if not entry:
            return None

        age = max(0, int(time.time() - entry["stored_at"]))
        # The body is the exact bytes a view already rendered (through the template
        # engine) for this same host and path, written to the cache only by _store.
        # nosemgrep: opengrep-rules.python.django.security.audit.xss.direct-use-of-httpresponse
        response = HttpResponse(b"" if request.method == "HEAD" else entry["content"], status=200)
        for name, value in entry["headers"]:
            response[name] = value
        response["Content-Length"] = str(len(entry["content"]))
        response["Age"] = str(age)
        # The copy is only for the length of the outage; nothing downstream should keep it.
        response["Cache-Control"] = "no-store"
        response["X-Cache"] = "STALE"
        logger.warning(
            "Database unavailable; served stale Trust Center copy for %s%s (age %ss)",
            request.get_host(),
            request.path,
            age,
        )
        return response
