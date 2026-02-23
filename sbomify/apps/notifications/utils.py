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

    # Collect all notifications from providers first
    all_provider_notifications = []

    for provider_path in providers:
        try:
            # Split into module path and function name
            module_path, func_name = provider_path.rsplit(".", 1)

            # Import the module and get the function
            module = import_module(f"{module_path}")
            provider_func = getattr(module, func_name)

            # Get notifications from this provider
            try:
                provider_notifications = provider_func(request)
                if provider_notifications:
                    if isinstance(provider_notifications, list):
                        all_provider_notifications.extend(provider_notifications)
                    else:
                        all_provider_notifications.append(provider_notifications)
            except Exception as e:
                logger.exception(f"Exception in provider {provider_path}: {str(e)}")
                raise

        except Exception as e:
            logger.error(f"Error getting notifications from provider {provider_path}: {str(e)}")

    # Re-read dismissed IDs after all providers have run (providers may modify session)
    dismissed_ids = set(request.session.get("dismissed_notifications", []))

    # Filter out dismissed notifications
    for notification in all_provider_notifications:
        if notification.id not in dismissed_ids:
            notifications.append(notification)

    return notifications
