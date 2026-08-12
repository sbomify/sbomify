import logging

_ROOT = "sbomify"


def getLogger(name: str) -> logging.Logger:
    """Return a logger under the ``sbomify`` namespace.

    The prefix is only added when it is missing. Every call site passes
    ``__name__``, which already begins with ``sbomify.``, so prepending
    unconditionally produced ``sbomify.sbomify.apps.plugins.orchestrator`` —
    while modules using the stdlib ``getLogger`` directly produced
    ``sbomify.apps.plugins.tasks``. The same app logged under two different
    names, roughly a quarter of a million lines a day under the doubled one.

    Harmless in isolation, because the ``sbomify`` logger configured in
    settings is an ancestor of both. It stops being harmless the moment
    anyone configures a specific module — a handler or level attached to
    ``sbomify.apps.plugins`` silently misses every logger the helper made,
    which is half of them.
    """
    if name == _ROOT or name.startswith(f"{_ROOT}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT}.{name}")
