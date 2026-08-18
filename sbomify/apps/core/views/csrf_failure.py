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
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)

RETRY_MESSAGE = "Your session was refreshed. Please submit the form again."


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    logger.warning("CSRF failure on %s (%s)", request.path, reason)

    if request.headers.get("HX-Request"):
        from sbomify.apps.core.htmx import htmx_error_response

        return htmx_error_response(RETRY_MESSAGE)

    referer = request.headers.get("Referer", "")
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        messages.error(request, RETRY_MESSAGE)
        return redirect(referer)

    from sbomify.apps.core.errors import error_response

    return error_response(request, HttpResponse(RETRY_MESSAGE, status=403))
