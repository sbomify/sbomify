"""
WebSocket consumers for real-time updates.

This module provides WebSocket consumers for broadcasting updates to workspace members.
"""

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

    async def connect(self):
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
            logger.warning(
                f"WebSocket connection rejected: user {user.id} is not a member of workspace {self.workspace_key}"
            )
            await self.close()
            return

        # Join workspace group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.debug(f"WebSocket connected: user={user.id}, workspace={self.workspace_key}")

    @database_sync_to_async
    def _check_workspace_membership(self, user, workspace_key: str) -> bool:
        """Check if the user is a member of the workspace."""
        from sbomify.apps.teams.models import Team

        return Team.objects.filter(key=workspace_key, members=user).exists()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        # Leave workspace group
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

        user = self.scope.get("user")
        user_id = user.id if user and user.is_authenticated else "anonymous"
        logger.debug(f"WebSocket disconnected: user={user_id}, code={close_code}")

    async def receive_json(self, content):
        """
        Handle incoming WebSocket messages.

        Currently, this is a receive-only consumer. Clients don't send messages,
        they only receive broadcasts from the server.
        """
        # For now, we don't expect clients to send messages
        # This could be extended for client-to-server communication if needed
        logger.debug(f"Received unexpected client message: {content}")

    async def workspace_message(self, event):
        """
        Handle workspace broadcast messages.

        This method is called when a message is sent to the workspace group
        via channel_layer.group_send with type="workspace_message".

        Args:
            event: Dict containing:
                - type: "workspace_message" (used for routing)
                - data: The actual message data to send to the client
        """
        # Send message to WebSocket client
        await self.send_json(event["data"])
