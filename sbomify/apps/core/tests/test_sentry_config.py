"""Sentry wiring regression tests.

A misconfigured Sentry fails silently: with no DSN the SDK still builds a
client whose transport is None, drops every event, and reports is_active()
as True. The tests here pin the resolution helpers in
``sbomify.sentry_config`` -- which ``settings.py`` calls -- so a revert of
the underlying fix (e.g. reintroducing a hardcoded ``"development"``
fallback) is caught in CI.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest
import sentry_sdk

from sbomify.sentry_config import resolve_environment, should_warn_missing_dsn


@pytest.fixture
def sentry_client_isolation():
    """Snapshot and restore the process-wide sentry client.

    ``sentry_sdk.init`` replaces the global scope's client; without this
    fixture, tests that re-init strip the DjangoIntegration /
    DramatiqIntegration / LoggingIntegration wired up by ``settings.py``
    and every subsequent test in the same worker sees the stripped-down
    client. Only the global scope is restored: setting a client on the
    current or isolation scope pins it there and breaks sentry_sdk's own
    scope fallback chain.
    """
    original = sentry_sdk.Scope.get_global_scope().client
    try:
        yield
    finally:
        sentry_sdk.Scope.get_global_scope().set_client(original)


def _init(dsn: str | None = "https://public@example.invalid/1") -> sentry_sdk.Client:
    """Initialise a client using the same resolution helper as ``settings.py``.

    Only ``dsn`` and ``environment`` are exercised here; the real settings
    call also wires up ``release``, three integrations, ``traces_sampler``,
    ``profiles_sample_rate`` and ``ignore_errors``, which are out of scope
    for these regression tests.
    """
    sentry_sdk.init(
        dsn=dsn,
        # Passing DEBUG=False mirrors the production code path; individual
        # tests override the environment resolution directly when needed.
        environment=resolve_environment(debug=False),
    )
    return sentry_sdk.get_client()


class TestResolveEnvironment:
    """``resolve_environment`` is what ``settings.py`` calls; pin its contract.

    A hardcoded ``"development"`` fallback tagged every deployment that did
    not set ``SENTRY_ENVIRONMENT`` as development, so production alert rules
    matched nothing. The fix is: use the env var when set, fall back to
    ``"development"`` only in DEBUG mode, otherwise return ``None`` and let
    the SDK resolve to ``"production"``.
    """

    def test_prod_defaults_to_none_so_sdk_uses_production(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_ENVIRONMENT", None)
            assert resolve_environment(debug=False) is None

    def test_debug_defaults_to_development(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_ENVIRONMENT", None)
            assert resolve_environment(debug=True) == "development"

    def test_explicit_env_wins_over_debug(self):
        with patch.dict(os.environ, {"SENTRY_ENVIRONMENT": "staging"}):
            assert resolve_environment(debug=True) == "staging"
            assert resolve_environment(debug=False) == "staging"

    def test_empty_env_falls_back_like_unset(self):
        with patch.dict(os.environ, {"SENTRY_ENVIRONMENT": ""}):
            assert resolve_environment(debug=False) is None
            assert resolve_environment(debug=True) == "development"

    def test_prod_never_silently_becomes_development(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_ENVIRONMENT", None)
            assert resolve_environment(debug=False) != "development"


class TestShouldWarnMissingDsn:
    """The startup warning is the only signal that Sentry silently drops events."""

    def test_warns_when_dsn_missing_in_prod(self):
        with patch.dict(sys.modules, {}, clear=False):
            sys.modules.pop("pytest", None)
            assert should_warn_missing_dsn(None, debug=False) is True

    def test_silent_when_dsn_present(self):
        assert should_warn_missing_dsn("https://x@example.invalid/1", debug=False) is False

    def test_silent_when_debug(self):
        assert should_warn_missing_dsn(None, debug=True) is False

    def test_silent_under_pytest(self):
        # pytest is imported by virtue of running this test.
        assert "pytest" in sys.modules
        assert should_warn_missing_dsn(None, debug=False) is False


class TestSentryClient:
    """Sanity-check the client the resolution helpers actually build."""

    def test_missing_dsn_drops_every_event(self, sentry_client_isolation):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_DSN", None)
            client = _init(dsn=None)
            assert client.transport is None, "no transport means events are discarded"
            # is_active() stays True, which is why the absence needs an explicit log.
            assert client.is_active() is True

    def test_real_dsn_builds_transport(self, sentry_client_isolation):
        client = _init(dsn="https://public@example.invalid/1")
        assert client.transport is not None
        assert client.is_active() is True


class TestSettingsIntegration:
    """Verify ``settings.py`` actually wires the resolution helpers.

    The unit tests above pin the helper contracts, but a revert of
    ``settings.py`` that drops the calls (e.g. reverts to a hardcoded
    ``environment="development"``) would not be caught by those alone.
    This test imports ``sbomify.settings`` and checks the code path.
    """

    def test_settings_uses_resolution_helpers(self):
        import sbomify.settings as settings_module

        assert settings_module.resolve_environment is resolve_environment
        assert settings_module.should_warn_missing_dsn is should_warn_missing_dsn
