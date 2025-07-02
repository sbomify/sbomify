import json
import logging
import tempfile
import typing
from pathlib import Path

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

import redis
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout as django_logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse

from access_tokens.models import AccessToken
from access_tokens.utils import create_personal_access_token
from core.utils import token_to_number, verify_item_access
from sboms.models import SBOM  # SBOM still lives in sboms app
from sboms.utils import get_product_sbom_package, get_project_sbom_package
from teams.schemas import BrandingInfo

from .errors import error_response
from .forms import CreateAccessTokenForm
from .models import Component, Product, Project

logger = logging.getLogger(__name__)


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return redirect("core:keycloak_login")


def keycloak_login(request: HttpRequest) -> HttpResponse:
    """Render the Allauth default login page on /login."""
    return render(request, "account/login.html.j2")


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    context = {"current_team": request.session.get("current_team", {})}
    return render(request, "core/dashboard.html.j2", context)


@login_required
def user_settings(request: HttpRequest) -> HttpResponse:
    create_access_token_form = CreateAccessTokenForm()
    context = dict(create_access_token_form=create_access_token_form)

    if request.method == "POST":
        form = CreateAccessTokenForm(request.POST)
        if form.is_valid():
            access_token_str = create_personal_access_token(request.user)
            token = AccessToken(
                encoded_token=access_token_str,
                user=request.user,
                description=form.cleaned_data["description"],
            )
            token.save()

            context["new_encoded_access_token"] = access_token_str
            messages.add_message(
                request,
                messages.INFO,
                "New access token created",
            )

    access_tokens = AccessToken.objects.filter(user=request.user).only("id", "description", "created_at").all()
    # Serialize access tokens for Vue component
    access_tokens_data = [
        {"id": str(token.id), "description": token.description, "created_at": token.created_at.isoformat()}
        for token in access_tokens
    ]
    context["access_tokens"] = access_tokens_data
    return render(request, "core/settings.html.j2", context)


@login_required
def delete_access_token(request: HttpRequest, token_id: int):
    try:
        token = AccessToken.objects.get(pk=token_id)

        if token.user_id != request.user.id:
            return error_response(request, HttpResponseForbidden("Not allowed"))

        messages.add_message(
            request,
            messages.INFO,
            "Access token removed",
        )
        token.delete()

    except AccessToken.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Access token not found"))

    return redirect(reverse("core:settings"))


@login_required
def logout(request: HttpRequest) -> HttpResponse:
    django_logout(request)
    # Redirect to Keycloak logout page
    redirect_url = (
        f"{settings.KEYCLOAK_SERVER_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/logout"
        f"?redirect_uri={settings.APP_BASE_URL}"
    )
    return redirect(redirect_url)


def login_error(request: HttpRequest) -> HttpResponse:
    """Handle login errors and display more information."""
    error_message = request.GET.get("error", "Unknown error occurred during authentication")
    error_description = request.GET.get("error_description", "No additional information available")

    context = {"error_message": error_message, "error_description": error_description}
    return render(request, "socialaccount/authentication_error.html.j2", context)


def keycloak_webhook(request: HttpRequest) -> HttpResponse:
    """Handle Keycloak webhook events.

    This endpoint receives events from Keycloak when properly configured with a
    webhook extension. It processes user-related events like account deletion
    and profile updates.

    Args:
        request: The HTTP request object containing the webhook payload

    Returns:
        HttpResponse: Response indicating success or failure of event processing
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    # Verify webhook secret if configured
    webhook_secret = getattr(settings, "KEYCLOAK_WEBHOOK_SECRET", None)
    if webhook_secret:
        received_secret = request.headers.get("X-Keycloak-Secret")
        if not received_secret or received_secret != webhook_secret:
            logger.warning("Invalid webhook secret received")
            return HttpResponseForbidden("Invalid webhook secret")

    from allauth.socialaccount.models import SocialAccount

    try:
        data = json.loads(request.body)
        event_type = data.get("type")
        user_id = data.get("userId")
        event_time = data.get("time")
        details = data.get("details", {})

        if not user_id:
            return HttpResponse(status=204)  # No content to process

        logger.info(f"Received Keycloak webhook event: {event_type} for user {user_id} at {event_time}")

        # Handle different event types
        if event_type == "DELETE_ACCOUNT":
            try:
                social_account = SocialAccount.objects.get(uid=user_id)
                django_user = social_account.user
                django_user.is_active = False
                django_user.save()
                logger.info(
                    f"Deactivated user {django_user.username} (ID: {django_user.id}) after Keycloak account deletion"
                )
            except SocialAccount.DoesNotExist:
                logger.warning(f"Cannot find Django user for Keycloak user ID {user_id}")

        elif event_type == "UPDATE_PROFILE":
            try:
                social_account = SocialAccount.objects.get(uid=user_id)
                django_user = social_account.user

                # Update email if changed
                if "email" in details:
                    django_user.email = details["email"]
                    django_user.save()
                    logger.info(f"Updated email for user {django_user.username} to {details['email']}")

                # Update extra_data in social account
                social_account.extra_data.update(details)
                social_account.save()

            except SocialAccount.DoesNotExist:
                logger.warning(f"Cannot find Django user for Keycloak user ID {user_id}")

        elif event_type in ["LOGIN", "LOGOUT"]:
            # Log these events for audit purposes
            logger.info(f"User {user_id} performed {event_type} from IP {details.get('ipAddress', 'unknown')}")

        return HttpResponse(status=200)

    except json.JSONDecodeError:
        logger.error("Invalid JSON received in webhook payload")
        return HttpResponse("Invalid JSON", status=400)
    except Exception as e:
        logger.error(f"Error processing Keycloak webhook: {e}", exc_info=True)
        return HttpResponse("Error processing webhook", status=500)


# ============================================================================
# Product/Project/Component Views - Moved from sboms app
# ============================================================================


@login_required
def products_dashboard(request: HttpRequest) -> HttpResponse:
    has_crud_permissions = request.session.get("current_team").get("role") in ("owner", "admin")

    return render(
        request,
        "core/products_dashboard.html.j2",
        {
            "has_crud_permissions": has_crud_permissions,
        },
    )


def product_details_public(request: HttpRequest, product_id: str) -> HttpResponse:
    try:
        product: Product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Product not found"))

    # Verify access to project
    if not product.is_public:
        return error_response(request, HttpResponseNotFound("Product not found"))

    branding_info = BrandingInfo(**product.team.branding_info)
    return render(
        request,
        "core/product_details_public.html.j2",
        {"product": product, "brand": branding_info},
    )


@login_required
def product_details_private(request: HttpRequest, product_id: str) -> HttpResponse:
    try:
        product: Product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Product not found"))

    # Verify access to project
    if not verify_item_access(request, product, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    has_crud_permissions = verify_item_access(request, product, ["owner", "admin"])

    return render(
        request,
        "core/product_details_private.html.j2",
        {
            "product": product,
            "has_crud_permissions": has_crud_permissions,
            "APP_BASE_URL": settings.APP_BASE_URL,
            "current_team": request.session.get("current_team", {}),
        },
    )


@login_required
def projects_dashboard(request: HttpRequest) -> HttpResponse:
    has_crud_permissions = request.session.get("current_team").get("role") in ("owner", "admin")

    return render(
        request,
        "core/projects_dashboard.html.j2",
        {
            "has_crud_permissions": has_crud_permissions,
        },
    )


def project_details_public(request: HttpRequest, project_id: str) -> HttpResponse:
    try:
        project: Project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Project not found"))

    # Verify access to project
    if not project.is_public:
        return error_response(request, HttpResponseNotFound("Project not found"))

    branding_info = BrandingInfo(**project.team.branding_info)

    return render(
        request,
        "core/project_details_public.html.j2",
        {"project": project, "brand": branding_info},
    )


@login_required
def project_details_private(request: HttpRequest, project_id: str) -> HttpResponse:
    try:
        project: Project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Project not found"))

    # Verify access to project
    if not verify_item_access(request, project, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    has_crud_permissions = verify_item_access(request, project, ["owner", "admin"])

    return render(
        request,
        "core/project_details_private.html.j2",
        {
            "project": project,
            "has_crud_permissions": has_crud_permissions,
            "APP_BASE_URL": settings.APP_BASE_URL,
            "current_team": request.session.get("current_team", {}),
        },
    )


@login_required
def components_dashboard(request: HttpRequest) -> HttpResponse:
    has_crud_permissions = request.session.get("current_team").get("role") in ("owner", "admin")

    return render(
        request,
        "core/components_dashboard.html.j2",
        {
            "has_crud_permissions": has_crud_permissions,
            "APP_BASE_URL": settings.APP_BASE_URL,
        },
    )


def component_details_public(request: HttpRequest, component_id: str) -> HttpResponse:
    try:
        component: Component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Component not found"))

    # Verify access to project
    if not component.is_public:
        return error_response(request, HttpResponseNotFound("Component not found"))

    sboms_queryset = SBOM.objects.filter(component_id=component_id).order_by("-created_at").all()
    sboms_with_vuln_status = []
    try:
        redis_client = redis.from_url(settings.REDIS_WORKER_URL)
        for sbom_item in sboms_queryset:
            keys = redis_client.keys(f"osv_scan_result:{sbom_item.id}:*")
            sboms_with_vuln_status.append(
                {
                    "sbom": {
                        "id": str(sbom_item.id),
                        "name": sbom_item.name,
                        "format": sbom_item.format,
                        "format_version": sbom_item.format_version,
                        "version": sbom_item.version,
                        "created_at": sbom_item.created_at.isoformat(),
                    },
                    "has_vulnerabilities_report": bool(keys),
                }
            )
    except redis.exceptions.ConnectionError:
        for sbom_item in sboms_queryset:
            sboms_with_vuln_status.append(
                {
                    "sbom": {
                        "id": str(sbom_item.id),
                        "name": sbom_item.name,
                        "format": sbom_item.format,
                        "format_version": sbom_item.format_version,
                        "version": sbom_item.version,
                        "created_at": sbom_item.created_at.isoformat(),
                    },
                    "has_vulnerabilities_report": False,
                }
            )
        # No messages.error for public view, just log or fail silently
        # logger.warning("Could not connect to Redis in public component view.")

    branding_info = BrandingInfo(**component.team.branding_info)

    return render(
        request,
        "core/component_details_public.html.j2",
        {"component": component, "sboms_data": sboms_with_vuln_status, "brand": branding_info},  # Changed from "sboms"
    )


@login_required
def component_details_private(request: HttpRequest, component_id: str) -> HttpResponse:
    try:
        component: Component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Component not found"))

    # Verify access to project
    if not verify_item_access(request, component, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    has_crud_permissions = verify_item_access(request, component, ["owner", "admin"])
    is_owner = verify_item_access(request, component, ["owner"])

    sboms_queryset = SBOM.objects.filter(component_id=component_id).order_by("-created_at").all()
    sboms_with_vuln_status = []
    try:
        redis_client = redis.from_url(settings.REDIS_WORKER_URL)
        for sbom_item in sboms_queryset:
            keys = redis_client.keys(f"osv_scan_result:{sbom_item.id}:*")
            sboms_with_vuln_status.append(
                {
                    "sbom": {
                        "id": str(sbom_item.id),
                        "name": sbom_item.name,
                        "format": sbom_item.format,
                        "format_version": sbom_item.format_version,
                        "version": sbom_item.version,
                        "created_at": sbom_item.created_at.isoformat(),
                    },
                    "has_vulnerabilities_report": bool(keys),
                }
            )
    except redis.exceptions.ConnectionError:
        # If Redis is down, assume no reports are available for simplicity
        for sbom_item in sboms_queryset:
            sboms_with_vuln_status.append(
                {
                    "sbom": {
                        "id": str(sbom_item.id),
                        "name": sbom_item.name,
                        "format": sbom_item.format,
                        "format_version": sbom_item.format_version,
                        "version": sbom_item.version,
                        "created_at": sbom_item.created_at.isoformat(),
                    },
                    "has_vulnerabilities_report": False,
                }
            )
        messages.error(
            request, "Could not connect to Redis to check for vulnerability reports. Status may be inaccurate."
        )

    return render(
        request,
        "core/component_details_private.html.j2",
        {
            "component": component,
            "has_crud_permissions": has_crud_permissions,
            "is_owner": is_owner,
            "sboms_data": sboms_with_vuln_status,  # Changed from "sboms"
            "APP_BASE_URL": settings.APP_BASE_URL,
            "current_team": request.session.get("current_team", {}),
        },
    )


@login_required
def transfer_component_to_team(request: HttpRequest, component_id: str) -> HttpResponse:
    """
    Transfer component to a different team.

    User must have owner role in component's current team and owner or admin role in target team.
    """
    if request.method != "POST":
        return error_response(request, HttpResponseBadRequest("Invalid request"))

    team_key = request.POST.get("team_key")
    team_id = token_to_number(team_key)

    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Component not found"))

    if not verify_item_access(request, component, ["owner"]):
        return error_response(request, HttpResponseForbidden("Only allowed for owners of the component"))

    target_team = request.session.get("user_teams", {}).get(team_key, {})
    if target_team.get("role", "") not in ("owner", "admin"):
        return error_response(request, HttpResponseForbidden("Only allowed for admins or owners of the target team"))

    with transaction.atomic():
        # Remove component's existing linkages to projects if any
        component.projects.clear()
        component.team_id = team_id
        component.save()

    messages.add_message(
        request,
        messages.INFO,
        f"Component {component.name} transferred to team {target_team.get('name')}",
    )

    return redirect("core:component_details", component_id=component_id)


def sbom_download_project(request: HttpRequest, project_id: str) -> HttpResponse:
    """
    Download a zip file containing the SBOMs for all components in a project.
    """
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Project not found"))

    if not project.is_public:
        if not verify_item_access(request, project, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    with tempfile.TemporaryDirectory() as temp_dir:
        sbom_zip_path = get_project_sbom_package(project, Path(temp_dir))

        response = HttpResponse(open(sbom_zip_path, "rb").read(), content_type="application/zip")
        response["Content-Disposition"] = f"attachment; filename={project.name}.cdx.zip"

        return response


def sbom_download_product(request: HttpRequest, product_id: str) -> HttpResponse:
    """
    Download a zip file containing the SBOMs for all projects in a product.
    """
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Product not found"))

    if not product.is_public:
        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    with tempfile.TemporaryDirectory() as temp_dir:
        sbom_zip_path = get_product_sbom_package(product, Path(temp_dir))

        response = HttpResponse(open(sbom_zip_path, "rb").read(), content_type="application/zip")
        response["Content-Disposition"] = f"attachment; filename={product.name}.cdx.zip"

        return response


@login_required
def get_component_metadata(request: HttpRequest, component_id: str) -> HttpResponse:
    try:
        component: Component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Component not found"))

    if not verify_item_access(request, component, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    metadata = component.metadata or {}
    metadata.setdefault("supplier", None)
    return JsonResponse(metadata)
