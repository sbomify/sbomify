"""Logging filter helpers used by the Django LOGGING config.

Kept out of ``sbomify.settings`` so tests can import the filter without
loading the full settings module (which would bypass ``sbomify.test_settings``).
"""

from __future__ import annotations

import logging


def is_benign_shielded_future_error(record: logging.LogRecord) -> bool:
    # CancelledError comes from asgiref when clients disconnect mid-request;
    # ConnectionClosed (and its subclasses ConnectionClosedError/ConnectionClosedOK)
    # from websockets on keepalive ping timeout or normal client close.
    message = record.getMessage()
    return "exception in shielded future" in message and any(
        exc in message for exc in ("CancelledError", "ConnectionClosed")
    )


# Caddy's on-demand TLS `ask` endpoint (see Caddyfile: `ask
# http://sbomify-backend:8000/api/v1/internal/domains`). Caddy calls it before
# issuing a certificate for an unrecognised SNI, and a 404 is the documented way
# to answer "do not issue one" — a successful answer, not a failure.
_ON_DEMAND_TLS_ASK_PATH = "/api/v1/internal/domains"


def is_on_demand_tls_ask_denial(record: logging.LogRecord) -> bool:
    """``True`` for Django's 404 warning on the on-demand TLS ask endpoint.

    Django logs every 4xx it returns through ``django.request`` as
    "Not Found: <path>". For every other endpoint that is a useful signal. For
    this one it is the opposite: refusing a certificate is the endpoint's whole
    job, and anything on the internet that opens a TLS connection to our IP with
    an unknown SNI makes Caddy ask once.

    It was a third of the entire production log stream — 49,835 of 152,128
    messages in a week, roughly one every twelve seconds — and it says nothing
    the endpoint has not already said better: ``check_domain_allowed`` logs each
    denial *with the domain*, deduplicated by the resolve cache, which is the
    line worth having. A bare repeated path is not.

    Matched on the exact line Django writes for a 404 and nothing else. The
    level is not a proxy for the status: ``log_response`` writes *every* 4xx at
    WARNING, and this endpoint answers 422 when Caddy calls it without a
    ``domain`` (``test_internal_apis.py``), so keying on WARNING alone would
    also discard "Unprocessable Entity" - a misconfigured proxy, silently
    swallowed. Only "Not Found" is the expected denial; every other status here
    is a genuine failure of the ask endpoint and stays visible.
    """
    if record.name != "django.request":
        return False
    # django.core.handlers.base logs `log_response("%s: %s", reason_phrase, path)`.
    if record.getMessage() != f"Not Found: {_ON_DEMAND_TLS_ASK_PATH}":
        return False

    # The message alone cannot tell the endpoint's answer from the route having
    # gone missing: a URL-resolver 404 writes the identical line. That failure
    # makes Caddy refuse a certificate for every custom domain, so it is the
    # last thing that should be swallowed as routine.
    #
    # ``_get_response`` assigns ``request.resolver_match`` once a route matches
    # and before the view runs, so a 404 the view returned has one and a 404
    # from resolution failing does not. No match means the ask endpoint is not
    # registered, and that line stays.
    request = getattr(record, "request", None)
    return getattr(request, "resolver_match", None) is not None
