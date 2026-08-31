"""The same app was logging under two different names.

``sbomify.logging.getLogger`` prepended ``sbomify.`` unconditionally, and
almost every call site passes ``__name__`` — which already begins with
``sbomify.``. So modules using the helper logged as

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
        "module_path",
        [
            "sbomify.apps.core.consumers",
            "sbomify.apps.billing.stripe_client",
            "sbomify.apps.oidc.utils",
            "sbomify.apps.teams.apis",
        ],
    )
    def test_real_modules_keep_their_import_path(self, module_path: str) -> None:
        """A logger name that matches the module path is the whole point: it is
        what makes a log line greppable back to the file that wrote it.

        Imports the module and reads the logger it actually built, rather than
        passing the path back into the helper. The string form asserted only
        that the helper is a near-identity on names shaped like a module path —
        it would have passed unchanged if every one of these call sites had
        switched to a hand-written name.
        """
        import importlib

        module = importlib.import_module(module_path)

        assert module.logger.name == module_path


class TestTheNamespacingStillWorks:
    """The prefix exists for a reason and must survive for bare names."""

    def test_a_bare_name_is_namespaced(self) -> None:
        assert getLogger("audit.token_auth").name == "sbomify.audit.token_auth"

    def test_a_name_merely_starting_with_the_letters_is_namespaced(self) -> None:
        """``sbomifyish`` is not inside the namespace, and the guard must key on
        the dot rather than on the prefix alone."""
        assert getLogger("sbomifyish").name == "sbomify.sbomifyish"


class TestTheBareNameCallerIsReal:
    """The branch a reader is most likely to think is dead.

    The audit trail for PAT and OIDC authentication goes through this helper
    with a bare label, not a ``__name__``. Reducing the helper to
    ``logging.getLogger(name)`` would move ``audit.token_auth`` outside the
    configured ``sbomify`` tree, where its INFO records fall through to the
    WARNING root and are dropped — an auth forensic trail that stops silently.
    """

    def test_the_audit_logger_lands_under_the_configured_tree(self) -> None:
        from sbomify.apps.access_tokens import utils

        assert utils.audit_log.name == "sbomify.audit.token_auth"

    def test_a_bare_name_is_namespaced(self) -> None:
        assert getLogger("audit.token_auth").name == "sbomify.audit.token_auth"
