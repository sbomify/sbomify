"""
Utilities for handling notifications
"""

from importlib import import_module

from django.conf import settings

from sbomify.logging import getLogger

logger = getLogger(__name__)


def get_notifications(request):
    """Get notifications from all enabled providers"""
    notifications = []
    providers = getattr(settings, "NOTIFICATION_PROVIDERS", [])

    for provider_path in providers:
        try:
            # Split into module path and function name
            module_path, func_name = provider_path.rsplit(".", 1)

            # Import the module and get the function
            module = import_module(f"{module_path}")
            provider_func = getattr(module, func_name)

            # Get notifications from this provider
            provider_notifications = provider_func(request)
            if provider_notifications:
                if isinstance(provider_notifications, list):
                    notifications.extend(provider_notifications)
                else:
                    notifications.append(provider_notifications)

        except Exception as e:
            logger.error(f"Error getting notifications from provider {provider_path}: {str(e)}")

    return notifications
