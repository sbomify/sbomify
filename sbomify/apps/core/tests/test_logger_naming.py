"""The same app was logging under two different names.

``sbomify.logging.getLogger`` prepended ``sbomify.`` unconditionally, and all
63 call sites pass ``__name__`` — which already begins with ``sbomify.``. So
modules using the helper logged as

    sbomify.sbomify.apps.plugins.orchestrator

while modules using the stdlib ``getLogger`` directly logged as

    sbomify.apps.plugins.tasks

Both from the same app, in the same request. In 48 hours of staging, 248,924
lines carried the doubled prefix.

Nothing broke, because the ``sbomify`` logger configured in settings is an
ancestor of both names and catches everything either way. It stops being
harmless the moment anyone configures a specific module: a handler or level
attached to ``sbomify.apps.plugins`` silently misses every logger the helper
made, which is half of them. That is a trap laid for whoever next tries to
quiet one noisy module.
"""

from __future__ import annotations

import pytest

from sbomify.logging import getLogger


class TestTheNameIsNotDoubled:
    def test_a_dunder_name_is_left_alone(self) -> None:
        """The defect, in the form every call site actually takes."""
        assert getLogger("sbomify.apps.plugins.orchestrator").name == "sbomify.apps.plugins.orchestrator"

    def test_the_root_itself_is_left_alone(self) -> None:
        assert getLogger("sbomify").name == "sbomify"

    @pytest.mark.parametrize(
        "module",
        [
            "sbomify.apps.core.consumers",
            "sbomify.apps.billing.stripe_client",
            "sbomify.apps.oidc.utils",
            "sbomify.apps.teams.apis",
        ],
    )
    def test_real_modules_keep_their_import_path(self, module: str) -> None:
        """A logger name that matches the module path is the whole point: it is
        what makes a log line greppable back to the file that wrote it."""
        assert getLogger(module).name == module


class TestTheNamespacingStillWorks:
    """The prefix exists for a reason and must survive for bare names."""

    def test_a_bare_name_is_namespaced(self) -> None:
        assert getLogger("audit.token_auth").name == "sbomify.audit.token_auth"

    def test_a_name_merely_starting_with_the_letters_is_namespaced(self) -> None:
        """``sbomifyish`` is not inside the namespace, and the guard must key on
        the dot rather than on the prefix alone."""
        assert getLogger("sbomifyish").name == "sbomify.sbomifyish"


class TestEveryHelperLoggerLandsUnderTheRoot:
    """Whatever the input, settings' ``sbomify`` logger has to remain an
    ancestor — that is what routes the records at all."""

    @pytest.mark.parametrize(
        "name",
        ["sbomify", "sbomify.apps.core.consumers", "audit.token_auth", "sbomifyish"],
    )
    def test_the_root_logger_is_an_ancestor(self, name: str) -> None:
        resolved = getLogger(name).name

        assert resolved == "sbomify" or resolved.startswith("sbomify.")


class TestTheCodebaseAgreesWithItself:
    def test_modules_using_the_helper_log_under_their_own_path(self) -> None:
        """Reaches into two real modules rather than asserting on strings, so
        this fails if a call site is ever changed to pass something else."""
        from sbomify.apps.core import consumers
        from sbomify.apps.plugins import orchestrator

        assert consumers.logger.name == "sbomify.apps.core.consumers"
        assert orchestrator.logger.name == "sbomify.apps.plugins.orchestrator"

    def test_helper_and_stdlib_modules_share_a_naming_scheme(self) -> None:
        """The two halves of the codebase disagreed; this is the assertion that
        they no longer do."""
        from sbomify.apps.plugins import orchestrator, tasks

        assert orchestrator.logger.name.startswith("sbomify.apps.plugins")
        assert tasks.logger.name.startswith("sbomify.apps.plugins")
