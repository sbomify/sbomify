"""The CRA audit trail must outlive a raised LOG_LEVEL.

``sbomify/apps/compliance/audit.py`` emits every record at INFO, and its own
docstring reserves ``sbomify.compliance.audit`` for routing them to a dedicated
sink. Without an explicit entry the logger inherits ``sbomify``, whose level is
``LOG_LEVEL``, so raising that to WARNING in production silences the trail with
no other symptom.
"""

import logging

from django.conf import settings

LOGGER_NAME = "sbomify.compliance.audit"


def test_the_logger_is_pinned_independent_of_log_level():
    """An explicit INFO entry, not an inherited one.

    Level alone is not enough. A logger that resolves INFO but owns no handler
    still delivers nothing once its parent is raised, because the record is
    dropped where it would have been emitted rather than where it was filtered.
    So assert it carries its own handler and does not depend on the parent.
    """
    config = settings.LOGGING["loggers"][LOGGER_NAME]

    assert config["level"] == "INFO"
    assert config["handlers"], "no handler of its own, so delivery still rides on the parent"
    assert config["propagate"] is False


def test_a_record_is_emitted_with_the_parent_raised():
    """The end the other tests only approach: a record actually reaches a handler."""
    parent = logging.getLogger("sbomify")
    logger = logging.getLogger(LOGGER_NAME)
    previous = parent.level
    captured: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    handler = Capture()
    parent.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        logger.info("scope screening changed")
    finally:
        logger.removeHandler(handler)
        parent.setLevel(previous)

    assert [r.getMessage() for r in captured] == ["scope screening changed"]


def test_info_survives_a_raised_parent_level():
    """The failure this guards: raising the parent silences the trail.

    A logger with no level of its own resolves through its parents, so removing
    the entry above would leave this False whenever ``sbomify`` sits at WARNING.
    """
    parent = logging.getLogger("sbomify")
    previous = parent.level
    parent.setLevel(logging.WARNING)
    try:
        assert logging.getLogger(LOGGER_NAME).isEnabledFor(logging.INFO)
    finally:
        parent.setLevel(previous)


def test_the_module_logs_to_that_name():
    """The pin is worthless if the emitters use another logger."""
    from sbomify.apps.compliance import audit

    assert audit._LOG.name == LOGGER_NAME
