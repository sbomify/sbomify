"""Resolve the URL path the Django health check is served under.

Caddy, the compose healthcheck and the Helm chart all read the same
``HEALTH_CHECK_PATH`` value, so the parser is strict rather than forgiving:
normalising a sloppy value here would let Django serve a path the edge does
not route.
"""

from __future__ import annotations

import re

from django.core.exceptions import ImproperlyConfigured

DEFAULT_HEALTH_CHECK_PATH = "/UuPha8mu/"

_PATH_RE = re.compile(r"/[A-Za-z0-9_-]+/")


def resolve_health_check_path(value: str | None) -> str:
    """Return the health check path, e.g. ``/UuPha8mu/``.

    An unset or empty value falls back to the default. Anything else must be a
    single path segment of letters, digits, ``-`` or ``_`` with a leading and a
    trailing slash, since the Caddyfile matches it verbatim.
    """
    if not value:
        return DEFAULT_HEALTH_CHECK_PATH
    if not _PATH_RE.fullmatch(value):
        raise ImproperlyConfigured(
            f"HEALTH_CHECK_PATH must look like /some-segment/ (letters, digits, '-' or '_'), got {value!r}"
        )
    return value
