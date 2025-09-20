"""
Tests for the notifications system
"""
from datetime import datetime

import pytest
from django.test import RequestFactory

from .utils import get_notifications


@pytest.fixture
def notification_request():
    """Create a test request"""
    factory = RequestFactory()
    return factory.get("/")


def mock_notification_provider(request):
    """Mock notification provider for testing"""
    return {
        "id": "test_notification",
        "type": "test",
        "message": "Test notification",
        "severity": "info",
        "created_at": datetime.utcnow().isoformat(),
        "action_url": "/test/url/"
    }


def mock_list_provider(request):
    """Mock provider that returns a list"""
    return [
        {
            "id": "test_1",
            "type": "test",
            "message": "Test 1",
            "severity": "info",
            "created_at": datetime.utcnow().isoformat(),
        },
        {
            "id": "test_2",
            "type": "test",
            "message": "Test 2",
            "severity": "warning",
            "created_at": datetime.utcnow().isoformat(),
        }
    ]


def mock_error_provider(request):
    """Mock provider that raises an exception"""
    raise Exception("Test error")


@pytest.mark.django_db
class TestNotifications:
    """Test notification system"""

    def test_single_notification(self, notification_request, settings):
        """Test getting a single notification from a provider"""
        settings.NOTIFICATION_PROVIDERS = ["sbomify.apps.notifications.tests.mock_notification_provider"]
        notifications = get_notifications(notification_request)

        assert len(notifications) == 1
        assert notifications[0]["id"] == "test_notification"
        assert notifications[0]["type"] == "test"
        assert notifications[0]["severity"] == "info"
        assert notifications[0]["action_url"] == "/test/url/"

    def test_multiple_notifications(self, notification_request, settings):
        """Test getting multiple notifications from a provider"""
        settings.NOTIFICATION_PROVIDERS = ["sbomify.apps.notifications.tests.mock_list_provider"]
        notifications = get_notifications(notification_request)

        assert len(notifications) == 2
        assert notifications[0]["id"] == "test_1"
        assert notifications[1]["id"] == "test_2"

    def test_provider_error(self, notification_request, settings):
        """Test handling provider errors gracefully"""
        settings.NOTIFICATION_PROVIDERS = ["sbomify.apps.notifications.tests.mock_error_provider"]
        notifications = get_notifications(notification_request)

        assert len(notifications) == 0

    def test_multiple_providers(self, notification_request, settings):
        """Test getting notifications from multiple providers"""
        settings.NOTIFICATION_PROVIDERS = [
            "sbomify.apps.notifications.tests.mock_notification_provider",
            "sbomify.apps.notifications.tests.mock_list_provider",
            "sbomify.apps.notifications.tests.mock_error_provider"
        ]
        notifications = get_notifications(notification_request)

        assert len(notifications) == 3  # 1 from first provider + 2 from second

    def test_invalid_provider(self, notification_request, settings):
        """Test handling invalid provider paths gracefully"""
        settings.NOTIFICATION_PROVIDERS = ["nonexistent.module.provider"]
        notifications = get_notifications(notification_request)

        assert len(notifications) == 0

    def test_no_providers(self, notification_request, settings):
        """Test getting notifications with no providers configured"""
        settings.NOTIFICATION_PROVIDERS = []
        notifications = get_notifications(notification_request)

        assert len(notifications) == 0
