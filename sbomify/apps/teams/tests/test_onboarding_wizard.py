"""Tests for the onboarding wizard single-step flow."""

import pytest
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.models import ContactProfile



@pytest.fixture
def community_plan() -> BillingPlan:
    """Free community plan fixture."""
    plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan for small teams",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "stripe_product_id": None,
            "stripe_price_monthly_id": None,
            "stripe_price_annual_id": None,
        }
    )
    return plan


@pytest.mark.django_db
class TestDashboardRedirectToOnboarding:
    """Tests for dashboard redirect to onboarding wizard when not completed."""

    def test_dashboard_redirects_when_wizard_not_completed(
        self, client: Client, sample_user, sample_team_with_owner_member
    ) -> None:
        """Test that dashboard redirects to onboarding wizard when has_completed_wizard is False."""
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.get(reverse("core:dashboard"))

        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

    def test_dashboard_renders_when_wizard_completed(
        self, client: Client, sample_user, sample_team_with_owner_member
    ) -> None:
        """Test that dashboard renders normally when has_completed_wizard is True."""
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()

        response = client.get(reverse("core:dashboard"))

        assert response.status_code == 200
        assert "dashboard" in response.templates[0].name.lower()

    def test_dashboard_defaults_to_completed_when_key_missing(
        self, client: Client, sample_user, sample_team_with_owner_member
    ) -> None:
        """Test that dashboard renders normally when has_completed_wizard key is missing (defaults to True)."""
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            # Note: has_completed_wizard is intentionally missing
        }
        session.save()

        response = client.get(reverse("core:dashboard"))

        # Should NOT redirect - defaults to True (completed)
        assert response.status_code == 200


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

    def test_successful_onboarding_flow(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
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
                "contact_name": "Jane Smith",
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

    def test_contact_profile_created(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
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
                "contact_name": "John Doe",
                "email": "contact@test.com",
                "website": "https://test.com",
            },
        )

        assert response.status_code == 302

        # Verify ContactProfile was created correctly (3-level hierarchy)
        profile = ContactProfile.objects.filter(team=team).first()
        assert profile is not None
        assert profile.name == "Default"
        assert profile.is_default is True

        # Entity should have the company details
        entity = profile.entities.first()
        assert entity is not None
        assert entity.name == "Test Company"  # Entity name is the company name
        assert entity.email == "contact@test.com"
        assert entity.website_urls == ["https://test.com"]
        assert entity.is_manufacturer is True
        assert entity.is_supplier is True

        # Verify ContactProfileContact was created for NTIA compliance (linked to entity)
        contact = entity.contacts.first()
        assert contact is not None
        assert contact.name == "John Doe"
        assert contact.email == "contact@test.com"

        # Verify AuthorContact was created (CycloneDX 1.7)
        author = profile.authors.first()
        assert author is not None
        assert author.name == "John Doe"
        assert author.email == "contact@test.com"

    def test_contact_profile_uses_user_email_as_fallback(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
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
                "contact_name": "Test User",
            },
        )

        assert response.status_code == 302

        profile = ContactProfile.objects.filter(team=team).first()
        assert profile is not None
        # Email is now on the entity, not the profile
        entity = profile.entities.first()
        assert entity is not None
        assert entity.email == sample_user.email

    def test_product_project_component_auto_created(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
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
                "contact_name": "Test Contact",
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

    def test_component_has_sbom_type(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
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
                "contact_name": "SBOM Tester",
            },
        )

        assert response.status_code == 302

        component = Component.objects.filter(team=team).first()
        assert component is not None
        assert component.component_type == Component.ComponentType.SBOM

    def test_keycloak_metadata_in_component(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
        """Test that Keycloak user metadata is properly used when creating a component."""
        # Create Keycloak social auth record with metadata (created for side effects only)
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
                "contact_name": "Keycloak Tester",
            },
        )

        assert response.status_code == 302

        # Verify component has Keycloak metadata
        component = Component.objects.filter(team=team).first()
        assert component is not None
        assert component.metadata.get("supplier", {}).get("name") == "Keycloak Corp"
        assert component.metadata.get("supplier", {}).get("url") == ["https://keycloak.example.com"]

    def test_complete_step_shows_summary(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
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
                "contact_name": "Summary Tester",
            },
        )

        # Now access the complete step
        response = client.get(reverse("teams:onboarding_wizard") + "?step=complete")

        assert response.status_code == 200
        assert response.context["current_step"] == "complete"
        assert response.context["company_name"] == "Summary Test Inc"
        assert response.context["component_id"] is not None

    def test_session_updated_after_completion(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
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
                "contact_name": "Session Tester",
            },
        )

        # Check session was updated
        session = client.session
        assert session["current_team"]["has_completed_wizard"] is True
        assert session["current_team"]["name"] == "Session Test's Workspace"

    def test_company_name_required(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
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
                "contact_name": "Test User",
                "email": "test@test.com",
            },
        )

        # Should stay on the same page with form errors
        assert response.status_code == 200
        assert response.context["form"].errors.get("company_name") is not None

    def test_contact_name_required(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
        """Test that contact_name is required for NTIA compliance."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # Submit without contact_name
        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Test Company",
                "email": "test@test.com",
            },
        )

        # Should stay on the same page with form errors
        assert response.status_code == 200
        assert response.context["form"].errors.get("contact_name") is not None

    def test_website_is_optional(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
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
                "contact_name": "No Website Tester",
            },
        )

        assert response.status_code == 302

        profile = ContactProfile.objects.filter(team=team).first()
        assert profile is not None
        # website_urls is now on the entity, not the profile
        entity = profile.entities.first()
        assert entity is not None
        assert entity.website_urls == []

    def test_invalid_website_url(self, client: Client, sample_user, sample_team_with_owner_member, community_plan) -> None:
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
                "contact_name": "Invalid URL Tester",
                "website": "not-a-valid-url",
            },
        )

        # Should stay on same page with form errors
        assert response.status_code == 200
        assert response.context["form"].errors.get("website") is not None

    def test_community_plan_creates_public_entities(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Test that community plan wizard creates public entities."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        # Ensure team is on community plan (cannot be private)
        team.billing_plan = "community"
        team.save()

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
                "company_name": "Community Corp",
                "contact_name": "Community Tester",
            },
        )

        assert response.status_code == 302

        # Verify all entities are public for community plan
        product = Product.objects.filter(team=team, name="Community Corp").first()
        assert product is not None
        assert product.is_public is True

        project = Project.objects.filter(team=team, name="Main Project").first()
        assert project is not None
        assert project.is_public is True

        component = Component.objects.filter(team=team, name="Main Component").first()
        assert component is not None
        assert component.is_public is True

    def test_business_plan_creates_private_entities(
        self, client: Client, sample_user, sample_team_with_owner_member
    ) -> None:
        """Test that business plan wizard creates private entities."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        # Create and set up business plan for the team
        BillingPlan.objects.get_or_create(
            key="business",
            defaults={
                "name": "Business",
                "description": "Business Plan",
                "max_products": 10,
                "max_projects": 10,
                "max_components": 10,
            },
        )
        team.billing_plan = "business"
        team.save()

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
                "company_name": "Business Corp",
                "contact_name": "Business Tester",
            },
        )

        assert response.status_code == 302

        # Verify all entities are private for business plan
        product = Product.objects.filter(team=team, name="Business Corp").first()
        assert product is not None
        assert product.is_public is False

        project = Project.objects.filter(team=team, name="Main Project").first()
        assert project is not None
        assert project.is_public is False

        component = Component.objects.filter(team=team, name="Main Component").first()
        assert component is not None
        assert component.is_public is False
