from __future__ import annotations

import typing

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from sbomify.apps.billing.models import BillingPlan  # noqa: F401
from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.forms import OnboardingCompanyForm
from sbomify.apps.teams.models import (
    ContactEntity,
    ContactProfile,
    ContactProfileContact,
    Team,
    format_workspace_name,
)
from sbomify.apps.teams.utils import (
    refresh_current_team_session,
    update_user_teams_session,
)
from sbomify.logging import getLogger

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

log = getLogger(__name__)

DEFAULT_SBOM_AUGMENTATION_URL = "https://sbomify.com/features/generate-collaborate-analyze/"


class OnboardingWizardView(LoginRequiredMixin, View):
    """3-step onboarding wizard: Welcome -> Company Info -> Success."""

    def get(self, request: HttpRequest) -> HttpResponse:
        step = request.GET.get("step")
        if step == "setup":
            return self._render_setup(request)
        if step == "complete":
            return self._render_complete(request)
        return self._render_welcome(request)

    def post(self, request: HttpRequest) -> HttpResponse:
        return self._process_setup(request)

    def _render_welcome(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        first_name = user.first_name or (user.email or "").split("@")[0]
        context = {
            "current_step": "welcome",
            "first_name": first_name,
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _render_setup(self, request: HttpRequest) -> HttpResponse:
        initial = {"email": request.user.email}
        full_name = request.user.get_full_name()
        if full_name:
            initial["contact_name"] = full_name

        form = OnboardingCompanyForm(initial=initial)
        sbom_augmentation_url = getattr(settings, "SBOM_AUGMENTATION_URL", DEFAULT_SBOM_AUGMENTATION_URL)

        context = {
            "form": form,
            "current_step": "setup",
            "sbom_augmentation_url": sbom_augmentation_url,
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _render_complete(self, request: HttpRequest) -> HttpResponse:
        sbom_augmentation_url = getattr(settings, "SBOM_AUGMENTATION_URL", DEFAULT_SBOM_AUGMENTATION_URL)
        context = {
            "current_step": "complete",
            "component_id": request.session.pop("wizard_component_id", None),
            "company_name": request.session.pop("wizard_company_name", ""),
            "sbom_augmentation_url": sbom_augmentation_url,
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _process_setup(self, request: HttpRequest) -> HttpResponse:
        from sbomify.apps.core.apis import _check_billing_limits
        from sbomify.apps.sboms.utils import (
            create_default_component_metadata,
            populate_component_metadata_native_fields,
        )

        team_key = request.session["current_team"]["key"]
        team = Team.objects.get(key=team_key)
        sbom_augmentation_url = getattr(settings, "SBOM_AUGMENTATION_URL", DEFAULT_SBOM_AUGMENTATION_URL)

        form = OnboardingCompanyForm(request.POST)
        if form.is_valid():
            company_name = form.cleaned_data["company_name"]

            can_create_product, product_error, _ = _check_billing_limits(team.id, "product")
            if not can_create_product:
                messages.error(request, product_error)
                return redirect("teams:onboarding_wizard")

            can_create_project, project_error, _ = _check_billing_limits(team.id, "project")
            if not can_create_project:
                messages.error(request, project_error)
                return redirect("teams:onboarding_wizard")

            can_create_component, component_error, _ = _check_billing_limits(team.id, "component")
            if not can_create_component:
                messages.error(request, component_error)
                return redirect("teams:onboarding_wizard")

            try:
                with transaction.atomic():
                    website_url = form.cleaned_data.get("website")
                    contact_name = form.cleaned_data["contact_name"]
                    contact_email = (form.cleaned_data.get("email") or "").strip() or request.user.email

                    contact_profile, created = ContactProfile.objects.get_or_create(
                        team=team, is_default=True, defaults={"name": "Default"}
                    )

                    entity, entity_created = ContactEntity.objects.get_or_create(
                        profile=contact_profile,
                        name=company_name,
                        defaults={
                            "email": contact_email,
                            "website_urls": [website_url] if website_url else [],
                            "is_manufacturer": True,
                            "is_supplier": True,
                        },
                    )

                    contact, created = ContactProfileContact.objects.get_or_create(
                        entity=entity,
                        name=contact_name,
                        email=contact_email,
                        defaults={"is_author": True},
                    )
                    if not created and not contact.is_author:
                        contact.is_author = True
                        contact.save(update_fields=["is_author"])

                    is_public = not team.can_be_private()
                    product, _ = Product.objects.get_or_create(
                        name=company_name, team=team, defaults={"is_public": is_public}
                    )
                    project, _ = Project.objects.get_or_create(
                        name="Main Project", team=team, defaults={"is_public": is_public}
                    )

                    component_metadata = create_default_component_metadata(
                        user=request.user, team_id=team.id, custom_metadata=None
                    )

                    component, component_created = Component.objects.get_or_create(
                        name="Main Component",
                        team=team,
                        defaults={
                            "component_type": Component.ComponentType.SBOM,
                            "metadata": component_metadata,
                            "visibility": Component.Visibility.PUBLIC if is_public else Component.Visibility.PRIVATE,
                        },
                    )

                    if component_created:
                        populate_component_metadata_native_fields(component, request.user, custom_metadata=None)
                        component.save()

                    product.projects.add(project)
                    project.components.add(component)

                    team.name = format_workspace_name(company_name)
                    team.has_completed_wizard = True
                    team.onboarding_goal = form.cleaned_data.get("goal", "")
                    team.save()

                    update_user_teams_session(request, request.user)
                    refresh_current_team_session(request, team)

                    request.session["wizard_component_id"] = component.id
                    request.session["wizard_company_name"] = company_name
                    request.session.modified = True
                    request.session.save()

                messages.success(request, "Your SBOM identity has been set up!")
                return redirect(f"{reverse('teams:onboarding_wizard')}?step=complete")
            except IntegrityError as e:
                log.warning(f"IntegrityError during onboarding for team {team.key}, company_name='{company_name}': {e}")
                messages.warning(
                    request,
                    "Setup could not be completed due to a conflict. Please try again or contact support.",
                )

        context = {
            "form": form,
            "current_step": "setup",
            "sbom_augmentation_url": sbom_augmentation_url,
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)
