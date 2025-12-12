"""Tests for the onboarding wizard single-step flow."""

import pytest
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.models import ContactProfile


@pytest.mark.django_db
class TestOnboardingWizard:
    """Tests for the single-step SBOM identity onboarding wizard."""

    def test_wizard_requires_login(self, client: Client) -> None:
        """Test that the onboarding wizard requires authentication."""
        response = client.get(reverse("teams:onboarding_wizard"))
        assert response.status_code == 302
        assert response.url.startswith(settings.LOGIN_URL)

    def test_wizard_shows_setup_form(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that GET request shows the setup form with pre-filled email."""
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.get(reverse("teams:onboarding_wizard"))

        assert response.status_code == 200
        assert response.context["current_step"] == "setup"
        assert "form" in response.context

        # Check email is pre-filled
        form = response.context["form"]
        assert form.initial.get("email") == sample_user.email

    def test_successful_onboarding_flow(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test the complete successful single-step onboarding flow."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        original_team_name = team.name

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
            "name": original_team_name,
        }
        session.save()

        # Submit company info
        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Acme Corporation",
                "email": "security@acme.com",
                "website": "https://acme.com",
            },
        )

        # Should redirect to complete step
        assert response.status_code == 302
        assert "step=complete" in response.url

        # Check success message
        messages = list(get_messages(response.wsgi_request))
        assert any("SBOM identity has been set up" in str(m) for m in messages)

        # Verify workspace was renamed
        team.refresh_from_db()
        assert team.name == "Acme Corporation's Workspace"
        assert team.has_completed_wizard is True

    def test_contact_profile_created(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that ContactProfile is created with company=supplier=vendor and is_default=True."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Test Company",
                "email": "contact@test.com",
                "website": "https://test.com",
            },
        )

        assert response.status_code == 302

        # Verify ContactProfile was created correctly
        profile = ContactProfile.objects.filter(team=team).first()
        assert profile is not None
        assert profile.name == "Default"
        assert profile.company == "Test Company"
        assert profile.supplier_name == "Test Company"
        assert profile.vendor == "Test Company"
        assert profile.email == "contact@test.com"
        assert profile.website_urls == ["https://test.com"]
        assert profile.is_default is True

    def test_contact_profile_uses_user_email_as_fallback(
        self, client: Client, sample_user, sample_team_with_owner_member
    ) -> None:
        """Test that ContactProfile uses user email when not provided in form."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # Submit without email
        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Fallback Email Test",
            },
        )

        assert response.status_code == 302

        profile = ContactProfile.objects.filter(team=team).first()
        assert profile is not None
        assert profile.email == sample_user.email

    def test_product_project_component_auto_created(
        self, client: Client, sample_user, sample_team_with_owner_member
    ) -> None:
        """Test that Product, Project, and Component are auto-created with correct hierarchy."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Hierarchy Test Corp",
            },
        )

        assert response.status_code == 302

        # Verify Product
        product = Product.objects.filter(team=team, name="Hierarchy Test Corp").first()
        assert product is not None

        # Verify Project
        project = Project.objects.filter(team=team, name="Main Project").first()
        assert project is not None

        # Verify Component with SBOM type
        component = Component.objects.filter(team=team, name="Main Component").first()
        assert component is not None
        assert component.component_type == Component.ComponentType.SBOM

        # Verify hierarchy: product -> project -> component
        assert project in product.projects.all()
        assert component in project.components.all()

    def test_component_has_sbom_type(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that auto-created component has component_type=SBOM."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "SBOM Type Test",
            },
        )

        assert response.status_code == 302

        component = Component.objects.filter(team=team).first()
        assert component is not None
        assert component.component_type == Component.ComponentType.SBOM

    def test_keycloak_metadata_in_component(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that Keycloak user metadata is properly used when creating a component."""
        # Create Keycloak social auth record with metadata
        SocialAccount.objects.create(
            user=sample_user,
            provider="keycloak",
            extra_data={
                "user_metadata": {
                    "company": "Keycloak Corp",
                    "supplier_url": "https://keycloak.example.com",
                }
            },
        )

        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Keycloak Test",
            },
        )

        assert response.status_code == 302

        # Verify component has Keycloak metadata
        component = Component.objects.filter(team=team).first()
        assert component is not None
        assert component.metadata.get("supplier", {}).get("name") == "Keycloak Corp"
        assert component.metadata.get("supplier", {}).get("url") == ["https://keycloak.example.com"]

    def test_complete_step_shows_summary(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that completion step shows created entities summary."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # First submit the form
        client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Summary Test Inc",
            },
        )

        # Now access the complete step
        response = client.get(reverse("teams:onboarding_wizard") + "?step=complete")

        assert response.status_code == 200
        assert response.context["current_step"] == "complete"
        assert response.context["company_name"] == "Summary Test Inc"
        assert response.context["component_id"] is not None

    def test_session_updated_after_completion(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that session is properly updated after wizard completion."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
            "name": team.name,
        }
        session.save()

        client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Session Test",
            },
        )

        # Check session was updated
        session = client.session
        assert session["current_team"]["has_completed_wizard"] is True
        assert session["current_team"]["name"] == "Session Test's Workspace"

    def test_company_name_required(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that company_name is required."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # Submit without company_name
        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "email": "test@test.com",
            },
        )

        # Should stay on the same page with form errors
        assert response.status_code == 200
        assert response.context["form"].errors.get("company_name") is not None

    def test_website_is_optional(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that website field is optional."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # Submit without website
        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "No Website Corp",
            },
        )

        assert response.status_code == 302

        profile = ContactProfile.objects.filter(team=team).first()
        assert profile is not None
        assert profile.website_urls == []

    def test_invalid_website_url(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that invalid website URL is rejected."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Invalid URL Test",
                "website": "not-a-valid-url",
            },
        )

        # Should stay on same page with form errors
        assert response.status_code == 200
        assert response.context["form"].errors.get("website") is not None
