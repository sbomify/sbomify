"""Tests for the onboarding wizard single-step flow."""

import pytest
from django.conf import settings
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.sboms.models import Component, Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile


@pytest.fixture
def community_plan() -> BillingPlan:
    """Free community plan fixture."""
    plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan for small teams",
            "max_products": 1,
            "max_components": 5,
            "stripe_product_id": None,
            "stripe_price_monthly_id": None,
            "stripe_price_annual_id": None,
        },
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

        team = sample_team_with_owner_member.team
        team.has_selected_billing_plan = True
        team.save(update_fields=["has_selected_billing_plan"])

        session = client.session
        session["current_team"] = {
            "key": team.key,
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

        team = sample_team_with_owner_member.team
        team.has_selected_billing_plan = True
        team.save(update_fields=["has_selected_billing_plan"])

        session = client.session
        session["current_team"] = {
            "key": team.key,
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

    def test_wizard_shows_welcome_step(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that GET request without params shows the welcome step."""
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
        assert response.context["current_step"] == "welcome"
        assert "first_name" in response.context

    def test_setup_step_shows_form(self, client: Client, sample_user, sample_team_with_owner_member) -> None:
        """Test that GET request with ?step=setup shows the form with pre-filled email."""
        client.force_login(sample_user)
        session = client.session
        session["current_team"] = {
            "key": sample_team_with_owner_member.team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.get(reverse("teams:onboarding_wizard") + "?step=setup")

        assert response.status_code == 200
        assert response.context["current_step"] == "setup"
        assert "form" in response.context

        # Check email is pre-filled
        form = response.context["form"]
        assert form.initial.get("email") == sample_user.email

    def test_successful_onboarding_flow(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
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

    def test_contact_profile_created(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
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

        # Verify ContactProfileContact was created with is_author=True for NTIA/CycloneDX compliance
        contact = entity.contacts.first()
        assert contact is not None
        assert contact.name == "John Doe"
        assert contact.email == "contact@test.com"
        assert contact.is_author is True  # Contact is marked as author

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

    def test_no_product_or_component_is_created(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """The wizard sets up an identity, not an inventory.

        It used to create a product named after the company and a component
        called "Main Component". Bootstrapping an account left two entities
        nobody asked for, and pre-ticked the dashboard's own "create your first
        product" and "create your first component" steps — so the checklist
        meant to guide someone through those was complete before they had done
        either.
        """
        from sbomify.apps.core.models import Component, Product

        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        session = client.session
        session["current_team"] = {"key": team.key, "role": "owner", "has_completed_wizard": False}
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "No Auto Entities Ltd",
                "contact_name": "Jane Doe",
                "email": "jane@example.com",
                "goal": "compliance",
            },
        )

        assert response.status_code == 302
        assert not Product.objects.filter(team=team).exists()
        assert not Component.objects.filter(team=team).exists()

    def test_the_identity_it_does_set_up_survives(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """What the wizard is actually for is unchanged: the workspace name and
        the manufacturer/contact identity. Removing the entities must not take
        those with it."""
        from sbomify.apps.teams.models import ContactEntity, Team

        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        session = client.session
        session["current_team"] = {"key": team.key, "role": "owner", "has_completed_wizard": False}
        session.save()

        client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Identity Survives Ltd",
                "contact_name": "Jane Doe",
                "email": "jane@example.com",
                "goal": "compliance",
            },
        )

        team = Team.objects.get(pk=team.pk)
        assert team.has_completed_wizard is True
        assert "Identity Survives Ltd" in team.name
        entity = ContactEntity.objects.get(profile__team=team, is_manufacturer=True)
        # The posted address, not the user's. Before the field name was fixed the
        # form ignored it and this fell back to sample_user.email, so the test
        # passed while exercising nothing.
        assert entity.email == "jane@example.com"


    def test_complete_step_shows_summary(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
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
        # No component id: the completion step is keyed on the company name now,
        # since the wizard no longer creates a component to point at.
        #
        # The positive control matters: ContextList.__contains__ does look up
        # keys, but a bare "not in" assertion is indistinguishable from one that
        # can never fail, so a key known to be present is asserted beside it.
        assert "company_name" in response.context
        assert "component_id" not in response.context

    def test_session_updated_after_completion(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
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

    def test_company_name_required(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
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

    def test_contact_name_required(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
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

    def test_website_is_optional(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
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

    def test_invalid_website_url(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
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

    def test_goal_field_saved_to_team(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Test that the optional goal field is saved to team.onboarding_goal."""
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
                "company_name": "Goal Test Corp",
                "contact_name": "Goal Tester",
                "goal": "Track open source dependencies and meet compliance requirements",
            },
        )

        assert response.status_code == 302
        team.refresh_from_db()
        assert team.onboarding_goal == "Track open source dependencies and meet compliance requirements"

    def test_goal_field_is_optional(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Test that submitting without goal succeeds (no regression)."""
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
                "company_name": "No Goal Corp",
                "contact_name": "No Goal Tester",
            },
        )

        assert response.status_code == 302
        team.refresh_from_db()
        assert team.onboarding_goal == ""
        assert team.has_completed_wizard is True

    def test_onboarding_completes_when_team_at_billing_limit(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Test that onboarding completes even when team is at billing plan limits.

        Regression test: teams with pre-existing assets at the plan limit should
        not get stuck in an infinite onboarding redirect loop.
        """
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        team.billing_plan = "community"
        team.save(update_fields=["billing_plan"])

        # Pre-create assets up to the community plan limits (1 product, 5 components)
        product = Product.objects.create(name="Existing Product", team=team, is_public=True)
        for i in range(5):
            comp = Component.objects.create(
                name=f"Existing Component {i}",
                team=team,
                component_type=Component.ComponentType.BOM,
                visibility=Component.Visibility.PUBLIC,
            )
            product.components.add(comp)

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
                "company_name": "At Limit Corp",
                "contact_name": "Limit Tester",
            },
        )

        # Should redirect to complete step, NOT loop back to welcome
        assert response.status_code == 302
        assert "step=complete" in response.url

        team.refresh_from_db()
        assert team.has_completed_wizard is True

        # Single product is renamed in place; component uses get_or_create with a
        # fixed "Main Component" name, creating at most one new component.
        # The point of this test is that a team at its plan limit can still
        # finish onboarding. It used to prove that by counting the entities the
        # wizard created; with none created, the limit cannot be the thing that
        # blocks it, and completion is the whole assertion.
        assert Component.objects.filter(team=team).count() == 5  # unchanged by the wizard

    def test_rerun_onboarding_updates_manufacturer_entity(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Test that re-running onboarding updates the manufacturer entity in place.

        When onboarding is re-run with a different company name, the existing
        manufacturer ContactEntity should be updated, not duplicated.
        """
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # First onboarding
        client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Original Corp",
                "contact_name": "First Tester",
                "email": "first@original.com",
                "website": "https://original.com",
            },
        )

        profile = ContactProfile.objects.get(team=team, is_default=True)
        assert ContactEntity.objects.filter(profile=profile, is_manufacturer=True).count() == 1
        entity = ContactEntity.objects.get(profile=profile, is_manufacturer=True)
        assert entity.name == "Original Corp"

        # Reset wizard state for second run
        team.has_completed_wizard = False
        team.save(update_fields=["has_completed_wizard"])
        session = client.session
        session["current_team"]["has_completed_wizard"] = False
        session.save()

        # Second onboarding with different company name
        response = client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Renamed Corp",
                "contact_name": "Second Tester",
                "email": "second@renamed.com",
                "website": "https://renamed.com",
            },
        )

        assert response.status_code == 302
        assert "step=complete" in response.url

        # Still exactly one manufacturer entity, with updated fields
        assert ContactEntity.objects.filter(profile=profile, is_manufacturer=True).count() == 1
        entity.refresh_from_db()
        assert entity.name == "Renamed Corp"
        assert entity.email == "second@renamed.com"
        assert entity.website_urls == ["https://renamed.com"]

    def test_rerun_onboarding_preserves_website_when_omitted(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Re-running onboarding without a website should preserve the previously saved URL."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # First onboarding with a website
        client.post(
            reverse("teams:onboarding_wizard"),
            {
                "company_name": "Website Corp",
                "contact_name": "Tester",
                "website": "https://website-corp.com",
            },
        )

        profile = ContactProfile.objects.get(team=team, is_default=True)
        entity = ContactEntity.objects.get(profile=profile, is_manufacturer=True)
        assert entity.website_urls == ["https://website-corp.com"]

        # Reset wizard for re-run
        team.has_completed_wizard = False
        team.save(update_fields=["has_completed_wizard"])
        session = client.session
        session["current_team"]["has_completed_wizard"] = False
        session.save()

        # Re-run WITHOUT providing a website
        response = client.post(
            reverse("teams:onboarding_wizard"),
            {"company_name": "Website Corp", "contact_name": "Tester"},
        )

        assert response.status_code == 302
        entity.refresh_from_db()
        assert entity.website_urls == ["https://website-corp.com"]

    def test_completed_onboarding_redirects_to_dashboard(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Test that visiting the wizard after full onboarding redirects to dashboard with info message."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        team.has_completed_wizard = True
        team.has_selected_billing_plan = True
        team.save(update_fields=["has_completed_wizard", "has_selected_billing_plan"])

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()

        response = client.get(reverse("teams:onboarding_wizard"))

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        msgs = list(get_messages(response.wsgi_request))
        assert any("Onboarding is already complete" in str(m) for m in msgs)

    def test_post_to_completed_wizard_redirects_to_dashboard(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """POST to wizard after full onboarding should redirect without processing form."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        team.has_completed_wizard = True
        team.has_selected_billing_plan = True
        team.save(update_fields=["has_completed_wizard", "has_selected_billing_plan"])

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {"company_name": "Should Not Be Created", "contact_name": "Ghost"},
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        msgs = list(get_messages(response.wsgi_request))
        assert any("Onboarding is already complete" in str(m) for m in msgs)
        assert not Product.objects.filter(team=team, name="Should Not Be Created").exists()

    def test_billing_pending_does_not_redirect(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Wizard should pass through when billing plan selection is still pending."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        team.has_completed_wizard = True
        team.has_selected_billing_plan = False
        team.save(update_fields=["has_completed_wizard", "has_selected_billing_plan"])

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()

        response = client.get(reverse("teams:onboarding_wizard"))
        assert response.status_code == 200

    def test_entity_name_conflict_keeps_old_name(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """When re-running onboarding and another entity already has the target name,
        the manufacturer entity keeps its old name and user sees a warning."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        # First onboarding — creates "Original Corp" manufacturer entity
        client.post(
            reverse("teams:onboarding_wizard"),
            {"company_name": "Original Corp", "contact_name": "Tester"},
        )

        profile = ContactProfile.objects.get(team=team, is_default=True)
        entity = ContactEntity.objects.get(profile=profile, is_manufacturer=True)
        assert entity.name == "Original Corp"

        # Manually create a conflicting entity with the name we'll try to rename to
        ContactEntity.objects.create(profile=profile, name="Conflicting Corp", is_author=True)

        # Reset wizard for re-run
        team.has_completed_wizard = False
        team.save(update_fields=["has_completed_wizard"])
        session = client.session
        session["current_team"]["has_completed_wizard"] = False
        session.save()

        # Re-run onboarding with a name that conflicts
        response = client.post(
            reverse("teams:onboarding_wizard"),
            {"company_name": "Conflicting Corp", "contact_name": "Tester"},
        )

        # Wizard should still complete
        assert response.status_code == 302
        assert "step=complete" in response.url

        # Entity name should NOT have changed
        entity.refresh_from_db()
        assert entity.name == "Original Corp"

        # Warning message should be present
        msgs = list(get_messages(response.wsgi_request))
        assert any("already exists" in str(m) and "kept the previous name" in str(m) for m in msgs)

    def test_non_owner_post_redirects_to_dashboard(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Non-owner members posting to the wizard should be redirected to dashboard."""
        from sbomify.apps.teams.models import Member

        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        # Downgrade user from owner to member
        member = Member.objects.get(user=sample_user, team=team)
        member.role = "member"
        member.save(update_fields=["role"])

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "member",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {"company_name": "Should Not Be Created", "contact_name": "Ghost"},
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")
        assert not Product.objects.filter(team=team, name="Should Not Be Created").exists()

    def test_payment_restricted_post_shows_error(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan, mocker
    ) -> None:
        """Payment-restricted teams should see an error and be redirected back to the wizard."""
        from sbomify.apps.teams.models import Team

        client.force_login(sample_user)
        team = sample_team_with_owner_member.team

        mocker.patch.object(Team, "is_payment_restricted", new_callable=mocker.PropertyMock, return_value=True)

        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        response = client.post(
            reverse("teams:onboarding_wizard"),
            {"company_name": "Suspended Corp", "contact_name": "Suspended User"},
        )

        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

        msgs = list(get_messages(response.wsgi_request))
        assert any("suspended" in str(m).lower() for m in msgs)
        assert not Product.objects.filter(team=team, name="Suspended Corp").exists()

    def test_complete_step_visible_after_setup(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """The completion screen must render even though has_completed_wizard is already True.

        After _process_setup sets has_completed_wizard=True and redirects to ?step=complete,
        the dispatch guard must let the request through when wizard_component_id is in the session.
        """
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        team.has_completed_wizard = True
        team.has_selected_billing_plan = True
        team.save(update_fields=["has_completed_wizard", "has_selected_billing_plan"])

        component = Component.objects.create(
            name="Test Component", team=team, component_type=Component.ComponentType.BOM
        )

        session = client.session
        session["current_team"] = {"key": team.key, "role": "owner", "has_completed_wizard": True}
        session["wizard_component_id"] = component.id
        session["wizard_company_name"] = "Test Corp"
        session.save()

        response = client.get(reverse("teams:onboarding_wizard") + "?step=complete")

        assert response.status_code == 200
        assert response.context["current_step"] == "complete"

    def test_complete_step_redirects_without_session_key(
        self, client: Client, sample_user, sample_team_with_owner_member, community_plan
    ) -> None:
        """Visiting ?step=complete without wizard_component_id in session should redirect."""
        client.force_login(sample_user)
        team = sample_team_with_owner_member.team
        team.has_completed_wizard = True
        team.has_selected_billing_plan = True
        team.save(update_fields=["has_completed_wizard", "has_selected_billing_plan"])

        session = client.session
        session["current_team"] = {"key": team.key, "role": "owner", "has_completed_wizard": True}
        session.save()

        response = client.get(reverse("teams:onboarding_wizard") + "?step=complete")

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")
