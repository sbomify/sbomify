"""Logging filter helpers used by the Django LOGGING config.

Kept out of ``sbomify.settings`` so tests can import the filter without
loading the full settings module (which would bypass ``sbomify.test_settings``).
"""

from __future__ import annotations

import logging
import re


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


# Signed download URLs carry their credential in the ``token`` query parameter.
_TOKEN_QUERY_VALUE = re.compile(r"([?&]token=)[^&\s\"]*")

# Routes whose next path segment is the credential: invitation links, the
# emailed unsubscribe link, and allauth's email confirmation and password reset
# keys. ``%2F`` covers the same paths URL-encoded inside a ``next`` parameter,
# where the key's own characters are percent-encoded too, so the segment ends
# at the next separator, raw or encoded, rather than at the first ``%``.
_SLASH = r"(?:/|%2F)"
_SECRET_PATH_SEGMENT = re.compile(
    rf"((?:accept_invite|onboarding{_SLASH}unsubscribe|accounts{_SLASH}confirm-email"
    rf"|accounts{_SLASH}password{_SLASH}reset{_SLASH}key){_SLASH})"
    rf"(?!done{_SLASH})(?:(?!%2F)[^/?&#\s\"])+",
    re.IGNORECASE,
)


# allauth provider callbacks (``/accounts/<provider>/login/callback/`` and
# ``/accounts/oidc/<id>/login/callback/``) carry the one-time authorization
# ``code`` and the ``state`` in the query string.
_OAUTH_CALLBACK_QUERY = re.compile(r"(/accounts/(?:[\w.-]+/){1,2}login/callback/?\?)([^\s\"#]*)")
_OAUTH_CALLBACK_PARAM = re.compile(r"((?:^|&)(?:code|state)=)[^&]*")


def _redact_oauth_callback(match: re.Match[str]) -> str:
    return match.group(1) + _OAUTH_CALLBACK_PARAM.sub(r"\1[redacted]", match.group(2))


def _redact(value: str) -> str:
    value = _TOKEN_QUERY_VALUE.sub(r"\1[redacted]", value)
    value = _OAUTH_CALLBACK_QUERY.sub(_redact_oauth_callback, value)
    return _SECRET_PATH_SEGMENT.sub(r"\1[redacted]", value)


def redact_access_log_secrets(record: logging.LogRecord) -> bool:
    """Replace credentials carried in a URL with ``[redacted]`` in the record's args.

    The server's access log writes the full request path, query string
    included, so signed and emailed links would otherwise be stored with the
    credential that grants them.
    """
    if isinstance(record.args, tuple):
        record.args = tuple(_redact(arg) if isinstance(arg, str) else arg for arg in record.args)
    return True
