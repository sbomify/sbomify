import json
import logging
import tempfile
import typing
from pathlib import Path
from urllib.parse import urlencode, urljoin

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

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
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.utils import token_to_number, verify_item_access
from sbomify.apps.core.views.component_details_private import ComponentDetailsPrivateView  # noqa: F401, E402
from sbomify.apps.core.views.component_details_public import ComponentDetailsPublicView  # noqa: F401, E402
from sbomify.apps.core.views.component_item import ComponentItemPublicView, ComponentItemView  # noqa: F401, E402
from sbomify.apps.core.views.component_scope import ComponentScopeView  # noqa: F401, E402
from sbomify.apps.core.views.components_dashboard import ComponentsDashboardView  # noqa: F401, E402
from sbomify.apps.core.views.dashboard import DashboardView  # noqa: F401, E402
from sbomify.apps.core.views.product_details_private import ProductDetailsPrivateView  # noqa: F401, E402
from sbomify.apps.core.views.product_details_public import ProductDetailsPublicView  # noqa: F401, E402
from sbomify.apps.core.views.product_releases_private import ProductReleasesPrivateView  # noqa: F401, E402
from sbomify.apps.core.views.product_releases_public import ProductReleasesPublicView  # noqa: F401, E402
from sbomify.apps.core.views.products_dashboard import ProductsDashboardView  # noqa: F401, E402
from sbomify.apps.core.views.project_details_private import ProjectDetailsPrivateView  # noqa: F401, E402
from sbomify.apps.core.views.project_details_public import ProjectDetailsPublicView  # noqa: F401, E402
from sbomify.apps.core.views.projects_dashboard import ProjectsDashboardView  # noqa: F401, E402
from sbomify.apps.core.views.release_details_private import ReleaseDetailsPrivateView  # noqa: F401, E402
from sbomify.apps.core.views.release_details_public import ReleaseDetailsPublicView  # noqa: F401, E402
from sbomify.apps.core.views.releases_dashboard import ReleasesDashboardView  # noqa: F401, E402
from sbomify.apps.core.views.toggle_public_status import TogglePublicStatusView  # noqa: F401, E402
from sbomify.apps.core.views.workspace_public import WorkspacePublicView  # noqa: F401, E402
from sbomify.apps.sboms.utils import get_product_sbom_package, get_project_sbom_package

from ..errors import error_response
from ..forms import CreateAccessTokenForm, SupportContactForm
from ..models import Component, Product, Project

logger = logging.getLogger(__name__)


def home(request: HttpRequest) -> HttpResponse:
    # On custom domains, show the workspace Trust Center
    if getattr(request, "is_custom_domain", False):
        return WorkspacePublicView.as_view()(request, workspace_key=None)

    # Standard home page behavior
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return redirect("core:keycloak_login")


def keycloak_login(request: HttpRequest) -> HttpResponse:
    """Send the user directly to the Keycloak login flow handled by Allauth.

    We bypass the bespoke login template so that users always land on the
    native Keycloak login screen. The Allauth provider view builds the correct
    OIDC authorize URL (including callback and state) for us.
    """

    login_path = reverse("openid_connect_login", args=["keycloak"])
    next_param = request.GET.get("next")

    # Validate next parameter to prevent open redirect attacks
    if next_param and url_has_allowed_host_and_scheme(
        next_param,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        login_path = f"{login_path}?{urlencode({'next': next_param})}"

    # Use APP_BASE_URL when provided so redirects work behind proxies/custom domains.
    absolute_login_url = (
        urljoin(settings.APP_BASE_URL.rstrip("/") + "/", login_path.lstrip("/"))
        if getattr(settings, "APP_BASE_URL", None)
        else login_path
    )

    return redirect(absolute_login_url)


@never_cache
@login_required
def user_settings(request: HttpRequest) -> HttpResponse:
    from django.utils import timezone

    from sbomify.apps.teams.models import Invitation

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

    # Fetch pending invitations for the user
    if request.user.email:
        pending_invitations = (
            Invitation.objects.filter(email__iexact=request.user.email, expires_at__gt=timezone.now())
            .select_related("team")
            .order_by("-created_at")
        )
        context["pending_invitations"] = [
            {
                "id": inv.id,
                "token": str(inv.token),
                "team_name": inv.team.display_name,
                "role": inv.role,
                "created_at": inv.created_at,
                "expires_at": inv.expires_at,
            }
            for inv in pending_invitations
        ]
    else:
        context["pending_invitations"] = []

    return render(request, "core/settings.html.j2", context)


@login_required
def accept_user_invitation(request: HttpRequest, invitation_id: int) -> HttpResponse:
    """Accept a pending invitation from user settings."""
    from django.db import transaction
    from django.utils import timezone

    from sbomify.apps.teams.models import Invitation, Member
    from sbomify.apps.teams.utils import can_add_user_to_team, get_user_teams, switch_active_workspace

    if request.method != "POST":
        return error_response(request, HttpResponseBadRequest("Invalid request method"))

    try:
        invitation = Invitation.objects.select_related("team").get(pk=invitation_id)
    except Invitation.DoesNotExist:
        messages.add_message(request, messages.ERROR, "Invitation not found or has already been processed.")
        return redirect("core:settings")

    # Verify invitation belongs to this user
    if (request.user.email or "").lower() != invitation.email.lower():
        messages.add_message(request, messages.ERROR, "This invitation is not for your account.")
        return redirect("core:settings")

    # Check if expired
    if invitation.expires_at <= timezone.now():
        messages.add_message(request, messages.WARNING, "This invitation has expired.")
        invitation.delete()
        return redirect("core:settings")

    # Check if already a member
    if Member.objects.filter(user=request.user, team=invitation.team).exists():
        messages.add_message(request, messages.INFO, f"You are already a member of {invitation.team.display_name}.")
        invitation.delete()
        return redirect("core:settings")

    # Check team capacity
    can_add, error_message = can_add_user_to_team(invitation.team)
    if not can_add:
        messages.add_message(request, messages.ERROR, f"Cannot join {invitation.team.display_name}: {error_message}")
        return redirect("core:settings")

    # Capture team and role before deleting invitation, because the invitation object
    # will be invalidated after deletion and its attributes will no longer be accessible.
    team = invitation.team
    role = invitation.role

    # Create membership in atomic transaction to ensure it's committed
    with transaction.atomic():
        has_default_team = Member.objects.filter(user=request.user, is_default_team=True).exists()
        Member.objects.create(
            user=request.user,
            team=team,
            role=role,
            is_default_team=not has_default_team,
        )
        invitation.delete()

    # Refresh user_teams in session and switch to new workspace
    request.session["user_teams"] = get_user_teams(request.user)
    switch_active_workspace(request, team, role)

    messages.add_message(request, messages.SUCCESS, f"You have joined {team.display_name} as {role}.")

    return redirect("core:dashboard")


@login_required
def reject_user_invitation(request: HttpRequest, invitation_id: int) -> HttpResponse:
    """Reject a pending invitation from user settings."""
    from django.db import transaction

    from sbomify.apps.teams.models import Invitation

    if request.method != "POST":
        return error_response(request, HttpResponseBadRequest("Invalid request method"))

    try:
        invitation = Invitation.objects.select_related("team").get(pk=invitation_id)
    except Invitation.DoesNotExist:
        messages.add_message(request, messages.ERROR, "Invitation not found or has already been processed.")
        return redirect("core:settings")

    # Verify invitation belongs to this user
    if (request.user.email or "").lower() != invitation.email.lower():
        messages.add_message(request, messages.ERROR, "This invitation is not for your account.")
        return redirect("core:settings")

    team_name = invitation.team.display_name

    with transaction.atomic():
        invitation.delete()

    messages.add_message(request, messages.SUCCESS, f"You have declined the invitation to join {team_name}.")
    return redirect("core:settings")


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


def logout(request: HttpRequest) -> HttpResponse:
    """Log the user out of both Django and Keycloak.

    If the user is not authenticated, simply redirect to the login page.
    """
    if not request.user.is_authenticated:
        # User is already logged out, redirect to login
        return redirect(reverse("core:keycloak_login"))

    django_logout(request)
    # Redirect to Keycloak logout endpoint and then straight into its login page.
    # Using post_logout_redirect_uri avoids pausing on the Keycloak "You are logged out" splash.
    base_url = (
        settings.KEYCLOAK_PUBLIC_URL.rstrip("/")
        if hasattr(settings, "KEYCLOAK_PUBLIC_URL")
        else settings.KEYCLOAK_SERVER_URL.rstrip("/")
    )
    realm = settings.KEYCLOAK_REALM
    client_id = settings.KEYCLOAK_CLIENT_ID

    # Where Keycloak should send the user after logout: our login entrypoint,
    # which immediately redirects back into the Keycloak auth flow.
    login_path = reverse("openid_connect_login", args=["keycloak"])
    login_redirect = (
        urljoin(settings.APP_BASE_URL.rstrip("/") + "/", login_path.lstrip("/"))
        if getattr(settings, "APP_BASE_URL", None)
        else request.build_absolute_uri(login_path)
    )

    logout_query = urlencode(
        {
            "client_id": client_id,
            "post_logout_redirect_uri": login_redirect,
        }
    )
    redirect_url = f"{base_url}/realms/{realm}/protocol/openid-connect/logout?{logout_query}"
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

# ============================================================================
# Release Views
# ============================================================================


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
    Download the aggregated SBOM file for all components in a project.
    """
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Project not found"))

    if not project.is_public:
        if not verify_item_access(request, project, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    with tempfile.TemporaryDirectory() as temp_dir:
        sbom_path = get_project_sbom_package(project, Path(temp_dir), user=request.user)

        response = HttpResponse(open(sbom_path, "rb").read(), content_type="application/json")
        response["Content-Disposition"] = f"attachment; filename={project.name}.cdx.json"

        return response


def sbom_download_product(request: HttpRequest, product_id: str) -> HttpResponse:
    """
    Download the aggregated SBOM file for all projects in a product.
    """
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Product not found"))

    if not product.is_public:
        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    with tempfile.TemporaryDirectory() as temp_dir:
        sbom_path = get_product_sbom_package(product, Path(temp_dir), user=request.user)

        response = HttpResponse(open(sbom_path, "rb").read(), content_type="application/json")
        response["Content-Disposition"] = f"attachment; filename={product.name}.cdx.json"

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


@login_required
def support_contact(request: HttpRequest) -> HttpResponse:
    """Display support contact form and handle submissions."""
    from django.core.mail import EmailMessage
    from django.utils import timezone

    if request.method == "POST":
        form = SupportContactForm(request.POST)
        if form.is_valid():
            # Form is valid, proceed with email sending

            try:
                # Get support type display name
                support_type_display = dict(form.fields["support_type"].choices).get(
                    form.cleaned_data["support_type"], "Unknown"
                )

                # Create email subject
                subject = f"[{support_type_display}] {form.cleaned_data['subject']}"

                # Create email content
                message_content = f"""
New Support Request

Support Type: {support_type_display}
Subject: {form.cleaned_data["subject"]}

Contact Information:
- Name: {form.cleaned_data["first_name"]} {form.cleaned_data["last_name"]}
- Email: {form.cleaned_data["email"]}

Browser/System Info: {form.cleaned_data.get("browser_info") or "Not provided"}

Message:
{form.cleaned_data["message"]}

Submitted by: {request.user.email} ({request.user.get_full_name() or request.user.username})
Submitted at: {timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC")}
Source IP: {request.META.get("REMOTE_ADDR", "Unknown")}
User Agent: {request.META.get("HTTP_USER_AGENT", "Unknown")}
"""

                # Send email to support team
                support_email = EmailMessage(
                    subject=subject,
                    body=message_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=["hello@sbomify.com"],
                    reply_to=[form.cleaned_data["email"]],
                )
                support_email.send(fail_silently=False)

                # Send confirmation email to the user
                confirmation_subject = "Thank you for contacting sbomify support"
                confirmation_message = f"""
Hi {form.cleaned_data["first_name"]},

Thank you for reaching out to sbomify support. We have received your message about:

Subject: {form.cleaned_data["subject"]}
Support Type: {support_type_display}

We will review your request and get back to you as soon as possible.
Our typical response time is within 1-2 business days.

If you have any urgent issues, you can reply to this email directly.

Best regards,
The sbomify Support Team

---
Original message:
{form.cleaned_data["message"]}
"""

                confirmation_email = EmailMessage(
                    subject=confirmation_subject,
                    body=confirmation_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[form.cleaned_data["email"]],
                    reply_to=["hello@sbomify.com"],
                )
                confirmation_email.send(fail_silently=False)

                return redirect("core:support_contact_success")

            except Exception as e:
                logger.error(f"Failed to send support contact email: {e}")
                messages.error(
                    request,
                    "Sorry, there was an error sending your message. Please try again later or contact us directly "
                    "at hello@sbomify.com",
                )

    else:
        # Pre-populate form with user information
        initial_data = {
            "first_name": request.user.first_name,
            "last_name": request.user.last_name,
            "email": request.user.email,
        }
        form = SupportContactForm(initial=initial_data)

    return render(
        request,
        "core/support_contact.html.j2",
        {
            "form": form,
            "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
        },
    )


@login_required
def support_contact_success(request: HttpRequest) -> HttpResponse:
    """Display support contact success page."""
    return render(request, "core/support_contact_success.html.j2")
