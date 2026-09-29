"""Tests for Keycloak utility functions."""

from unittest.mock import MagicMock, patch

import pytest


class TestKeycloakDisableUser:
    @pytest.mark.django_db
    def test_disable_user_calls_update(self):
        """disable_user calls admin_client.update_user with enabled=False."""
        with patch("sbomify.apps.core.keycloak_utils.KeycloakAdmin") as MockAdmin:
            mock_admin = MagicMock()
            MockAdmin.return_value = mock_admin
            mock_admin.token = {"access_token": "fake"}

            with patch("sbomify.apps.core.keycloak_utils.KeycloakOpenID"):
                from sbomify.apps.core.keycloak_utils import KeycloakManager

                manager = KeycloakManager()
                manager.admin_client = mock_admin

                result = manager.disable_user("user-123")
                assert result is True
                mock_admin.update_user.assert_called_once_with("user-123", {"enabled": False})

    @pytest.mark.django_db
    def test_disable_user_returns_false_on_error(self):
        """disable_user returns False when Keycloak call fails."""
        with patch("sbomify.apps.core.keycloak_utils.KeycloakAdmin") as MockAdmin:
            mock_admin = MagicMock()
            MockAdmin.return_value = mock_admin
            mock_admin.token = {"access_token": "fake"}
            mock_admin.update_user.side_effect = Exception("Connection refused")

            with patch("sbomify.apps.core.keycloak_utils.KeycloakOpenID"):
                from sbomify.apps.core.keycloak_utils import KeycloakManager

                manager = KeycloakManager()
                manager.admin_client = mock_admin

                result = manager.disable_user("user-456")
                assert result is False


class TestKeycloakDeleteUser:
    @pytest.mark.django_db
    def test_delete_user_calls_admin_delete(self):
        """delete_user calls admin_client.delete_user."""
        with patch("sbomify.apps.core.keycloak_utils.KeycloakAdmin") as MockAdmin:
            mock_admin = MagicMock()
            MockAdmin.return_value = mock_admin
            mock_admin.token = {"access_token": "fake"}

            with patch("sbomify.apps.core.keycloak_utils.KeycloakOpenID"):
                from sbomify.apps.core.keycloak_utils import KeycloakManager

                manager = KeycloakManager()
                manager.admin_client = mock_admin

                result = manager.delete_user("user-789")
                assert result is True
                mock_admin.delete_user.assert_called_once_with("user-789")

    @pytest.mark.django_db
    def test_delete_user_returns_false_on_error(self):
        """delete_user returns False when Keycloak call fails."""
        with patch("sbomify.apps.core.keycloak_utils.KeycloakAdmin") as MockAdmin:
            mock_admin = MagicMock()
            MockAdmin.return_value = mock_admin
            mock_admin.token = {"access_token": "fake"}
            mock_admin.delete_user.side_effect = Exception("Connection refused")

            with patch("sbomify.apps.core.keycloak_utils.KeycloakOpenID"):
                from sbomify.apps.core.keycloak_utils import KeycloakManager

                manager = KeycloakManager()
                manager.admin_client = mock_admin

                result = manager.delete_user("user-101")
                assert result is False


class TestKeycloakManagerConstruction:
    def test_builds_against_the_installed_python_keycloak(self, settings):
        """No mocks: a KeycloakAdmin attribute the pinned library lacks must fail here.

        Constructing the clients makes no request; the token is fetched on first use.
        """
        from sbomify.apps.core.keycloak_utils import KeycloakManager

        settings.KEYCLOAK_SERVER_URL = "https://keycloak.example.com/"
        settings.KEYCLOAK_REALM = "sbomify"
        settings.KEYCLOAK_ADMIN_USERNAME = "admin"
        settings.KEYCLOAK_ADMIN_PASSWORD = "secret"
        settings.KEYCLOAK_CLIENT_ID = "sbomify"
        settings.KEYCLOAK_CLIENT_SECRET = "client-secret"

        manager = KeycloakManager()

        connection = manager.admin_client.connection
        assert connection.server_url == "https://keycloak.example.com/"
        assert connection.realm_name == "sbomify"
        assert connection.user_realm_name == "master"
        assert connection.username == "admin"
        assert manager.master_admin.connection.realm_name == "master"


class TestKeycloakEventPolling:
    def test_poll_calls_the_installed_get_events(self, settings, mocker):
        """Only the HTTP call is faked, so a keyword the pinned get_events lacks fails here."""
        from requests import Response

        from keycloak.openid_connection import KeycloakOpenIDConnection
        from sbomify.apps.core.keycloak_events import KeycloakEventPoller

        settings.KEYCLOAK_SERVER_URL = "https://keycloak.example.com/"
        settings.KEYCLOAK_REALM = "sbomify"
        settings.KEYCLOAK_ADMIN_USERNAME = "admin"
        settings.KEYCLOAK_ADMIN_PASSWORD = "secret"
        settings.KEYCLOAK_CLIENT_ID = "sbomify"
        settings.KEYCLOAK_CLIENT_SECRET = "client-secret"

        response = Response()
        response.status_code = 200
        response._content = b'[{"type": "UPDATE_PROFILE", "userId": "u1"}]'
        raw_get = mocker.patch.object(KeycloakOpenIDConnection, "raw_get", return_value=response)

        events = KeycloakEventPoller().poll_events()

        assert events == [{"type": "UPDATE_PROFILE", "userId": "u1"}]
        query = raw_get.call_args.kwargs
        assert "dateFrom" in query
        assert "UPDATE_PROFILE" in query["type"]
