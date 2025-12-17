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

    # Get dismissed notification IDs from session (excluding upgrade notifications)
    dismissed_ids = set(request.session.get("dismissed_notifications", []))

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
                        for notification in provider_notifications:
                            # Don't filter out upgrade notifications (they can't be dismissed)
                            is_upgrade = notification.type == "community_upgrade"
                            is_dismissed = notification.id in dismissed_ids
                            if is_upgrade or not is_dismissed:
                                notifications.append(notification)
                    else:
                        # Single notification
                        is_upgrade = provider_notifications.type == "community_upgrade"
                        is_dismissed = provider_notifications.id in dismissed_ids
                        if is_upgrade or not is_dismissed:
                            notifications.append(provider_notifications)
            except Exception as e:
                logger.exception(f"Exception in provider {provider_path}: {str(e)}")
                raise

        except Exception as e:
            logger.error(f"Error getting notifications from provider {provider_path}: {str(e)}")

    return notifications
