"""
Utilities for handling notifications
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils.module_loading import import_string

from sbomify.logging import getLogger

logger = getLogger(__name__)


def get_notifications(request: HttpRequest) -> list[Any]:
    """Get notifications from all enabled providers"""
    all_provider_notifications: list[Any] = []
    for provider_path in getattr(settings, "NOTIFICATION_PROVIDERS", []):
        try:
            all_provider_notifications.extend(import_string(provider_path)(request) or [])
        except Exception:
            logger.exception(f"Error getting notifications from provider {provider_path}")

    # Re-read dismissed IDs after all providers have run (providers may modify session)
    dismissed_ids = set(request.session.get("dismissed_notifications", []))
    return [n for n in all_provider_notifications if n.id not in dismissed_ids]
