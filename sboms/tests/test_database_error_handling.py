"""
Tests for database connection error handling in SBOM utilities.
"""

import pytest
from unittest.mock import patch, Mock
from django.db import DatabaseError, OperationalError

from sboms.utils import get_sbom_data, get_sbom_data_bytes, SBOMDataError
from sboms.models import SBOM
from .fixtures import sample_sbom  # noqa: F401


@pytest.mark.django_db
class TestDatabaseErrorHandling:
    """Test database connection error handling in SBOM utilities."""

    def test_get_sbom_data_handles_connection_error(self, sample_sbom):  # noqa: F811
        """Test that get_sbom_data handles database connection errors gracefully."""

        # Mock the SBOM.objects.select_related().get() to raise a connection error
        with patch.object(SBOM.objects, 'select_related') as mock_select_related:
            mock_queryset = Mock()
            mock_select_related.return_value = mock_queryset
            mock_queryset.get.side_effect = OperationalError("server closed the connection unexpectedly")

            # Should raise SBOMDataError with appropriate message
            with pytest.raises(SBOMDataError) as exc_info:
                get_sbom_data(str(sample_sbom.id))

            assert "database connection temporarily unavailable" in str(exc_info.value)
            assert str(sample_sbom.id) in str(exc_info.value)

    def test_get_sbom_data_handles_generic_database_error(self, sample_sbom):  # noqa: F811
        """Test that get_sbom_data handles generic database errors."""

        # Mock the SBOM.objects.select_related().get() to raise a generic database error
        with patch.object(SBOM.objects, 'select_related') as mock_select_related:
            mock_queryset = Mock()
            mock_select_related.return_value = mock_queryset
            mock_queryset.get.side_effect = DatabaseError("database is locked")

            # Should raise SBOMDataError with appropriate message
            with pytest.raises(SBOMDataError) as exc_info:
                get_sbom_data(str(sample_sbom.id))

            assert "database error" in str(exc_info.value)
            assert str(sample_sbom.id) in str(exc_info.value)

    def test_get_sbom_data_bytes_handles_connection_error(self, sample_sbom):  # noqa: F811
        """Test that get_sbom_data_bytes handles database connection errors gracefully."""

        # Mock the SBOM.objects.select_related().get() to raise a connection error
        with patch.object(SBOM.objects, 'select_related') as mock_select_related:
            mock_queryset = Mock()
            mock_select_related.return_value = mock_queryset
            mock_queryset.get.side_effect = OperationalError("connection terminated")

            # Should raise SBOMDataError with appropriate message
            with pytest.raises(SBOMDataError) as exc_info:
                get_sbom_data_bytes(str(sample_sbom.id))

            assert "database connection temporarily unavailable" in str(exc_info.value)
            assert str(sample_sbom.id) in str(exc_info.value)

    def test_get_sbom_data_bytes_handles_generic_database_error(self, sample_sbom):  # noqa: F811
        """Test that get_sbom_data_bytes handles generic database errors."""

        # Mock the SBOM.objects.select_related().get() to raise a generic database error
        with patch.object(SBOM.objects, 'select_related') as mock_select_related:
            mock_queryset = Mock()
            mock_select_related.return_value = mock_queryset
            mock_queryset.get.side_effect = DatabaseError("deadlock detected")

            # Should raise SBOMDataError with appropriate message
            with pytest.raises(SBOMDataError) as exc_info:
                get_sbom_data_bytes(str(sample_sbom.id))

            assert "database error" in str(exc_info.value)
            assert str(sample_sbom.id) in str(exc_info.value)

    def test_connection_error_message_detection(self, sample_sbom):  # noqa: F811
        """Test that connection error messages are properly detected."""

        connection_error_messages = [
            "server closed the connection unexpectedly",
            "connection terminated",
            "connection reset by peer",
            "could not connect to server",
        ]

        for error_msg in connection_error_messages:
            with patch.object(SBOM.objects, 'select_related') as mock_select_related:
                mock_queryset = Mock()
                mock_select_related.return_value = mock_queryset
                mock_queryset.get.side_effect = OperationalError(error_msg)

                with pytest.raises(SBOMDataError) as exc_info:
                    get_sbom_data(str(sample_sbom.id))

                # Should be treated as connection error
                assert "database connection temporarily unavailable" in str(exc_info.value)

    def test_non_connection_database_error_handling(self, sample_sbom):  # noqa: F811
        """Test that non-connection database errors are handled differently."""

        non_connection_errors = [
            "syntax error in SQL",
            "table does not exist",
            "permission denied",
            "disk full",
        ]

        for error_msg in non_connection_errors:
            with patch.object(SBOM.objects, 'select_related') as mock_select_related:
                mock_queryset = Mock()
                mock_select_related.return_value = mock_queryset
                mock_queryset.get.side_effect = DatabaseError(error_msg)

                with pytest.raises(SBOMDataError) as exc_info:
                    get_sbom_data(str(sample_sbom.id))

                # Should be treated as generic database error
                assert "database error" in str(exc_info.value)
                assert "temporarily unavailable" not in str(exc_info.value)

    def test_sbom_does_not_exist_still_works(self):
        """Test that SBOM.DoesNotExist is still handled properly."""

        non_existent_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(SBOMDataError) as exc_info:
            get_sbom_data(non_existent_id)

        assert "not found" in str(exc_info.value)
        assert non_existent_id in str(exc_info.value)

    @patch('sboms.utils.log')
    def test_connection_error_logging(self, mock_log, sample_sbom):  # noqa: F811
        """Test that connection errors are logged appropriately."""

        with patch.object(SBOM.objects, 'select_related') as mock_select_related:
            mock_queryset = Mock()
            mock_select_related.return_value = mock_queryset
            mock_queryset.get.side_effect = OperationalError("server closed the connection unexpectedly")

            with pytest.raises(SBOMDataError):
                get_sbom_data(str(sample_sbom.id))

            # Should log as warning for connection errors
            mock_log.warning.assert_called_once()
            assert "Database connection error" in mock_log.warning.call_args[0][0]
            assert str(sample_sbom.id) in mock_log.warning.call_args[0][0]

    @patch('sboms.utils.log')
    def test_generic_database_error_logging(self, mock_log, sample_sbom):  # noqa: F811
        """Test that generic database errors are logged appropriately."""

        with patch.object(SBOM.objects, 'select_related') as mock_select_related:
            mock_queryset = Mock()
            mock_select_related.return_value = mock_queryset
            mock_queryset.get.side_effect = DatabaseError("syntax error")

            with pytest.raises(SBOMDataError):
                get_sbom_data(str(sample_sbom.id))

            # Should log as error for generic database errors
            mock_log.error.assert_called_once()
            assert "Database error" in mock_log.error.call_args[0][0]
            assert str(sample_sbom.id) in mock_log.error.call_args[0][0]
