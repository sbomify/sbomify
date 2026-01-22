"""
WebSocket URL routing for Django Channels.

This module defines the URL patterns for WebSocket connections.
"""

from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    # Workspace-scoped WebSocket for real-time updates
    # URL: ws://host/ws/workspace/<workspace_key>/
    re_path(r"ws/workspace/(?P<workspace_key>[\w-]+)/$", consumers.WorkspaceConsumer.as_asgi()),
]
