"""Save onboarding identity and security settings in one transaction."""

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.models import User
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import (
    ContactEntity,
    ContactProfile,
    ContactProfileContact,
    Member,
    Team,
    default_patch_sla_days,
    format_workspace_name,
)
from sbomify.apps.teams.services.security_txt import clean_expires
from sbomify.logging import getLogger

log = getLogger(__name__)


@dataclass(frozen=True)
class SetupResult:
    workspace: Team
    warning: str = ""


def complete_workspace_setup(workspace: Team, user: User, data: dict[str, Any]) -> ServiceResult[SetupResult]:
    try:
        with transaction.atomic():
            workspace = Team.objects.select_for_update().get(pk=workspace.pk)
            if not Member.objects.filter(team=workspace, user=user, role__in=ADMINISTER).exists():
                return ServiceResult.failure("You cannot configure this workspace.", status_code=403)
            if workspace.is_payment_restricted:
                return ServiceResult.failure("Update your payment method before continuing.", status_code=403)

            company_name = data["company_name"]
            contact_email = data.get("email") or user.email
            profile, _ = ContactProfile.objects.get_or_create(
                team=workspace, is_default=True, defaults={"name": "Default"}
            )
            entity = ContactEntity.objects.filter(profile=profile, is_manufacturer=True).first()
            warning = ""
            if entity:
                if ContactEntity.objects.filter(profile=profile, name=company_name).exclude(pk=entity.pk).exists():
                    warning = f'Another entity named "{company_name}" already exists, kept the previous name.'
                else:
                    entity.name = company_name
            else:
                entity = ContactEntity(profile=profile, name=company_name, is_manufacturer=True)
            entity.email = contact_email
            entity.is_supplier = True
            entity.address = data.get("address", "")
            if data.get("website"):
                entity.website_urls = [data["website"]]
            entity.save()

            author, created = ContactProfileContact.objects.get_or_create(
                entity=entity, name=data["contact_name"], email=contact_email, defaults={"is_author": True}
            )
            if not created and not author.is_author:
                author.is_author = True
                author.save(update_fields=["is_author"])

            if data.get("security_email"):
                security_contact = ContactProfileContact.objects.filter(
                    entity__profile=profile, is_security_contact=True
                ).first()
                if security_contact and security_contact.email != data["security_email"]:
                    security_contact.is_security_contact = False
                    security_contact.save(update_fields=["is_security_contact"])
                if security_contact and security_contact.email == data["security_email"]:
                    contact = security_contact
                else:
                    contact, _ = ContactProfileContact.objects.get_or_create(
                        entity=entity,
                        email=data["security_email"],
                        name=data["contact_name"] if data["security_email"] == contact_email else "Security contact",
                    )
                contact.is_security_contact = True
                contact.full_clean()
                contact.save(update_fields=["is_security_contact"])
                if data.get("publish_security_txt"):
                    workspace.security_txt_config = {
                        **workspace.security_txt_config,
                        "enabled": True,
                        "contact_id": contact.pk,
                        "expires": clean_expires(workspace.security_txt_config.get("expires", "")),
                    }

            workspace.name = format_workspace_name(company_name)
            workspace.has_completed_wizard = True
            workspace.onboarding_goal = data.get("goal", "")
            workspace.default_support_period_years = data.get("default_support_period_years")
            workspace.patch_sla_days = (
                {severity: data.get(severity) for severity in default_patch_sla_days()}
                if data.get("mode") == "custom"
                else default_patch_sla_days()
            )
            workspace.save(
                update_fields=[
                    "name",
                    "has_completed_wizard",
                    "onboarding_goal",
                    "patch_sla_days",
                    "security_txt_config",
                    "default_support_period_years",
                ]
            )
            return ServiceResult.success(SetupResult(workspace, warning))
    except (IntegrityError, ValidationError):
        return ServiceResult.failure(
            "Setup could not be completed due to a conflict. Please try again or contact support."
        )


def build_onboarding_plan_context(request: HttpRequest, workspace: Team, plan_hint: str) -> dict[str, Any]:
    from sbomify.apps.billing.services.plan_selection import build_plan_selection_context
    from sbomify.apps.billing.stripe_pricing_service import StripePricingService

    try:
        pricing = StripePricingService().get_all_plans_pricing()
    except Exception:
        log.exception("Failed to fetch onboarding plan pricing")
        pricing = {}
    selection = build_plan_selection_context(request, workspace, pricing).value or {}
    return {
        "plan_cards": [
            {**plan, "current": False}
            for plan in selection.get("plans", [])
            if plan["key"] in {"community", "business", "enterprise"}
        ],
        "plan_selection_data": selection.get("plan_selection_data", {}),
        "plan_hint": plan_hint,
        "trial_days": settings.TRIAL_PERIOD_DAYS,
    }
