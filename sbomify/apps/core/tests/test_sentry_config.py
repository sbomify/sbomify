"""Sentry wiring regression tests.

A misconfigured Sentry fails silently: with no DSN the SDK still builds a client
whose transport is None, drops every event, and reports is_active() as True. The
tests below pin the two settings that decided whether events were reportable and
findable, both of which had been wrong in deployment.
"""

import os
from unittest.mock import patch

import sentry_sdk


def _init(**overrides):
    """Initialise a client exactly the way settings.py does."""
    sentry_sdk.init(
        dsn=overrides.get("dsn", "https://public@example.invalid/1"),
        environment=os.environ.get("SENTRY_ENVIRONMENT") or None,
    )
    return sentry_sdk.get_client()


class TestSentryEnvironment:
    """settings.py must not hardcode an environment fallback.

    Passing a literal default overrides the SDK's own resolution, which reads
    SENTRY_ENVIRONMENT and otherwise uses "production". A "development" fallback
    tagged every deployment that did not set the variable as development, so
    production alert rules matched nothing.
    """

    def test_defaults_to_production_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_ENVIRONMENT", None)
            assert _init().options["environment"] == "production"

    def test_respects_explicit_environment(self):
        with patch.dict(os.environ, {"SENTRY_ENVIRONMENT": "staging"}):
            assert _init().options["environment"] == "staging"

    def test_never_silently_becomes_development(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_ENVIRONMENT", None)
            assert _init().options["environment"] != "development"


class TestSentryDsn:
    """Document the silent-failure mode the startup warning exists to catch."""

    def test_missing_dsn_drops_every_event(self):
        client = _init(dsn=None)
        assert client.transport is None, "no transport means events are discarded"
        # is_active() stays True, which is why the absence needs an explicit log.
        assert client.is_active() is True
