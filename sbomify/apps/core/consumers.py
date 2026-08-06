"""
WebSocket consumers for real-time updates.

This module provides WebSocket consumers for broadcasting updates to workspace members.
"""

from __future__ import annotations

from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from sbomify.logging import getLogger

logger = getLogger(__name__)


class WorkspaceConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for workspace-scoped real-time updates.

    Handles WebSocket connections for a specific workspace, allowing broadcast
    of events like SBOM uploads, vulnerability scan completions, and notifications
    to all connected workspace members.

    URL pattern: ws/workspace/<workspace_key>/
    """

    async def connect(self) -> None:
        """Handle WebSocket connection."""
        # Get workspace key from URL route
        self.workspace_key = self.scope["url_route"]["kwargs"]["workspace_key"]
        self.group_name = f"workspace_{self.workspace_key}"

        # Check if user is authenticated
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            logger.warning(f"WebSocket connection rejected: unauthenticated user for workspace {self.workspace_key}")
            await self.close()
            return

        # Verify user is a member of this workspace
        is_member = await self._check_workspace_membership(user, self.workspace_key)
        if not is_member:
            user_id = user.id  # type: ignore[attr-defined]
            logger.warning(
                f"WebSocket connection rejected: user {user_id} is not a member of workspace {self.workspace_key}"
            )
            await self.close()
            return

        # Join workspace group. A broker mid-restart raises here; closing
        # with 1012 (service restart) turns that into an orderly client
        # retry instead of an "Exception in ASGI application" traceback.
        #
        # The traceback goes to debug rather than warning: a broker restart
        # fails every open socket at once, and one stack per connection is the
        # noise this was written to stop. The warning line still names the
        # workspace, which is what a reader needs.
        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
        except Exception as exc:
            logger.warning(f"WebSocket group join failed for workspace {self.workspace_key}: {exc!r}")
            logger.debug("group_add traceback", exc_info=True)
            await self.close(code=1012)
            return

        try:
            await self.accept()
        except Exception as exc:
            logger.warning(f"WebSocket accept failed for workspace {self.workspace_key}: {exc!r}")
            logger.debug("accept traceback", exc_info=True)
            # The group membership was taken and disconnect() never runs for a
            # socket that was never accepted, so it would sit in the group
            # until the channel layer expired it, and every broadcast would
            # keep addressing a channel with nobody on the other end.
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.debug("group_discard after failed accept also failed", exc_info=True)
            await self.close(code=1012)
            return

        connected_user_id = user.id  # type: ignore[attr-defined]
        logger.debug(f"WebSocket connected: user={connected_user_id}, workspace={self.workspace_key}")

    @database_sync_to_async
    def _check_workspace_membership(self, user: Any, workspace_key: str) -> bool:
        """Check if the user is a member of the workspace."""
        from sbomify.apps.teams.models import Team

        return Team.objects.filter(key=workspace_key, members=user).exists()

    async def disconnect(self, close_code: Any):  # type: ignore[no-untyped-def]
        """Handle WebSocket disconnection."""
        # Leave workspace group. When the broker itself died, every open
        # socket disconnects at once and each group_discard would raise —
        # the membership is gone with the broker, so there is nothing to
        # clean up and nothing worth a traceback per connection.
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.debug("group_discard failed during disconnect; broker likely restarting", exc_info=True)

        user = self.scope.get("user")
        user_id = user.id if user and user.is_authenticated else "anonymous"  # type: ignore[attr-defined]
        logger.debug(f"WebSocket disconnected: user={user_id}, code={close_code}")

    async def receive_json(self, content: Any) -> None:  # type: ignore[override]
        """
        Handle incoming WebSocket messages.

        Currently, this is a receive-only consumer. Clients don't send messages,
        they only receive broadcasts from the server.
        """
        # For now, we don't expect clients to send messages
        # This could be extended for client-to-server communication if needed
        logger.debug(f"Received unexpected client message: {content}")

    async def workspace_message(self, event: Any):  # type: ignore[no-untyped-def]
        """
        Handle workspace broadcast messages.

        This method is called when a message is sent to the workspace group
        via channel_layer.group_send with type="workspace_message".

        Args:
            event: Dict containing:
                - type: "workspace_message" (used for routing)
                - data: The actual message data to send to the client
        """
        # A broadcast fans out to every channel in the group, and by the time it
        # arrives a given socket may already be gone: the reader closed the tab,
        # the connection dropped, or the broker is restarting. Sending to it
        # raises, and an exception escaping a consumer handler is what uvicorn
        # logs as "Exception in ASGI application" — one stack per dead socket,
        # per broadcast, for something that is a normal end to a connection.
        #
        # Nothing is retried. The payload is a refresh trigger the client
        # re-derives when it reconnects, so a socket that missed one has lost
        # nothing a reconnect does not restore.
        try:
            await self.send_json(event["data"])
        except KeyError:
            # A producer sent an event without a data key. That is a bug in the
            # caller rather than a transport failure, so it is worth a real log
            # line instead of the debug the disconnect cases get.
            logger.warning(f"Dropped a workspace_message with no data payload: {event!r}")
        except Exception:
            logger.debug("workspace_message send failed; socket likely gone", exc_info=True)
