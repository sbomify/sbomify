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
