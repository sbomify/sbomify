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

# The transport dropping under us. ``ConnectionError`` is a subclass, named
# here because it is the case this is actually about.
_SOCKET_GONE = (ConnectionError, OSError)

# RFC 6455 close codes, named because the distinction between them is the whole
# contract with the client: the store retries everything except the codes that
# are a verdict about this client, so a rejection has to be told apart from an
# outage or the client either retries something permanent or gives up on
# something temporary.
WS_CLOSE_POLICY_VIOLATION = 1008  # this client may not connect — do not retry
WS_CLOSE_SERVICE_RESTART = 1012  # the server is unavailable — please retry


def _is_socket_closed(exc: RuntimeError) -> bool:
    """Whether a ``RuntimeError`` is Channels saying the socket is already shut.

    Channels and the ASGI servers raise a plain ``RuntimeError`` for "cannot
    send once a close message has been sent", which is the ordinary end of a
    connection rather than a fault.

    Matched on the exact type rather than with ``isinstance``, because
    ``RecursionError`` and ``NotImplementedError`` are ``RuntimeError``
    subclasses and neither is a closed socket. A payload nested deeply enough
    makes ``json.dumps`` raise ``RecursionError`` from the same call as a
    dropped connection, so treating the base class as "socket gone" would put
    back exactly the silent-drop this is here to remove.
    """
    return type(exc) is RuntimeError


class WorkspaceConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for workspace-scoped real-time updates.

    Handles WebSocket connections for a specific workspace, allowing broadcast
    of events like SBOM uploads, vulnerability scan completions, and notifications
    to all connected workspace members.

    URL pattern: ws/workspace/<workspace_key>/
    """

    async def _reject(self, code: int) -> None:
        """Close a socket that never joined the workspace group.

        Drops ``group_name`` first so ``disconnect()`` skips its
        ``group_discard``. Accepting the handshake before applying the verdict
        means Channels now runs ``disconnect()`` for rejected sockets too, and
        that discard is a broker round trip for a group this connection was
        never in. It lands hardest in the case that needs it least: when
        ``group_add`` has just failed because the broker is down, every
        rejected socket would add another call to it.
        """
        if hasattr(self, "group_name"):
            del self.group_name
        await self.close(code=code)

    async def connect(self) -> None:
        """Handle WebSocket connection."""
        # Get workspace key from URL route
        self.workspace_key = self.scope["url_route"]["kwargs"]["workspace_key"]
        self.group_name = f"workspace_{self.workspace_key}"

        # Accepted before the verdicts below, so that a verdict can be
        # delivered at all. Per the ASGI spec a ``websocket.close`` sent before
        # ``websocket.accept`` makes the server refuse the handshake with HTTP
        # 403, and a refused handshake carries no close code — the browser
        # reports 1006 for all of them, which is also what it reports for a
        # dropped network. Closing after the handshake is the only way the code
        # reaches ``onclose``.
        #
        # Nothing is sent and no group is joined until the checks below pass,
        # so an unauthorised client learns nothing from the accept.
        try:
            await self.accept()
        except Exception as exc:
            logger.warning(f"WebSocket accept failed for workspace {self.workspace_key}: {exc!r}")
            logger.debug("accept traceback", exc_info=True)
            # Returning without answering at all leaves the handshake pending:
            # no 101 and no close frame, so the browser waits out its own
            # timeout and onclose never delivers a code the client can act on,
            # while this consumer sits in await_many_dispatch holding its
            # channel. Best-effort, since whatever broke the accept will often
            # break this too — but an unanswered handshake is the worse end.
            try:
                await self._reject(WS_CLOSE_SERVICE_RESTART)
            except Exception:
                logger.debug("close after failed accept also failed", exc_info=True)
            return

        # Check if user is authenticated
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            logger.warning(f"WebSocket connection rejected: unauthenticated user for workspace {self.workspace_key}")
            await self._reject(WS_CLOSE_POLICY_VIOLATION)
            return

        # Verify user is a member of this workspace
        is_member = await self._check_workspace_membership(user, self.workspace_key)
        if not is_member:
            user_id = user.id  # type: ignore[attr-defined]
            logger.warning(
                f"WebSocket connection rejected: user {user_id} is not a member of workspace {self.workspace_key}"
            )
            await self._reject(WS_CLOSE_POLICY_VIOLATION)
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
            await self._reject(WS_CLOSE_SERVICE_RESTART)
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
            data = event["data"]
        except KeyError:
            # A producer sent an event without a data key. That is a bug in the
            # caller rather than a transport failure, so it is worth a real log
            # line instead of the debug the disconnect cases get.
            logger.warning(f"Dropped a workspace_message with no data payload: {event!r}")
            return

        # Deliberately narrow. A payload that will not serialise raises from
        # this same call, and swallowing that logged one debug line and dropped
        # the broadcast to every socket in the workspace, for every broadcast,
        # until someone noticed the UI had quietly stopped updating. That is a
        # bug in the producer and it should be as loud as any other.
        try:
            await self.send_json(data)
        except _SOCKET_GONE:
            logger.debug("workspace_message send failed; socket likely gone", exc_info=True)
        except RuntimeError as exc:
            if not _is_socket_closed(exc):
                raise
            logger.debug("workspace_message send failed; socket already closed", exc_info=True)
