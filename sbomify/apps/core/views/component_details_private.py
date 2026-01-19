from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ComponentDetailsPrivateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            from sbomify.apps.core.views.component_details_public import ComponentDetailsPublicView

            return ComponentDetailsPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team", {})
        is_owner = current_team.get("role") == "owner"
        billing_plan = current_team.get("billing_plan")

        # Get company NDA ID for visibility selector and check if gated visibility is allowed
        company_nda_id = None
        gated_visibility_allowed = False
        team_key = current_team.get("key")
        team_id = component.get("team_id")
        if team_id:
            from sbomify.apps.teams.models import Team

            try:
                team = Team.objects.get(pk=team_id)
                if not team_key:
                    team_key = team.key
                company_nda = team.get_company_nda_document()
                if company_nda:
                    company_nda_id = company_nda.id
                # Check if gated visibility is allowed (Business or Enterprise plans)
                gated_visibility_allowed = team.can_be_private()
            except Team.DoesNotExist:
                pass

        # Build mapping of document types to their subcategory choices for dynamic dropdowns
        import json

        from sbomify.apps.documents.models import Document

        document_type_subcategories = {}
        for doc_type_value, doc_type_label in Document.DocumentType.choices:
            if doc_type_value == Document.DocumentType.COMPLIANCE:
                document_type_subcategories[doc_type_value] = {
                    "field_name": "compliance_subcategory",
                    "choices": Document.ComplianceSubcategory.choices,
                    "label": "Compliance Subcategory",
                }
            # Add more document types with subcategories here as needed

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "component": component,
            "current_team": current_team,
            "is_owner": is_owner,
            "team_billing_plan": billing_plan,
            "company_nda_id": company_nda_id,
            "gated_visibility_allowed": gated_visibility_allowed,
            "team_key": team_key,
            "document_type_subcategories": document_type_subcategories,
            "document_type_subcategories_json": json.dumps(document_type_subcategories),
        }

        component_type = component.get("component_type")
        if component_type == "sbom":
            template_name = "core/component_details_private_sbom.html.j2"
        elif component_type == "document":
            template_name = "core/component_details_private_document.html.j2"
        else:
            return error_response(request, HttpResponse(status=400, content="Invalid component type"))

        return render(request, template_name, context)
