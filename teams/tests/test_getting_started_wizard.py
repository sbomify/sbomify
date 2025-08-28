import pytest
from django.conf import settings
from django.contrib.messages import get_messages
from django.db import transaction, IntegrityError
from django.test import Client
from django.urls import reverse
from allauth.socialaccount.models import SocialAccount

from sboms.models import Component, Product, Project
from teams.models import Team

# Import billing fixtures for testing
pytest_plugins = ["billing.tests.fixtures"]


@pytest.mark.django_db
class TestGettingStartedWizard:
    """Test the new Django template-based getting started wizard."""

    def test_wizard_requires_login(self, client: Client):
        """Test that the getting started wizard requires login."""
        response = client.get(reverse("teams:getting_started_wizard"))
        assert response.status_code == 302
        assert response.url.startswith(settings.LOGIN_URL)

    def test_wizard_initial_load_plan_step(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test the wizard loads correctly on the plan selection step."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        response = client.get(reverse("teams:getting_started_wizard"))
        assert response.status_code == 200
        assert "teams/getting_started_wizard.html.j2" in [t.name for t in response.templates]
        assert response.context["current_step"] == "plan"
        assert response.context["progress"] == 0
        assert "form" in response.context

        # Check that the form is the correct type
        from teams.forms import WizardPlanSelectionForm
        assert isinstance(response.context["form"], WizardPlanSelectionForm)

    def test_wizard_step_navigation_via_query_param(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test wizard step navigation via query parameters."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Test direct navigation to different steps
        response = client.get(reverse("teams:getting_started_wizard") + "?step=plan")
        assert response.status_code == 200
        assert response.context["current_step"] == "plan"
        assert response.context["progress"] == 0

        response = client.get(reverse("teams:getting_started_wizard") + "?step=project")
        assert response.status_code == 200
        assert response.context["current_step"] == "project"
        assert response.context["progress"] == 45

    def test_wizard_invalid_step_defaults_to_plan(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that invalid steps default to plan step."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        response = client.get(reverse("teams:getting_started_wizard") + "?step=invalid")
        assert response.status_code == 200
        assert response.context["current_step"] == "plan"

    def test_plan_selection_step(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test the plan selection step of the wizard."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Test GET request to plan step
        response = client.get(reverse("teams:getting_started_wizard") + "?step=plan")
        assert response.status_code == 200
        assert response.context["current_step"] == "plan"
        assert "Choose Your Plan" in response.content.decode()

        # Test POST request to plan step
        form_data = {"plan": "community"}
        response = client.post(reverse("teams:getting_started_wizard") + "?step=plan", form_data)
        assert response.status_code == 302  # Redirect to next step

        # Check that team billing plan was updated
        team = sample_team_with_owner_member.team
        team.refresh_from_db()
        assert team.billing_plan == "community"

        # Check that session was updated
        session = client.session
        assert session["current_team"]["billing_plan"] == "community"

    def test_enterprise_plan_redirects_to_contact(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that selecting enterprise plan redirects to contact form."""
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # Test POST with enterprise plan
        response = client.post(reverse("teams:getting_started_wizard"), {"plan": "enterprise"})
        assert response.status_code == 302
        # Should redirect to public enterprise contact form
        assert response.url == reverse("public_enterprise_contact")

        # Check session has enterprise flag
        session = client.session
        assert session.get("selected_enterprise_plan") == True

        # Check team billing plan was NOT updated (enterprise requires contact)
        sample_team_with_owner_member.team.refresh_from_db()
        assert sample_team_with_owner_member.team.billing_plan != "enterprise"

        # Check success message was added
        messages = list(get_messages(response.wsgi_request))
        assert any("Enterprise plan" in str(m) and "contact form" in str(m) for m in messages)

    def test_successful_wizard_flow(self, client: Client, sample_user, sample_team_with_owner_member, community_plan):
        """Test the complete successful flow of the getting started wizard."""
        team = sample_team_with_owner_member.team

        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Step 1: Select Plan
        response = client.post(reverse("teams:getting_started_wizard"), {
            "plan": "community"
        })

        assert response.status_code == 302
        assert response.url == reverse("teams:getting_started_wizard")

        # Verify team billing plan was set
        team.refresh_from_db()
        assert team.billing_plan == "community"

        # Step 2: Create Product
        response = client.post(reverse("teams:getting_started_wizard"), {
            "name": "Test Product",
            "description": "A test product description"
        })

        assert response.status_code == 302
        assert response.url == reverse("teams:getting_started_wizard")

        messages = list(get_messages(response.wsgi_request))
        assert any("Product 'Test Product' created successfully" in str(m) for m in messages)

        # Verify product was created
        product = Product.objects.filter(name="Test Product").first()
        assert product is not None
        assert product.team == team
        assert product.description == "A test product description"

        # Step 3: Create Project
        session = client.session
        assert session["wizard_step"] == "project"
        assert session["wizard_product_id"] == str(product.id)

        response = client.post(reverse("teams:getting_started_wizard"), {
            "name": "Test Project"
        })
        assert response.status_code == 302
        assert response.url == reverse("teams:getting_started_wizard")

        messages = list(get_messages(response.wsgi_request))
        assert any("Project 'Test Project' created successfully" in str(m) for m in messages)

        # Verify project was created and linked
        project = Project.objects.filter(name="Test Project").first()
        assert project is not None
        assert project.team == team
        assert project in product.projects.all()

        # Step 4: Create Component
        session = client.session
        assert session["wizard_step"] == "component"
        assert session["wizard_project_id"] == str(project.id)

        response = client.post(reverse("teams:getting_started_wizard"), {
            "name": "Test Component"
        })
        assert response.status_code == 302
        assert response.url == reverse("teams:getting_started_wizard")

        messages = list(get_messages(response.wsgi_request))
        assert any("Component 'Test Component' created successfully" in str(m) for m in messages)

        # Verify component was created and linked
        component = Component.objects.filter(name="Test Component").first()
        assert component is not None
        assert component.team == team
        assert component in project.components.all()

        # Verify wizard completion
        team.refresh_from_db()
        assert team.has_completed_wizard is True

        # Verify session is updated
        session = client.session
        assert session["wizard_step"] == "complete"
        assert session["current_team"]["has_completed_wizard"] is True

    def test_wizard_completion_page(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test the wizard completion page displays correctly."""
        # Set up team
        team = sample_team_with_owner_member.team
        team.billing_plan = "community"
        team.save()

        # Create a component for the completion page
        product = Product.objects.create(name="Test Product", team=team)
        project = Project.objects.create(name="Test Project", team=team)
        component = Component.objects.create(name="Test Component", team=team)
        product.projects.add(project)
        project.components.add(component)

        # Login and set session data for completion step
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": True
        }
        session["wizard_step"] = "complete"
        session["wizard_component_id"] = str(component.id)
        session.save()

        response = client.get(reverse("teams:getting_started_wizard") + "?step=complete")
        assert response.status_code == 200
        assert response.context["current_step"] == "complete"
        assert response.context["component_id"] == str(component.id)

        # Check completion page content
        content = response.content.decode()
        assert "All Set!" in content
        assert "Complete Metadata" in content
        assert "Upload SBOM" in content

    def test_wizard_form_validation_errors(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that form validation errors are displayed correctly."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Submit empty form
        response = client.post(reverse("teams:getting_started_wizard"), {})
        assert response.status_code == 200
        assert response.context["current_step"] == "plan"
        assert "form" in response.context
        assert response.context["form"].errors

    def test_wizard_billing_limits_handling(self, client: Client, sample_user, sample_team_with_owner_member, community_plan):
        """Test that billing limits are handled correctly via API responses."""
        team = sample_team_with_owner_member.team

        # Create existing product to hit the 1-product limit
        existing_product = Product.objects.create(name="Existing Product", team=team)

        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Step 1: Select community plan
        response = client.post(reverse("teams:getting_started_wizard"), {
            "plan": "community"
        })
        assert response.status_code == 302  # Redirect to next step

        # Step 2: Try to create another product (should hit billing limit)
        response = client.post(reverse("teams:getting_started_wizard"), {
            "name": "Another Product"
        })

        # Should stay on same page with error message
        assert response.status_code == 200
        messages = list(get_messages(response.wsgi_request))
        # Community plan only allows 1 product, so it hits billing limit rather than duplicate check
        assert any("maximum 1 products allowed" in str(m) for m in messages)

    def test_wizard_missing_previous_steps(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that trying to skip steps is handled correctly."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session["wizard_step"] = "component"  # Jump to last step without previous data
        session.save()

        # Try to create component without previous steps
        response = client.post(reverse("teams:getting_started_wizard"), {
            "name": "Test Component"
        })

        # Should redirect back to plan step (first validation that kicks in)
        assert response.status_code == 302
        assert response.url == reverse("teams:getting_started_wizard")

        messages = list(get_messages(response.wsgi_request))
        assert any("Please select a billing plan first" in str(m) for m in messages)

        # Check session was reset
        session = client.session
        assert session["wizard_step"] == "plan"

    def test_wizard_with_keycloak_metadata(self, client: Client, sample_user, sample_team_with_owner_member, community_plan):
        """Test that Keycloak user metadata is properly used when creating a component."""
        team = sample_team_with_owner_member.team

        # Create Keycloak social auth record with metadata
        social_account = SocialAccount.objects.create(
            user=sample_user,
            provider="keycloak",
            extra_data={
                "user_metadata": {
                    "company": "Acme Corp",
                    "supplier_url": "https://acme.example.com"
                }
            }
        )

        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Complete the full wizard flow
        # Step 1: Plan Selection
        client.post(reverse("teams:getting_started_wizard"), {
            "plan": "community"
        })

        # Step 2: Product
        client.post(reverse("teams:getting_started_wizard"), {
            "name": "Test Product"
        })

        # Step 3: Project
        client.post(reverse("teams:getting_started_wizard"), {
            "name": "Test Project"
        })

        # Step 4: Component
        client.post(reverse("teams:getting_started_wizard"), {
            "name": "Test Component"
        })

        # Verify component metadata includes Keycloak data
        component = Component.objects.filter(name="Test Component").first()
        assert component is not None
        supplier_data = component.metadata.get("supplier", {})
        assert supplier_data.get("name") == "Acme Corp"
        assert "https://acme.example.com" in supplier_data.get("url", [])

    def test_wizard_progress_calculation(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that wizard progress is calculated correctly."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Test each step's progress
        test_cases = [
            ("plan", 0),
            ("product", 20),
            ("project", 45),
            ("component", 70),
            ("complete", 100),
        ]

        for step, expected_progress in test_cases:
            response = client.get(reverse("teams:getting_started_wizard") + f"?step={step}")
            assert response.status_code == 200
            assert response.context["progress"] == expected_progress

    def test_wizard_step_indicators(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that step indicators are rendered correctly."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        response = client.get(reverse("teams:getting_started_wizard"))
        assert response.status_code == 200

        # Check that steps are in context
        steps = response.context["steps"]
        assert len(steps) == 5
        assert steps[0]["name"] == "plan"
        assert steps[1]["name"] == "product"
        assert steps[2]["name"] == "project"
        assert steps[3]["name"] == "component"
        assert steps[4]["name"] == "complete"

        # Check icons are present
        for step in steps:
            assert "icon" in step
            assert step["icon"].startswith("fas fa-")

    def test_wizard_form_field_help_text(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that form field help text is displayed correctly."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        response = client.get(reverse("teams:getting_started_wizard"))
        assert response.status_code == 200

        content = response.content.decode()

        # Check that help text is present for plan step
        assert "Start with Community and upgrade anytime" in content
        assert "You can always change your plan later" in content

    def test_wizard_responsiveness_and_accessibility(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that the wizard template includes responsive and accessibility features."""
        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        response = client.get(reverse("teams:getting_started_wizard"))
        assert response.status_code == 200

        content = response.content.decode()

        # Check responsive classes
        assert "col-lg-10" in content  # Updated to match new layout
        assert "col-xl-8" in content

        # Check accessibility features
        assert 'aria-valuenow' in content  # Progress bar
        assert 'aria-valuemin' in content
        assert 'aria-valuemax' in content
        assert 'role="progressbar"' in content

        # Check form labels are properly associated
        assert 'for=' in content  # Label for attributes

    def test_wizard_session_cleanup_on_completion(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that wizard session data is cleaned up on completion."""
        # Setup component for completion page
        component = Component.objects.create(name="Test Component", team=sample_team_with_owner_member.team)

        # Login and set session data for completion step
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": True
        }
        session["wizard_step"] = "complete"
        session["wizard_component_id"] = str(component.id)
        session["wizard_product_id"] = "test-product-id"
        session["wizard_project_id"] = "test-project-id"
        session.save()

        # Visit completion page
        response = client.get(reverse("teams:getting_started_wizard") + "?step=complete")
        assert response.status_code == 200

        # Check that session wizard data is cleaned up
        session = client.session
        assert "wizard_step" not in session
        assert "wizard_product_id" not in session
        assert "wizard_project_id" not in session
        assert "wizard_component_id" not in session

    def test_automatic_wizard_redirect_from_dashboard(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that users are automatically redirected to wizard from dashboard if they haven't completed it."""
        # Set team as not having completed wizard
        team = sample_team_with_owner_member.team
        team.has_completed_wizard = False
        team.save()

        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # Test dashboard redirect
        response = client.get(reverse("core:dashboard"))
        assert response.status_code == 302
        assert response.url == reverse("teams:getting_started_wizard")

        # Test home redirect
        response = client.get("/")
        assert response.status_code == 302
        assert response.url == reverse("teams:getting_started_wizard")

    def test_no_wizard_redirect_when_completed(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that users are NOT redirected to wizard when they've completed it."""
        # Set team as having completed wizard
        team = sample_team_with_owner_member.team
        team.has_completed_wizard = True
        team.save()

        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": True
        }
        session.save()

        # Test dashboard renders normally
        response = client.get(reverse("core:dashboard"))
        assert response.status_code == 200
        assert "core/dashboard.html.j2" in [t.name for t in response.templates]

        # Test home redirects to dashboard normally
        response = client.get("/")
        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

    def test_skip_wizard_functionality(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that the skip wizard button works correctly."""
        # Set team as not having completed wizard
        team = sample_team_with_owner_member.team
        team.has_completed_wizard = False
        team.save()

        # Login and set session data
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session["wizard_step"] = "product"  # Add some wizard session data
        session["wizard_product_id"] = "test-product"
        session.save()

        # POST to skip wizard endpoint
        response = client.post(reverse("teams:skip_getting_started_wizard"))

        # Should redirect to dashboard
        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        # Check that team is marked as having completed wizard
        team.refresh_from_db()
        assert team.has_completed_wizard == True

        # Check that session was updated and cleaned up
        session = client.session
        assert session["current_team"]["has_completed_wizard"] == True
        assert "wizard_step" not in session
        assert "wizard_product_id" not in session

        # Check that success message was added
        messages = list(get_messages(response.wsgi_request))
        assert any("Getting started wizard skipped" in str(m) for m in messages)

    def test_skip_wizard_get_request_redirects(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that GET requests to skip wizard redirect to the wizard."""
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False
        }
        session.save()

        # GET request should redirect to wizard
        response = client.get(reverse("teams:skip_getting_started_wizard"))
        assert response.status_code == 302
        assert response.url == reverse("teams:getting_started_wizard")
