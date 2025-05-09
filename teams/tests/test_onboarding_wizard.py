import pytest
from django.conf import settings
from django.contrib.messages import get_messages
from django.db import transaction
from django.test import Client
from django.urls import reverse
from allauth.socialaccount.models import SocialAccount

from sboms.models import Component, Product, Project
from teams.models import Team


@pytest.mark.django_db
class TestOnboardingWizard:
    def test_wizard_requires_login(self, client: Client):
        """Test that the onboarding wizard requires login."""
        response = client.get(reverse("teams:onboarding_wizard"))
        assert response.status_code == 302
        assert response.url.startswith(settings.LOGIN_URL)

    def test_successful_wizard_flow(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test the complete successful flow of the onboarding wizard."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session["wizard_step"] = "product"
        session.save()

        # Step 1: Create Product
        response = client.post(reverse("teams:onboarding_wizard"), {
            "name": "Test Product"
        })
        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

        messages = list(get_messages(response.wsgi_request))
        assert any("Product 'Test Product' created successfully" in str(m) for m in messages)

        product = Product.objects.filter(name="Test Product").first()
        assert product is not None
        assert product.team == sample_team_with_owner_member.team

        # Step 2: Create Project
        session = client.session
        session["wizard_step"] = "project"
        session.save()

        response = client.post(reverse("teams:onboarding_wizard"), {
            "name": "Test Project"
        })
        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

        messages = list(get_messages(response.wsgi_request))
        assert any("Project 'Test Project' created successfully" in str(m) for m in messages)

        project = Project.objects.filter(name="Test Project").first()
        assert project is not None
        assert project.team == sample_team_with_owner_member.team

        # Step 3: Create Component
        session = client.session
        session["wizard_step"] = "component"
        session.save()

        response = client.post(reverse("teams:onboarding_wizard"), {
            "name": "Test Component"
        })
        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

        messages = list(get_messages(response.wsgi_request))
        assert any("Component 'Test Component' created successfully" in str(m) for m in messages)

        component = Component.objects.filter(name="Test Component").first()
        assert component is not None
        assert component.team == sample_team_with_owner_member.team

        # Verify relationships
        assert project in product.projects.all()
        assert component in project.components.all()

        # Verify wizard completion
        team = Team.objects.get(pk=sample_team_with_owner_member.team.pk)
        assert team.has_completed_wizard is True

    def test_keycloak_metadata_in_component(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that Keycloak user metadata is properly used when creating a component."""
        # Create Keycloak social auth record with metadata
        social_account = SocialAccount.objects.create(
            user=sample_user,
            provider="keycloak",
            extra_data={
                "user_metadata": {
                    "company": "Acme Corp",
                    "supplier_contact": {
                        "name": "John Doe",
                        "email": "john@example.com"
                    }
                }
            }
        )
        social_account.save()

        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session["wizard_step"] = "product"
        session.save()

        # Step 1: Create Product
        response = client.post(reverse("teams:onboarding_wizard"), {
            "name": "Test Product"
        })
        assert response.status_code == 302

        # Step 2: Create Project
        session = client.session
        session["wizard_step"] = "project"
        session.save()

        response = client.post(reverse("teams:onboarding_wizard"), {
            "name": "Test Project"
        })
        assert response.status_code == 302

        # Step 3: Create Component
        session = client.session
        session["wizard_step"] = "component"
        session.save()

        response = client.post(reverse("teams:onboarding_wizard"), {
            "name": "Test Component"
        })
        assert response.status_code == 302

        # Verify component metadata
        component = Component.objects.filter(name="Test Component").first()
        assert component is not None
        assert component.metadata.get("supplier", {}).get("contact") == {
            "name": "John Doe",
            "email": "john@example.com"
        }

    def test_duplicate_names(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that duplicate names are handled correctly."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session["wizard_step"] = "product"
        session.save()

        with transaction.atomic():
            # Create first product
            response = client.post(reverse("teams:onboarding_wizard"), {
                "name": "Test Product"
            })
            assert response.status_code == 302

            # Try to create duplicate product
            session = client.session
            session["wizard_step"] = "product"  # Make sure we're still on the product step
            session.save()

            response = client.post(reverse("teams:onboarding_wizard"), {
                "name": "Test Product"
            })
            assert response.status_code == 200  # Stays on the same page
            messages = list(get_messages(response.wsgi_request))
            assert any("A product with the name 'Test Product' already exists in your team" in str(m) for m in messages)

    def test_missing_previous_steps(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that trying to skip steps is handled correctly."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session["wizard_step"] = "component"  # Try to jump to last step
        session.save()

        with transaction.atomic():
            # Try to create component without previous steps
            response = client.post(reverse("teams:onboarding_wizard"), {
                "name": "Test Component"
            })
            assert response.status_code == 302
            messages = list(get_messages(response.wsgi_request))
            assert any("The product or project from previous steps no longer exists" in str(m) for m in messages)

    def test_invalid_step(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that invalid steps are handled correctly."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Try to access invalid step
        response = client.get(reverse("teams:onboarding_wizard") + "?step=invalid")
        assert response.status_code == 200
        assert "current_step" in response.context
        assert response.context["current_step"] == "product"  # Should default to first step