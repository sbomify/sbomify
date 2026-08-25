"""
WebSocket URL routing for Django Channels.

This module defines the URL patterns for WebSocket connections.
"""

from __future__ import annotations

from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    # Workspace-scoped WebSocket for real-time updates
    # URL: ws://host/ws/workspace/<workspace_key>/
    re_path(r"ws/workspace/(?P<workspace_key>[\w-]+)/$", consumers.WorkspaceConsumer.as_asgi()),  # type: ignore[arg-type]
    # Anything else. Channels raises ValueError when no pattern matches, which
    # escapes as an unhandled ASGI exception and reaches the error tracker as a
    # fault of ours — internet scanners probing paths like /wsproxy were enough
    # to raise it. A path we do not serve is a verdict about the client, so it
    # is refused the same way an unauthorised workspace socket is.
    #
    # Last in the list, and the only pattern without an anchor, so it is reached
    # only after every real route has failed to match.
    re_path(r"", consumers.UnknownPathConsumer.as_asgi()),  # type: ignore[arg-type]
]
