import logging

_ROOT = "sbomify"


def getLogger(name: str) -> logging.Logger:
    """Return a logger under the ``sbomify`` namespace.

    Takes either a module's ``__name__`` — which already begins with
    ``sbomify.`` — or a bare label such as ``"audit.token_auth"``, and adds the
    prefix only when it is missing. Both forms are in use, so **neither branch
    is dead**: ``access_tokens.utils`` calls this with a bare name for the
    PAT/OIDC audit trail, and reducing this to ``logging.getLogger(name)``
    would move that logger outside the configured ``sbomify`` tree and leave
    the trail to the WARNING root, where its INFO records are dropped.

    Prepending unconditionally produced
    ``sbomify.sbomify.apps.plugins.orchestrator`` for the ``__name__`` callers,
    while modules using the stdlib ``getLogger`` directly produced
    ``sbomify.apps.plugins.tasks`` — the same app under two names, roughly a
    quarter of a million lines a day under the doubled one.

    Harmless in isolation, because the ``sbomify`` logger configured in
    settings is an ancestor of both. It stops being harmless the moment
    anyone configures a specific module — a handler or level attached to
    ``sbomify.apps.plugins`` silently misses every logger the helper made.
    """
    if name == _ROOT or name.startswith(f"{_ROOT}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT}.{name}")
