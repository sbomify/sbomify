"""
Test exception handling in SBOM signal handlers.

This module tests the error handling and resilience of the signal handlers
that trigger NTIA compliance checks and vulnerability scans when SBOMs are created.
"""

import pytest
from unittest.mock import Mock, patch
from django.test import TestCase

from billing.models import BillingPlan
from core.models import User, Component
from teams.models import Team
from sboms.models import SBOM
from sboms.signals import trigger_ntia_compliance_check, trigger_vulnerability_scan


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

        with patch('sboms.signals.logger') as mock_logger:
            # Trigger signals for update (created=False)
            trigger_ntia_compliance_check(sender=SBOM, instance=sbom, created=False)
            trigger_vulnerability_scan(sender=SBOM, instance=sbom, created=False)

            # Verify no logging occurred (handlers should exit early)
            mock_logger.info.assert_not_called()
            mock_logger.error.assert_not_called()

    def test_both_signals_handle_malformed_instance(self):
        """Test both signals handle malformed SBOM instances gracefully."""
        # Create a mock instance that doesn't have the expected attributes
        mock_instance = Mock()
        mock_instance.id = "test-id"
        mock_instance.component = None

        with patch('sboms.signals.logger') as mock_logger:
            # Test NTIA compliance check
            trigger_ntia_compliance_check(sender=SBOM, instance=mock_instance, created=True)

            # Test vulnerability scan
            trigger_vulnerability_scan(sender=SBOM, instance=mock_instance, created=True)

            # Verify both functions logged errors
            self.assertEqual(mock_logger.error.call_count, 2)

    def test_ntia_compliance_with_no_billing_plan(self):
        """Test NTIA compliance check with no billing plan (community users)."""
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=self.component
        )

        with patch('sboms.signals.logger') as mock_logger:
            trigger_ntia_compliance_check(sender=SBOM, instance=sbom, created=True)

            # Should log that NTIA is skipped for community users
            mock_logger.info.assert_called_once()
            args, kwargs = mock_logger.info.call_args
            self.assertIn("Skipping NTIA compliance check", args[0])
            self.assertIn("no billing plan (community)", args[0])

    def test_ntia_compliance_with_business_plan(self):
        """Test NTIA compliance check with business plan."""
        # Set up team with business plan
        business_plan = BillingPlan.objects.create(
            key="business",
            name="Business Plan"
        )
        self.team.billing_plan = business_plan.key
        self.team.save()

        sbom = SBOM.objects.create(
            name="test-sbom",
            component=self.component
        )

        with patch('sbomify.tasks.check_sbom_ntia_compliance') as mock_task:
            with patch('sboms.signals.logger') as mock_logger:
                trigger_ntia_compliance_check(sender=SBOM, instance=sbom, created=True)

                # Should trigger the task
                mock_task.send_with_options.assert_called_once_with(
                    args=[sbom.id],
                    delay=60000
                )

                # Should log that NTIA compliance is triggered
                mock_logger.info.assert_called_once()
                args, kwargs = mock_logger.info.call_args
                self.assertIn("Triggering NTIA compliance check", args[0])

    def test_vulnerability_scan_always_triggered(self):
        """Test vulnerability scan is always triggered regardless of plan."""
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=self.component
        )

        with patch('sbomify.tasks.scan_sbom_for_vulnerabilities_unified') as mock_task:
            with patch('sboms.signals.logger') as mock_logger:
                trigger_vulnerability_scan(sender=SBOM, instance=sbom, created=True)

                # Should trigger the task
                mock_task.send_with_options.assert_called_once_with(
                    args=[sbom.id],
                    delay=90000
                )

                # Should log that vulnerability scan is triggered
                mock_logger.info.assert_called_once()
                args, kwargs = mock_logger.info.call_args
                self.assertIn("Triggering vulnerability scan", args[0])

    def test_vulnerability_scan_with_business_plan(self):
        """Test vulnerability scan with business plan logs plan info."""
        # Set up team with business plan
        business_plan = BillingPlan.objects.create(
            key="business",
            name="Business Plan"
        )
        self.team.billing_plan = business_plan.key
        self.team.save()

        sbom = SBOM.objects.create(
            name="test-sbom",
            component=self.component
        )

        with patch('sbomify.tasks.scan_sbom_for_vulnerabilities_unified') as mock_task:
            with patch('sboms.signals.logger') as mock_logger:
                trigger_vulnerability_scan(sender=SBOM, instance=sbom, created=True)

                # Should trigger the task
                mock_task.send_with_options.assert_called_once_with(
                    args=[sbom.id],
                    delay=90000
                )

                # Should log with business plan info
                mock_logger.info.assert_called_once()
                args, kwargs = mock_logger.info.call_args
                self.assertIn("'business' plan", args[0])

    def test_vulnerability_scan_with_nonexistent_plan(self):
        """Test vulnerability scan handles nonexistent billing plan gracefully."""
        self.team.billing_plan = "nonexistent-plan"
        self.team.save()

        sbom = SBOM.objects.create(
            name="test-sbom",
            component=self.component
        )

        with patch('sbomify.tasks.scan_sbom_for_vulnerabilities_unified') as mock_task:
            with patch('sboms.signals.logger') as mock_logger:
                trigger_vulnerability_scan(sender=SBOM, instance=sbom, created=True)

                # Should still trigger the task
                mock_task.send_with_options.assert_called_once_with(
                    args=[sbom.id],
                    delay=90000
                )

                # Should log with unknown plan info
                mock_logger.info.assert_called_once()
                args, kwargs = mock_logger.info.call_args
                self.assertIn("unknown plan 'nonexistent-plan'", args[0])


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
        """Test that both signals are triggered when an SBOM is created."""
        with patch('sbomify.tasks.scan_sbom_for_vulnerabilities_unified') as mock_vuln_task:
            with patch('sboms.signals.logger') as mock_logger:
                # Create SBOM - this should trigger both signals
                sbom = SBOM.objects.create(
                    name="test-sbom",
                    component=self.component
                )

                # Verify vulnerability scan was triggered
                mock_vuln_task.send_with_options.assert_called_once_with(
                    args=[sbom.id],
                    delay=90000
                )

                # Verify logging occurred for both signals
                info_calls = [str(call) for call in mock_logger.info.call_args_list]
                vuln_calls = [call for call in info_calls if 'vulnerability scan' in call]
                ntia_calls = [call for call in info_calls if 'NTIA compliance check' in call]

                self.assertTrue(len(vuln_calls) > 0)
                self.assertTrue(len(ntia_calls) > 0)  # Should skip NTIA for community

    def test_exception_handling_resilience(self):
        """Test that exceptions in signal handlers don't break SBOM creation."""
        # Create a mock SBOM instance that will cause an exception when accessing component.team
        mock_instance = Mock()
        mock_instance.id = "test-id"
        mock_instance.component.team.side_effect = AttributeError("Simulated error")

        with patch('sboms.signals.logger') as mock_logger:
            # This should not raise an exception despite the AttributeError
            trigger_vulnerability_scan(sender=SBOM, instance=mock_instance, created=True)

            # Verify error was logged
            error_calls = [str(call) for call in mock_logger.error.call_args_list]
            vuln_error_calls = [call for call in error_calls if 'vulnerability scan' in call]
            self.assertTrue(len(vuln_error_calls) > 0)