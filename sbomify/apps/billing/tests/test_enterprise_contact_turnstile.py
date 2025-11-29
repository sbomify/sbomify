
import pytest
from unittest.mock import MagicMock
from django.urls import reverse
from django.conf import settings
from sbomify.apps.billing.tests.fixtures import *

@pytest.mark.django_db
class TestEnterpriseContactTurnstile:
    def test_select_plan_redirects_to_contact(self, client, sample_user, team_with_business_plan, enterprise_plan):
        """Test that selecting enterprise plan redirects to the contact view."""
        client.force_login(sample_user)
        
        response = client.post(
            reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}),
            {"plan": "enterprise"}
        )
        
        assert response.status_code == 302
        assert response.url == reverse("billing:enterprise_contact")

    def test_authenticated_contact_renders_turnstile(self, client, sample_user):
        """Test that the authenticated enterprise contact view renders the Turnstile widget."""
        client.force_login(sample_user)
        
        with pytest.MonkeyPatch.context() as m:
            m.setattr(settings, "TURNSTILE_SITE_KEY", "test-site-key")
            m.setattr(settings, "DEBUG", False)
            
            response = client.get(reverse("billing:enterprise_contact"))
            
            assert response.status_code == 200
            # Check if the widget div is present
            assert 'class="cf-turnstile"' in response.content.decode()

    def test_authenticated_submission_requires_turnstile(self, client, sample_user):
        """
        Test that the authenticated form REJECTS submission WITHOUT a valid Turnstile token.
        """
        client.force_login(sample_user)
        
        form_data = {
            "company_name": "Test Co",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "company_size": "startup",
            "primary_use_case": "compliance",
            "message": "This is a test message that is long enough.",
            # No cf_turnstile_response provided
        }
        
        with pytest.MonkeyPatch.context() as m:
            m.setattr(settings, "TURNSTILE_SITE_KEY", "test-site-key")
            m.setattr(settings, "DEBUG", False)
            
            url = reverse("billing:enterprise_contact")
            
            # We need to mock the async task so we don't actually try to send email/dramatiq
            with pytest.MonkeyPatch.context() as mp:
                mock_task = MagicMock()
                mp.setattr("sbomify.apps.billing.views.send_enterprise_inquiry_email", mock_task)
                
                response = client.post(url, form_data)
                
                # If validation is enforced, it should render the page again (status 200) with errors
                assert response.status_code == 200
                assert "Please complete the security verification" in response.content.decode() or "This field is required" in response.content.decode()
                
                # And the task should NOT have been called
                assert not mock_task.send.called
