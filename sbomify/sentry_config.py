"""Pure helpers for Sentry startup wiring.

Extracted from ``settings.py`` so regression tests can pin the actual
resolution logic instead of duplicating it locally.
"""

from __future__ import annotations

import os
import sys


def resolve_environment(*, debug: bool) -> str | None:
    """Return the value to pass as ``environment`` to ``sentry_sdk.init``.

    Passing ``None`` lets sentry-sdk read ``SENTRY_ENVIRONMENT`` itself and,
    if that is also unset, fall back to ``"production"``. We only apply a
    ``"development"`` fallback when Django is running in DEBUG mode, so a
    developer who exports ``SENTRY_DSN`` locally without also setting
    ``SENTRY_ENVIRONMENT`` does not ship events tagged ``"production"`` into
    real production alert rules.
    """
    explicit = os.environ.get("SENTRY_ENVIRONMENT")
    if explicit:
        return explicit
    if debug:
        return "development"
    return None


def should_warn_missing_dsn(dsn: str | None, *, debug: bool) -> bool:
    """Return ``True`` when the missing-DSN startup warning should fire.

    Suppressed when a DSN is set, when Django is in DEBUG mode (dev
    workflows opt out of error reporting on purpose), and when pytest is
    the process driver (tests import settings and would otherwise emit the
    warning at every collection).
    """
    if dsn or debug:
        return False
    if "pytest" in sys.modules:
        return False
    return True
