"""
Tests for WebSocket consumers.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sbomify.apps.core.consumers import (
    WS_CLOSE_POLICY_VIOLATION,
    WS_CLOSE_SERVICE_RESTART,
    WorkspaceConsumer,
)


class TestWorkspaceConsumer:
    """Tests for the WorkspaceConsumer."""

    @pytest.fixture
    def consumer(self):
        """Create a consumer instance for testing."""
        return WorkspaceConsumer()

    @pytest.fixture
    def mock_channel_layer(self):
        """Create a mock channel layer."""
        layer = MagicMock()
        layer.group_add = AsyncMock()
        layer.group_discard = AsyncMock()
        layer.group_send = AsyncMock()
        return layer

    @pytest.mark.asyncio
    async def test_connect_unauthenticated_user_rejected(self, consumer, mock_channel_layer):
        """Test that unauthenticated users are rejected."""
        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": None,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()

        await consumer.connect()

        consumer.close.assert_called_once_with(code=WS_CLOSE_POLICY_VIOLATION)
        # Accepted first so the code above can reach the client at all: a close
        # before the handshake completes is an HTTP 403 that carries no code.
        consumer.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_anonymous_user_rejected(self, consumer, mock_channel_layer):
        """Test that anonymous users are rejected."""
        mock_user = MagicMock()
        mock_user.is_authenticated = False

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()

        await consumer.connect()

        consumer.close.assert_called_once_with(code=WS_CLOSE_POLICY_VIOLATION)
        # Accepted first so the code above can reach the client at all: a close
        # before the handshake completes is an HTTP 403 that carries no code.
        consumer.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_authenticated_user_accepted(self, consumer, mock_channel_layer):
        """Test that authenticated workspace members can connect."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 123

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        # Mock the membership check to return True
        consumer._check_workspace_membership = AsyncMock(return_value=True)

        await consumer.connect()

        consumer.accept.assert_called_once()
        consumer.close.assert_not_called()
        mock_channel_layer.group_add.assert_called_once_with("workspace_test-workspace", "test-channel")

    @pytest.mark.asyncio
    async def test_connect_non_member_rejected(self, consumer, mock_channel_layer):
        """Test that authenticated users who are not workspace members are rejected."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 123

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        # Mock the membership check to return False
        consumer._check_workspace_membership = AsyncMock(return_value=False)

        await consumer.connect()

        consumer.close.assert_called_once_with(code=WS_CLOSE_POLICY_VIOLATION)
        # Accepted first so the code above can reach the client at all: a close
        # before the handshake completes is an HTTP 403 that carries no code.
        consumer.accept.assert_awaited_once()
        mock_channel_layer.group_add.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_sets_workspace_key_and_group_name(self, consumer, mock_channel_layer):
        """Test that connect sets the workspace_key and group_name."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 123

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "my-team-key"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.accept = AsyncMock()
        consumer._check_workspace_membership = AsyncMock(return_value=True)

        await consumer.connect()

        assert consumer.workspace_key == "my-team-key"
        assert consumer.group_name == "workspace_my-team-key"

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_group(self, consumer, mock_channel_layer):
        """Test that disconnect removes the channel from the group."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 123

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.group_name = "workspace_test-workspace"

        await consumer.disconnect(1000)

        mock_channel_layer.group_discard.assert_called_once_with("workspace_test-workspace", "test-channel")

    @pytest.mark.asyncio
    async def test_disconnect_without_group_name(self, consumer, mock_channel_layer):
        """Test that disconnect handles missing group_name gracefully."""
        mock_user = MagicMock()
        mock_user.is_authenticated = False

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        # group_name not set (connection was rejected)

        # Should not raise an exception
        await consumer.disconnect(1006)

        # group_discard should not be called since there's no group_name
        mock_channel_layer.group_discard.assert_not_called()

    @pytest.mark.asyncio
    async def test_workspace_message_sends_data(self, consumer, mock_channel_layer):
        """Test that workspace_message sends data to the client."""
        consumer.send_json = AsyncMock()

        event = {
            "type": "workspace_message",
            "data": {
                "type": "sbom_uploaded",
                "sbom_id": "123",
                "name": "test.json",
            },
        }

        await consumer.workspace_message(event)

        consumer.send_json.assert_called_once_with(event["data"])

    @pytest.mark.asyncio
    async def test_workspace_message_different_event_types(self, consumer):
        """Test workspace_message handles different event types."""
        consumer.send_json = AsyncMock()

        event_types = [
            {"type": "sbom_uploaded", "sbom_id": "123"},
            {"type": "sbom_deleted", "sbom_id": "456"},
            {"type": "document_uploaded", "document_id": "789"},
            {"type": "scan_complete", "sbom_id": "123", "status": "completed"},
            {"type": "assessment_complete", "sbom_id": "123", "plugin_name": "checksum"},
            {"type": "notification", "message": "Hello!"},
        ]

        for data in event_types:
            consumer.send_json.reset_mock()
            event = {"type": "workspace_message", "data": data}
            await consumer.workspace_message(event)
            consumer.send_json.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_receive_json_logs_unexpected_message(self, consumer):
        """Test that receive_json logs unexpected client messages."""
        with patch("sbomify.apps.core.consumers.logger") as mock_logger:
            await consumer.receive_json({"action": "ping"})
            mock_logger.debug.assert_called()


class TestWorkspaceConsumerGroupBroadcast:
    """Tests for group broadcast functionality."""

    @pytest.mark.asyncio
    async def test_group_name_format(self):
        """Test that group names are formatted correctly."""
        consumer = WorkspaceConsumer()
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 1

        mock_channel_layer = MagicMock()
        mock_channel_layer.group_add = AsyncMock()

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "abc-123-def"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.accept = AsyncMock()
        consumer._check_workspace_membership = AsyncMock(return_value=True)

        await consumer.connect()

        # Verify the group name format
        assert consumer.group_name == "workspace_abc-123-def"
        mock_channel_layer.group_add.assert_called_with("workspace_abc-123-def", "test-channel")


class TestBrokerOutageHandling:
    """A Redis restart must produce an orderly 1012 close, not an ASGI traceback."""

    @pytest.fixture
    def consumer(self):
        return WorkspaceConsumer()

    def _authenticated_scope(self, consumer):
        user = MagicMock()
        user.is_authenticated = True
        user.id = 7
        consumer.scope = {"url_route": {"kwargs": {"workspace_key": "ws-key"}}, "user": user}
        consumer.channel_name = "chan"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()

    @pytest.mark.asyncio
    async def test_group_add_failure_closes_with_service_restart(self, consumer):
        self._authenticated_scope(consumer)
        layer = MagicMock()
        layer.group_add = AsyncMock(side_effect=ConnectionError("reset by peer"))
        consumer.channel_layer = layer

        with patch.object(WorkspaceConsumer, "_check_workspace_membership", AsyncMock(return_value=True)):
            await consumer.connect()

        consumer.close.assert_called_once_with(code=WS_CLOSE_SERVICE_RESTART)
        # Accepted first, deliberately: a close sent before the handshake
        # completes is an HTTP 403 refusal that carries no code at all, so the
        # code asserted above would never have reached the client.
        consumer.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_accept_failure_joins_no_group(self, consumer):
        """A socket that never opened must not leave a membership behind.

        With the accept moved ahead of the join this is structural rather than
        cleaned up after the fact: there is nothing to discard because nothing
        was ever joined.
        """
        self._authenticated_scope(consumer)
        layer = MagicMock()
        layer.group_add = AsyncMock()
        layer.group_discard = AsyncMock()
        consumer.channel_layer = layer
        consumer.accept = AsyncMock(side_effect=ConnectionError("reset by peer"))

        with patch.object(WorkspaceConsumer, "_check_workspace_membership", AsyncMock(return_value=True)):
            await consumer.connect()

        layer.group_add.assert_not_awaited()
        layer.group_discard.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_accept_failure_does_not_raise(self, consumer):
        """Whatever killed the accept is usually the broker, and an exception
        escaping connect() is what uvicorn logs as "Exception in ASGI
        application" — one stack per socket, which is the noise this whole
        class exists to prevent."""
        self._authenticated_scope(consumer)
        layer = MagicMock()
        layer.group_add = AsyncMock()
        consumer.channel_layer = layer
        consumer.accept = AsyncMock(side_effect=ConnectionError("reset by peer"))

        with patch.object(WorkspaceConsumer, "_check_workspace_membership", AsyncMock(return_value=True)):
            await consumer.connect()  # must not raise

    @pytest.mark.asyncio
    async def test_disconnect_swallows_a_dead_broker(self, consumer):
        consumer.scope = {"user": None}
        consumer.group_name = "workspace_ws-key"
        consumer.channel_name = "chan"
        layer = MagicMock()
        layer.group_discard = AsyncMock(side_effect=ConnectionError("reset by peer"))
        consumer.channel_layer = layer

        await consumer.disconnect(1006)


class TestBroadcastResilience:
    """A broadcast fans out to every channel in the group, and a socket may be
    gone by the time its copy arrives. An exception escaping the handler is what
    uvicorn logs as "Exception in ASGI application"."""

    @pytest.fixture
    def consumer(self):
        return WorkspaceConsumer()

    @pytest.mark.asyncio
    async def test_a_dead_socket_does_not_raise_into_the_asgi_server(self, consumer):
        consumer.send_json = AsyncMock(side_effect=ConnectionError("reset by peer"))

        await consumer.workspace_message({"type": "workspace_message", "data": {"type": "sbom_uploaded"}})

        consumer.send_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_closed_socket_does_not_raise_either(self, consumer):
        """Channels raises its own error once the socket has been closed."""
        consumer.send_json = AsyncMock(side_effect=RuntimeError("Cannot call send once a close message has been sent"))

        await consumer.workspace_message({"type": "workspace_message", "data": {"x": 1}})

        # Not raising is only half the claim: a handler that quietly stopped
        # sending would pass on that alone.
        consumer.send_json.assert_awaited_once_with({"x": 1})

    @pytest.mark.asyncio
    async def test_a_payload_that_will_not_serialise_is_not_swallowed(self, consumer):
        """The half that must stay loud.

        A non-serialisable payload raises from the same call a dead socket does,
        so catching everything here dropped the broadcast to every socket in the
        workspace, every time, and said so in one debug line. It is a producer
        bug, and the only way it gets fixed is by being visible.
        """
        consumer.send_json = AsyncMock(side_effect=TypeError("Object of type datetime is not JSON serializable"))

        with pytest.raises(TypeError):
            await consumer.workspace_message({"type": "workspace_message", "data": {"when": object()}})

    @pytest.mark.asyncio
    async def test_a_recursion_error_is_not_mistaken_for_a_closed_socket(self, consumer):
        """``RecursionError`` subclasses ``RuntimeError``.

        A payload nested deeply enough makes ``json.dumps`` raise it from the
        same call Channels raises a plain ``RuntimeError`` from, so matching the
        base class would swallow it and put the silent drop straight back.
        """
        consumer.send_json = AsyncMock(side_effect=RecursionError("maximum recursion depth exceeded"))

        with pytest.raises(RecursionError):
            await consumer.workspace_message({"type": "workspace_message", "data": {"deep": {}}})

    @pytest.mark.asyncio
    async def test_a_not_implemented_error_is_not_either(self, consumer):
        """The other ``RuntimeError`` subclass, and squarely a programmer bug."""
        consumer.send_json = AsyncMock(side_effect=NotImplementedError("encode_json"))

        with pytest.raises(NotImplementedError):
            await consumer.workspace_message({"type": "workspace_message", "data": {"x": 1}})

    @pytest.mark.asyncio
    async def test_an_event_with_no_data_is_dropped_not_raised(self, consumer):
        """A producer bug, not a transport failure — it must not take the socket
        down with it, and it is the one case worth a warning."""
        consumer.send_json = AsyncMock()

        await consumer.workspace_message({"type": "workspace_message"})

        consumer.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_live_socket_still_receives_the_payload(self, consumer):
        consumer.send_json = AsyncMock()
        payload = {"type": "scan_complete", "sbom_id": "123"}

        await consumer.workspace_message({"type": "workspace_message", "data": payload})

        consumer.send_json.assert_awaited_once_with(payload)


@pytest.mark.django_db
class TestWorkspaceMembershipCheck:
    """The real membership check, not a mock.

    Every other test in this file replaces ``_check_workspace_membership`` with
    an AsyncMock, so the method that actually decides who may listen was never
    exercised — which is how it went unnoticed that it admitted anyone holding a
    Member row, guests included.
    """

    def _check(self, user, workspace_key):
        # The undecorated function. Driving database_sync_to_async from a sync
        # test closes the connection under the test transaction; the decision
        # being tested is in the body, not the threading wrapper.
        raw = WorkspaceConsumer.__dict__["_check_workspace_membership"].func
        return raw(WorkspaceConsumer(), user, workspace_key)

    def _user(self, django_user_model, name):
        return django_user_model.objects.create_user(
            username=name, email=f"{name}@test.com", password="password"
        )

    def test_a_guest_cannot_listen_to_internal_workspace_events(self, django_user_model):
        """A guest is external. Holding a Member row is not permission to listen.

        The row exists as an ACL anchor for the trust-center access-request and
        NDA machinery; treating it as workspace membership handed an outside
        visitor the internal event feed.
        """
        from sbomify.apps.teams.models import Member, Team

        team = Team.objects.create(name="Socket Workspace")
        guest = self._user(django_user_model, "socket-guest")
        Member.objects.create(user=guest, team=team, role="guest")

        assert self._check(guest, team.key) is False

    def test_internal_roles_can_listen(self, django_user_model):
        from sbomify.apps.teams.models import Member, Team

        team = Team.objects.create(name="Socket Workspace Internal")
        for role in ("owner", "admin", "member"):
            user = self._user(django_user_model, f"socket-{role}")
            Member.objects.create(user=user, team=team, role=role)
            assert self._check(user, team.key) is True, f"{role} should be able to listen"

    def test_a_non_member_cannot_listen(self, django_user_model):
        from sbomify.apps.teams.models import Team

        team = Team.objects.create(name="Socket Workspace Outsider")
        outsider = self._user(django_user_model, "socket-outsider")

        assert self._check(outsider, team.key) is False

    def test_an_unknown_workspace_is_refused(self, django_user_model):
        """No workspace, no listening — and no exception either."""
        outsider = self._user(django_user_model, "socket-nowhere")

        assert self._check(outsider, "does-not-exist") is False
