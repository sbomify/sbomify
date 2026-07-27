"""
WebSocket URL routing for Django Channels.

This module defines the URL patterns for WebSocket connections.
"""

from __future__ import annotations

from typing import Any

from django.urls import re_path

from . import consumers

# ``django.urls.re_path`` returns a ``URLPattern``; channels' ``URLRouter`` is
# annotated against its own ``_ExtendedURLPattern``. The two are interchangeable
# at runtime — channels re-wraps whatever it is given — but mypy cannot see
# that. Typed loosely here so the mismatch is explained once, rather than every
# consumer of this list (``sbomify/asgi.py``) carrying its own ignore.
websocket_urlpatterns: list[Any] = [
    # Workspace-scoped WebSocket for real-time updates
    # URL: ws://host/ws/workspace/<workspace_key>/
    re_path(r"ws/workspace/(?P<workspace_key>[\w-]+)/$", consumers.WorkspaceConsumer.as_asgi()),  # type: ignore[arg-type]
]
