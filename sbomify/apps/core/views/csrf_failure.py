"""Friendly CSRF failure handling.

The stock Django CSRF failure page is a dead end: after the login redirect
chain (Keycloak signup or a long-idle tab) the token in an already-rendered
form can go stale, and the user's first submit lands on a bare 403. A fresh
render of the same form always carries a valid token, so the recovery is
simply "go back and try again" — this view does that for the user.
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)

RETRY_MESSAGE = "Your session was refreshed. Please submit the form again."


def _safe_referer(request: HttpRequest) -> str | None:
    """The ``Referer``, when it is somewhere we can send the browser back to.

    Two checks, and the second one is the reason this is a function.
    ``url_has_allowed_host_and_scheme`` answers "does this point at a host we
    own", and it answers yes for *any* relative value — including one that is
    not a URL at all. That is not a corner case here: Django's CSRF middleware
    calls this view precisely because it rejected the request, and one of the
    reasons it rejects a request is a malformed ``Referer``, so a header that
    is not a URL is the expected input rather than a rare one. A bare word
    passed the host check and then reached ``redirect()``, which reads a string
    with no path separator as a *view name*, reverses it, and raises
    ``NoReverseMatch`` — a 500 raised by the view whose whole job is to turn a
    403 into something friendly.

    So the value must also be navigable: an absolute URL, or a path anchored at
    the root. Control characters are refused outright — they cannot appear in a
    ``Location`` header, and a ``Referer`` carrying one is not a browser.
    """
    referer = request.headers.get("Referer", "")
    if not referer:
        return None
    if any(char < " " or char == "\x7f" for char in referer):
        return None
    if not referer.startswith("/") and "://" not in referer:
        return None
    if not url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return None
    return referer


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    logger.warning("CSRF failure on %s (%s)", request.path, reason)

    safe_referer = _safe_referer(request)

    if request.headers.get("HX-Request"):
        # A toast alone would leave the stale token in the DOM and the retry
        # would fail the same way; HX-Redirect makes HTMX re-render the page,
        # which carries a fresh token. The message survives the navigation.
        messages.error(request, RETRY_MESSAGE)
        response = HttpResponse(status=204)
        response["HX-Redirect"] = safe_referer or request.path
        return response

    if safe_referer:
        messages.error(request, RETRY_MESSAGE)
        # Not ``redirect()``: that resolves a string without a path separator
        # as a view name. Everything reaching here is already a checked URL or
        # root-relative path, and there is no view name to look up.
        return HttpResponseRedirect(safe_referer)

    from sbomify.apps.core.errors import error_response

    return error_response(request, HttpResponse(RETRY_MESSAGE, status=403))
