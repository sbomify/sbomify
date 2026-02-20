"""
Test exception handling in SBOM signal handlers.

This module tests the error handling and resilience of the signal handlers
that trigger plugin assessments when SBOMs are created.
"""

from unittest.mock import Mock, patch
from django.test import TestCase

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.models import User, Component
from sbomify.apps.teams.models import Team
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.signals import trigger_plugin_assessments


class SignalExceptionHandlingTests(TestCase):
    """Test exception handling in SBOM signal handlers."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.team = Team.objects.create(
            name="Test Team"
        )
        self.component = Component.objects.create(
            name="test-component",
            team=self.team
        )

    def test_signal_handlers_not_triggered_for_updates(self):
        """Test that signal handlers are not triggered for SBOM updates."""
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=self.component
        )

        with patch('sbomify.apps.sboms.signals.logger') as mock_logger:
            # Trigger signals for update (created=False)
            trigger_plugin_assessments(sender=SBOM, instance=sbom, created=False)

            # Verify no logging occurred (handlers should exit early)
            mock_logger.info.assert_not_called()
            mock_logger.error.assert_not_called()

    def test_both_signals_handle_malformed_instance(self):
        """Test signal handles malformed SBOM instances gracefully."""
        # Create a mock instance that doesn't have the expected attributes
        mock_instance = Mock()
        mock_instance.id = "test-id"
        mock_instance.component = None

        with patch('sbomify.apps.sboms.signals.logger') as mock_logger:
            # Test plugin assessments
            trigger_plugin_assessments(sender=SBOM, instance=mock_instance, created=True)

            # Signal should log a debug message and return early for AttributeError
            mock_logger.debug.assert_called_once()
            mock_logger.error.assert_not_called()

    def test_plugin_assessments_triggered(self):
        """Test plugin assessments are triggered for new SBOMs."""
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=self.component
        )

        with patch('sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom') as mock_enqueue:
            with patch('sbomify.apps.sboms.signals.logger') as mock_logger:
                trigger_plugin_assessments(sender=SBOM, instance=sbom, created=True)

                # Should trigger the plugin assessment enqueue function
                mock_enqueue.assert_called_once()
                call_kwargs = mock_enqueue.call_args[1]
                self.assertEqual(call_kwargs['sbom_id'], sbom.id)
                self.assertEqual(call_kwargs['team_id'], self.team.id)

                # Should log that plugin assessments are triggered
                mock_logger.info.assert_called()


class SignalIntegrationTests(TestCase):
    """Integration tests for signal handlers with real Django signals."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.team = Team.objects.create(
            name="Test Team"
        )
        self.component = Component.objects.create(
            name="test-component",
            team=self.team
        )

    def test_signals_triggered_on_sbom_creation(self):
        """Test that plugin assessment signal is triggered when an SBOM is created."""
        with patch('sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom') as mock_plugin_enqueue:
            with patch('sbomify.apps.sboms.signals.logger'):
                # Create SBOM - this should trigger plugin assessments
                sbom = SBOM.objects.create(
                    name="test-sbom",
                    component=self.component
                )

                # Verify plugin assessments were triggered
                mock_plugin_enqueue.assert_called_once()
