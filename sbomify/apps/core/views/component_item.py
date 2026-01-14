from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import _build_item_response, get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_public_path,
    get_workspace_public_url,
    resolve_component_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.documents.apis import get_document
from sbomify.apps.plugins.public_assessment_utils import get_sbom_passing_assessments, passing_assessments_to_dict
from sbomify.apps.sboms.apis import get_sbom
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.vulnerability_scanning.models import VulnerabilityScanResult


class ComponentItemPublicView(View):
    def get(self, request: HttpRequest, component_id: str, item_type: str, item_id: str) -> HttpResponse:
        # Resolve component by slug (on custom domains) or ID (on main app)
        component_obj = resolve_component_identifier(request, component_id)
        if not component_obj:
            return error_response(request, HttpResponseNotFound("Component not found"))

        # Use the resolved component's ID for API calls
        resolved_id = component_obj.id
        component_slug = component_obj.slug

        status_code, component = get_component(request, resolved_id, return_instance=True)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        if item_type == "sboms":
            status_code, item = get_sbom(request, item_id)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=item.get("detail", "Unknown error"))
                )

        elif item_type == "documents":
            status_code, item = get_document(request, item_id)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=item.get("detail", "Unknown error"))
                )

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if component.team and (
            should_redirect_to_custom_domain(request, component.team) or should_redirect_to_clean_url(request)
        ):
            path = get_public_path(
                "component",
                resolved_id,
                is_custom_domain=True,
                slug=component_slug,
                item_type=item_type,
                item_id=item_id,
            )
            return HttpResponseRedirect(build_custom_domain_url(component.team, path, request.is_secure()))

        brand = build_branding_context(component.team)

        # Get workspace public URL for breadcrumbs
        workspace_public_url = get_workspace_public_url(request, component.team)

        # Get passing assessments for SBOMs
        passing_assessments = []
        if item_type == "sboms":
            sbom_passing = get_sbom_passing_assessments(item_id)
            passing_assessments = passing_assessments_to_dict(sbom_passing)

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "brand": brand,
            "item": item,
            "item_type": item_type,
            "component": _build_item_response(request, component, "component"),
            "passing_assessments": passing_assessments,
            "workspace_public_url": workspace_public_url,
        }
        add_custom_domain_to_context(request, context, component.team)

        return render(request, "core/component_item_public.html.j2", context)


class ComponentItemView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            return ComponentItemPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, component_id: str, item_type: str, item_id: str) -> HttpResponse:
        vulnerability_summary = None
        assessment_runs = None

        if item_type == "sboms":
            status_code, item = get_sbom(request, item_id)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=item.get("detail", "Unknown error"))
                )
            # Get latest vulnerability scan for this SBOM
            # Use component_id from item to ensure team access (defense in depth)
            component_id_from_item = item.get("component_id") or component_id
            latest_scan = (
                VulnerabilityScanResult.objects.filter(sbom_id=item_id, sbom__component_id=component_id_from_item)
                .select_related("sbom__component")
                .order_by("-created_at")
                .first()
            )
            if latest_scan:
                vulnerability_summary = {
                    "total": latest_scan.total_vulnerabilities,
                    "critical": latest_scan.critical_vulnerabilities,
                    "high": latest_scan.high_vulnerabilities,
                    "medium": latest_scan.medium_vulnerabilities,
                    "low": latest_scan.low_vulnerabilities,
                    "provider": latest_scan.provider,
                    "scan_date": latest_scan.created_at,
                }

            # Get assessment runs for this SBOM
            try:
                from sbomify.apps.plugins.apis import get_sbom_assessments

                # Create a mock request object with the sbom_id parameter
                assessment_response = get_sbom_assessments(request, item_id)
                # Use mode='json' to ensure datetime objects are serialized as ISO strings
                assessment_runs = assessment_response.model_dump(mode="json")
            except Exception:
                # If assessment fetch fails, continue without it
                assessment_runs = None

        elif item_type == "documents":
            status_code, item = get_document(request, item_id)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=item.get("detail", "Unknown error"))
                )

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        return render(
            request,
            "core/component_item.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "item": item,
                "item_type": item_type,
                "component_id": component_id,
                "vulnerability_summary": vulnerability_summary,
                "assessment_runs": assessment_runs,
            },
        )
