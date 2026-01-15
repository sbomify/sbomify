from __future__ import annotations

from django.conf import settings
from django.db import transaction


def run_on_commit(callback) -> None:
    """
    Execute callback on commit, but run immediately during tests.
    """
    if getattr(settings, "TESTING", False):
        callback()
        return
    transaction.on_commit(callback)
