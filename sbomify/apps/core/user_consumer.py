"""A signed-in user's own socket, for news addressed to them rather than to a workspace.

The workspace socket only admits people who may read the workspace's internal
activity. Someone asking a trust center for access is not one of them, yet the
public page wants to tell them the moment their request is decided. This socket
carries only what ``broadcast_to_user`` addresses to that user.

URL pattern: ws/user/
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.core.consumers import WS_CLOSE_POLICY_VIOLATION, WS_CLOSE_SERVICE_RESTART, WorkspaceConsumer
from sbomify.apps.core.utils import user_group_name
from sbomify.logging import getLogger

logger = getLogger(__name__)


class UserConsumer(WorkspaceConsumer):
    """Joins the signed-in user's own group. Delivery and teardown are the workspace socket's."""

    async def connect(self) -> None:
        # Accepted first for the same reason as the workspace socket: a close
        # code only reaches the browser after the handshake completes.
        try:
            await self.accept()
        except Exception as exc:
            logger.warning(f"User WebSocket accept failed: {exc!r}")
            try:
                await self._reject(WS_CLOSE_SERVICE_RESTART)
            except Exception:
                logger.debug("close after failed accept also failed", exc_info=True)
            return

        user: Any = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self._reject(WS_CLOSE_POLICY_VIOLATION)
            return

        self.group_name = user_group_name(user.id)
        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
        except Exception as exc:
            logger.warning(f"User WebSocket group join failed: {exc!r}")
            await self._reject(WS_CLOSE_SERVICE_RESTART)
