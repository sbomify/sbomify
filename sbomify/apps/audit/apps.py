from __future__ import annotations

from typing import Any

from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate


def _install_guards(sender: Any, using: str = "default", **kwargs: Any) -> None:
    """Re-install the table's triggers after every migrate.

    The migration installs them on a real database. A test database built with
    ``--nomigrations`` never runs it, and this is what gives that database the
    same guarantees, so the tests exercise the real controls.
    """
    from django.db import connections

    from .db import install

    connection = connections[using]
    if "audit_events" not in connection.introspection.table_names():
        return
    with connection.schema_editor() as schema_editor:
        install(schema_editor, block_truncate=getattr(settings, "AUDIT_LOG_BLOCK_TRUNCATE", True))


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.audit"
    label = "audit"

    def ready(self) -> None:
        # cron, so the retention purge actor is registered with the worker.
        from . import cron, signals  # noqa: F401

        signals.connect()
        post_migrate.connect(_install_guards, sender=self, dispatch_uid="audit_install_guards")
