from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_back_url_from_referrer,
    get_public_path,
    get_workspace_public_url,
    resolve_component_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.plugins.public_assessment_utils import get_component_assessment_status, passing_assessments_to_dict
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ComponentDetailsPublicView(View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        # Resolve component by slug (on custom domains) or ID (on main app)
        component_obj = resolve_component_identifier(request, component_id)
        if not component_obj:
            return error_response(request, HttpResponseNotFound("Component not found"))

        # Check if component is visible to public (public or gated)
        # Private components should not be accessible via public URL
        from sbomify.apps.sboms.models import Component as SbomComponent

        if component_obj.visibility == SbomComponent.Visibility.PRIVATE:
            return error_response(request, HttpResponseForbidden("Access denied"))

        # Use the resolved component's ID for API calls
        resolved_id = component_obj.id

        status_code, component = get_component(request, resolved_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        team = Team.objects.filter(pk=component.get("team_id")).first()

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if team and (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
            path = get_public_path("component", resolved_id, is_custom_domain=True, slug=component_obj.slug)
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

        # Get assessment status for this component (only passing assessments)
        assessment_status = get_component_assessment_status(component_obj)
        passing_assessments = passing_assessments_to_dict(assessment_status.passing_assessments)

        # Find the parent product (via project) for the back link fallback
        is_custom_domain = getattr(request, "is_custom_domain", False)
        parent_product = None
        parent_product_url = None
        public_projects = component_obj.projects.filter(is_public=True)
        if public_projects.exists():
            project = public_projects.first()
            public_products = project.products.filter(is_public=True)
            if public_products.exists():
                parent_product = public_products.first()
                if is_custom_domain:
                    parent_product_url = f"/product/{parent_product.slug or parent_product.id}/"
                else:
                    from django.urls import reverse

                    parent_product_url = reverse(
                        "core:product_details_public", kwargs={"product_id": parent_product.id}
                    )

        # Generate workspace URL based on context
        workspace_public_url = get_workspace_public_url(request, team)

        # Calculate fallback URL for back link (parent product or workspace)
        fallback_url = parent_product_url or workspace_public_url

        # Get back URL from referrer, with fallback to parent product or workspace
        back_url = get_back_url_from_referrer(request, team, fallback_url)

        # Check access using centralized access control
        from sbomify.apps.core.services.access_control import check_component_access
        from sbomify.apps.documents.access_models import AccessRequest
        from sbomify.apps.teams.models import Member

        # First check if user would have access (member or approved request) without NDA check
        would_have_access = False
        if request.user.is_authenticated and component_obj.visibility == SbomComponent.Visibility.GATED:
            # Check for approved access request
            if AccessRequest.objects.filter(
                team=team, user=request.user, status=AccessRequest.Status.APPROVED
            ).exists():
                would_have_access = True
            # Check if user is a member
            elif Member.objects.filter(team=team, user=request.user).exists():
                would_have_access = True

        # Now check actual access (which includes NDA check)
        access_result = check_component_access(request, component_obj, team)

        # Set session flag to indicate user is viewing a public component
        # This helps download views provide better error messages
        request.session["viewing_public_component"] = str(component_obj.id)
        request.session.save()

        # Check if user would have access but hasn't signed the current NDA
        # This handles cases where user is a member or has approved request but NDA is required
        # Note: Owners/admins are exempt from NDA requirement
        needs_nda_signing = False
        nda_access_request_id = None
        if (
            request.user.is_authenticated
            and component_obj.visibility == SbomComponent.Visibility.GATED
            and would_have_access
        ):
            # Check if user is an owner/admin member - they don't need to sign NDA
            is_owner_or_admin = False
            try:
                member = Member.objects.get(team=team, user=request.user)
                if member.role in ("owner", "admin"):
                    is_owner_or_admin = True
            except Member.DoesNotExist:
                # User is not a member, continue with access check
                pass

            # Only check NDA for guests and users with APPROVED AccessRequest
            if not is_owner_or_admin:
                from sbomify.apps.documents.views.access_requests import user_has_signed_current_nda

                # Check if NDA is required and user hasn't signed it
                if not user_has_signed_current_nda(request.user, team):
                    # Get or create access request for this user
                    access_request, created = AccessRequest.objects.get_or_create(
                        team=team,
                        user=request.user,
                        defaults={"status": AccessRequest.Status.APPROVED},
                    )
                    # If access request was already approved, keep it approved
                    # But user still needs to sign NDA to access
                    if not created and access_request.status != AccessRequest.Status.APPROVED:
                        access_request.status = AccessRequest.Status.APPROVED
                        access_request.save()

                    needs_nda_signing = True
                    nda_access_request_id = access_request.id

                    # Store return URL in session for after NDA signing
                    return_url = request.get_full_path()
                    request.session["nda_signing_return_url"] = return_url
                    request.session.modified = True

        # Extract access details for template context
        # If needs_nda_signing is True, we show the NDA message instead of "Access Granted"
        user_has_gated_access = (
            access_result.has_access
            and component_obj.visibility == SbomComponent.Visibility.GATED
            and not needs_nda_signing
        )
        access_request_status = access_result.access_request_status
        pending_request_needs_nda = False
        pending_request_id = None

        # Check if pending request needs NDA signing
        if access_request_status == "pending" and request.user.is_authenticated:
            from sbomify.apps.documents.access_models import AccessRequest, NDASignature

            access_request = (
                AccessRequest.objects.filter(team=team, user=request.user, status=AccessRequest.Status.PENDING)
                .order_by("-requested_at")
                .first()
            )

            if access_request:
                company_nda = team.get_company_nda_document()
                if company_nda:
                    has_signed = NDASignature.objects.filter(access_request=access_request).exists()
                    if not has_signed:
                        pending_request_needs_nda = True
                        pending_request_id = access_request.id

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "component": component,
            "component_obj": component_obj,  # Pass actual model for visibility checks
            "passing_assessments": passing_assessments,
            "has_passing_assessments": assessment_status.all_pass,
            "parent_product": parent_product,
            "parent_product_url": parent_product_url,
            "back_url": back_url,
            "fallback_url": fallback_url,
            "user_has_gated_access": user_has_gated_access,
            "access_request_status": access_request_status,
            "pending_request_needs_nda": pending_request_needs_nda,
            "pending_request_id": pending_request_id,
            "needs_nda_signing": needs_nda_signing,
            "nda_access_request_id": nda_access_request_id,
            "team": team,
        }

        brand = build_branding_context(team)

        current_team = request.session.get("current_team") or {}
        team_billing_plan = getattr(team, "billing_plan", None) or current_team.get("billing_plan")

        context.update(
            {
                "brand": brand,
                "team_billing_plan": team_billing_plan,
                "workspace_public_url": workspace_public_url,
            }
        )
        add_custom_domain_to_context(request, context, team)

        component_type = component.get("component_type")
        if component_type == "sbom":
            template_name = "core/component_details_public_sbom.html.j2"
        elif component_type == "document":
            template_name = "core/component_details_public_document.html.j2"
        else:
            return error_response(request, HttpResponse(status=400, content="Invalid component type"))

        return render(request, template_name, context)
