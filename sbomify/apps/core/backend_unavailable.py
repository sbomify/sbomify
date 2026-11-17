"""Answer a request with 503, not 500, when Postgres or Redis is unreachable.

A request can reach either backend from almost anywhere: the session and the
custom-domain lookup in middleware, every view, the rate limiter, and every
``actor.send()`` that enqueues a task. Before this, each of those failures was
an unhandled exception: a 500 the client had no reason to retry, a traceback in
the log stream, and a Sentry event, once per request in flight, for one outage.

``BackendUnavailableMiddleware`` is the one place that turns all of them into
what they are: the service is briefly unavailable, try again shortly. It writes
the shared outage line from ``sbomify.backend_outage`` once per failure, which
the console throttles and Sentry ignores until the outage outlasts a window.

It sits outermost, outside ``TrustCenterStaleCacheMiddleware``, because Django
converts an exception into a 500 at every layer it crosses, so nothing outside
the layer that raised ever sees the exception itself. The cause is recorded on
the request by a ``got_request_exception`` receiver instead, which fires for
exceptions raised in views and middleware alike, and read back here. Being
outside the stale cache lets a Trust Center page be replayed first; only what it
could not answer becomes a 503.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from django.core.signals import got_request_exception
from django.http import HttpRequest, HttpResponse, JsonResponse

from sbomify.backend_outage import report_backend_outage

#: Matches the backoff ceiling the Redis clients use and the rate limiter's
#: outage hint: a blip is usually over by then.
RETRY_AFTER_SECONDS = 5

_UNAVAILABLE_ATTR = "_sbomify_backend_unavailable"
_MESSAGE = "The service is temporarily unavailable. Please try again in a moment."


def _record_backend_unavailable(sender: Any, request: HttpRequest | None = None, **kwargs: Any) -> None:
    """Note on the request that it failed because a backend is unreachable.

    Sent from inside Django's exception handling, so ``sys.exc_info()`` is the
    exception being turned into a 500.
    """
    exc = sys.exc_info()[1]
    if exc is None:
        return
    backend = report_backend_outage(exc, "web request")
    if backend is not None and request is not None:
        setattr(request, _UNAVAILABLE_ATTR, backend)


got_request_exception.connect(_record_backend_unavailable, dispatch_uid="sbomify.backend_unavailable")


def _wants_json(request: HttpRequest) -> bool:
    if request.path.startswith(("/api/", "/tea/")):
        return True
    return "application/json" in request.META.get("HTTP_ACCEPT", "")


def backend_unavailable_response(request: HttpRequest) -> HttpResponse:
    """The 503 a request gets while a backend it needs is unreachable."""
    response: HttpResponse
    if _wants_json(request):
        response = JsonResponse({"detail": _MESSAGE}, status=503)
    else:
        # A fixed sentence with a text/plain content type; nothing from the request.
        # nosemgrep: opengrep-rules.python.django.security.audit.xss.direct-use-of-httpresponse
        response = HttpResponse(_MESSAGE, status=503, content_type="text/plain; charset=utf-8")
    response["Retry-After"] = str(RETRY_AFTER_SECONDS)
    response["Cache-Control"] = "no-store"
    # Django writes every 5xx it returns to ``django.request`` at error level,
    # once per request. The shared outage line already reported this, throttled,
    # and the attribute is how Django itself marks a response already logged.
    response._has_been_logged = True  # type: ignore[attr-defined]
    return response


class BackendUnavailableMiddleware:
    """Turn a 500 caused by an unreachable Postgres or Redis into a 503."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if response.status_code == 500 and getattr(request, _UNAVAILABLE_ATTR, None):
            return backend_unavailable_response(request)
        return response
