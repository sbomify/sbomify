from __future__ import annotations

from typing import Any, cast

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_sync import sync_subscription_from_stripe
from sbomify.apps.billing.team_pricing_service import TeamPricingService
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import User
from sbomify.apps.core.url_utils import build_custom_domain_url
from sbomify.apps.teams.apis import get_team, list_contact_profiles
from sbomify.apps.teams.forms import DeleteInvitationForm, DeleteMemberForm
from sbomify.apps.teams.models import ContactProfileContact, Invitation, Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.queries import get_pending_invitations_for_user
from sbomify.apps.teams.utils import refresh_current_team_session
from sbomify.logging import getLogger

logger = getLogger(__name__)

PLAN_FEATURES = {
    "community": [
        "Unlimited SBOMs",
        "Unlimited products & projects",
        "All data is public",
        "Weekly vulnerability scans",
        "Community support",
        "API access",
        "Workspace management",
        "Public Trust Center",
        "Custom branding (logo & colors)",
    ],
    "business": [
        "Everything in Community",
        "Private components/projects/products",
        "NTIA Minimum Elements check",
        "Advanced vulnerability scanning (every 12 hours)",
        "Product identifiers (SKUs/barcodes)",
        "Priority support",
        "Workspace management",
        "Public Trust Center",
        "Custom domain for Trust Center",
        "Custom branding (logo & colors)",
    ],
    "enterprise": [
        "Everything in Business",
        "Unlimited users",
        "Custom Dependency Track servers",
        "Dedicated support",
        "Custom integrations",
        "SLA guarantee",
        "Advanced security",
        "Custom deployment options",
        "Public Trust Center",
        "Custom domain for Trust Center",
        "Advanced custom branding (logo, colors, themes)",
    ],
}


def _get_bulk_statuses() -> list[tuple[str, str]]:
    """Return bulk status choices, importing from controls app if available."""
    try:
        from sbomify.apps.controls.views import BULK_STATUSES

        return BULK_STATUSES
    except ImportError:
        return [
            ("compliant", "Compliant"),
            ("partial", "Partial"),
            ("not_implemented", "Not Implemented"),
            ("not_applicable", "N/A"),
        ]


PLAN_LIMITS = {
    "max_products": {
        "label": "Products",
        "icon": "cube",
    },
    "max_projects": {
        "label": "Projects",
        "icon": "folder",
    },
    "max_components": {
        "label": "Components",
        "icon": "puzzle-piece",
    },
}


@method_decorator(never_cache, name="dispatch")
class TeamSettingsView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def _redirect_with_tab(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Redirect to team settings, preserving the active tab if provided."""
        from sbomify.apps.teams.utils import redirect_to_team_settings

        active_tab = request.POST.get("active_tab", "")
        return redirect_to_team_settings(team_key, active_tab if active_tab else None)

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=team.get("detail", "Unknown error"))
            )

        # Sync subscription data from Stripe before displaying billing info
        from sbomify.apps.billing.config import is_billing_enabled

        try:
            team_obj = Team.objects.get(key=team_key)
            if is_billing_enabled():
                sync_subscription_from_stripe(team_obj)
                # Refresh team data after sync
                team_obj.refresh_from_db()
        except Team.DoesNotExist:
            team_obj = None

        # Get plan features and pricing based on billing plan
        billing_plan = team.billing_plan or Team.Plan.COMMUNITY
        plan_features = PLAN_FEATURES.get(billing_plan, [])

        # Use pricing service to calculate plan pricing and limits
        pricing_service = TeamPricingService()

        # Fetch billing plan object once for reuse
        try:
            billing_plan_obj = BillingPlan.objects.get(key=billing_plan)
        except BillingPlan.DoesNotExist:
            billing_plan_obj = None

        # Get pricing information
        plan_pricing = pricing_service.get_plan_pricing(team, billing_plan_obj)

        # Get plan limits
        plan_limits = pricing_service.get_plan_limits(team, billing_plan_obj)

        # Get actual Team model instance to access helper properties and enrich context
        # (The 'team' from get_team is a Pydantic schema which lacks these properties)
        # team_obj was already fetched above for sync, reuse it
        if not team_obj:
            try:
                team_obj = Team.objects.get(key=team_key)
            except Team.DoesNotExist:
                team_obj = None

        # Convert Pydantic model to dict so we can inject properties
        # .dict() is generic for Pydantic v1/v2, .model_dump() is v2
        # leveraging getattr to support both or verify version. assuming .dict() or simply vars() won't work on Pydantic
        # Using model_dump() if available (Pydantic V2) or dict() (V1)
        if team_obj:
            try:
                team_data = team.dict() if hasattr(team, "dict") else team.model_dump()
            except AttributeError:
                # Fallback if team doesn't have dict or model_dump
                team_data = team.model_dump() if hasattr(team, "model_dump") else vars(team)

            # Inject properties used by global banners
            team_data["is_in_grace_period"] = team_obj.is_in_grace_period
            team_data["is_payment_restricted"] = team_obj.is_payment_restricted
        else:
            # Fallback if team_obj not found
            team_data = team  # Use schema as-is

        can_set_private = team_data.get("can_set_private") if isinstance(team_data, dict) else team.can_set_private
        is_owner = request.session.get("current_team", {}).get("role") == "owner"

        # Get branding info for trust center settings
        branding_info = team_obj.branding_info if team_obj else {}

        # Get company-wide NDA document if exists
        company_nda_document = None
        if team_obj:
            company_nda_document = team_obj.get_company_nda_document()

        # Fetch contact profiles for the settings tab
        _, profiles = list_contact_profiles(request, team_key)

        # Count access tokens for account deletion tab
        from sbomify.apps.access_tokens.models import AccessToken

        user = cast(User, request.user)
        access_token_count = AccessToken.objects.filter(user=user).count()

        # Fetch incoming invitations for the current user (accept/reject UI on members tab)
        pending_invitations = get_pending_invitations_for_user(user)

        # Controls tab — all catalogs (active + inactive, including imports)
        catalog_icon_map: dict[str, str] = {
            "SOC 2 Type II": "fa-shield-halved",
            "ISO 27001:2022": "fa-certificate",
            "NIST Cybersecurity Framework 2.0": "fa-landmark",
            "CIS Controls v8": "fa-lock",
            "HIPAA": "fa-heart-pulse",
            "GDPR": "fa-user-shield",
            "CMMC 2.0": "fa-jet-fighter",
            "CSA CCM": "fa-cloud",
            "PCI DSS": "fa-credit-card",
            "NIST SP 800-53": "fa-building-columns",
        }
        active_catalogs: list[dict[str, Any]] = []
        if team_obj:
            from sbomify.apps.controls.models import ControlCatalog
            from sbomify.apps.controls.services.catalog_service import get_active_catalogs
            from sbomify.apps.controls.services.status_service import get_controls_detail

            catalogs_result = get_active_catalogs(team_obj)
            if catalogs_result.ok and catalogs_result.value:
                for catalog in catalogs_result.value:
                    detail_result = get_controls_detail(catalog)
                    categories = detail_result.value if detail_result.ok and detail_result.value else []
                    active_catalogs.append(
                        {
                            "catalog": catalog,
                            "categories": categories,
                            "total_count": sum(len(c.get("controls", [])) for c in categories),
                            "icon": catalog_icon_map.get(catalog.name, "fa-list-check"),
                        }
                    )

        return render(
            request,
            "teams/team_settings.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "team": team_data,
                "team_obj": team_obj,  # Pass actual model in case specific valid/function call is lower down
                # Members tab
                "delete_member_form": DeleteMemberForm(),
                "delete_invitation_form": DeleteInvitationForm(),
                # Billing tab
                "plan_features": plan_features,
                "all_plan_features": PLAN_FEATURES,
                "plan_pricing": plan_pricing,
                "plan_limits": plan_limits,
                "can_set_private": can_set_private,
                "is_owner": is_owner,
                # Trust center settings
                "branding_info": branding_info,
                "company_nda_document": company_nda_document,
                "trust_center_domain": getattr(settings, "TRUST_CENTER_DOMAIN", ""),
                "trust_center_url": (
                    build_custom_domain_url(team_obj, "/", secure=True).rstrip("/") if team_obj else ""
                ),
                "security_txt_config": team_obj.security_txt_config if team_obj else {},
                "security_txt_contacts": (
                    ContactProfileContact.objects.filter(
                        entity__profile__team=team_obj,
                        entity__profile__is_component_private=False,
                    )
                    .order_by("entity__profile__name", "name")
                    .values("id", "name", "email", "entity__profile__name")
                    if team_obj and team_obj.is_public
                    else []
                ),
                # Contact Profiles tab
                "profiles": profiles,
                # Account tab
                "access_token_count": access_token_count,
                # Members tab — incoming invitations for the current user
                "pending_invitations": pending_invitations,
                # Controls tab
                "active_catalogs": active_catalogs,
                "active_catalog_names": {c["catalog"].name for c in active_catalogs},
                "imported_catalogs": list(
                    ControlCatalog.objects.filter(team=team_obj, source="custom").values(
                        "id", "name", "version", "is_active"
                    )
                )
                if team_obj
                else [],
                "bulk_statuses": _get_bulk_statuses(),
                "available_catalogs": [
                    ("soc2-type2", "SOC 2 Type II", "SOC 2 Type II", "fa-shield-halved"),
                    ("iso27001-2022", "ISO 27001:2022", "ISO 27001", "fa-certificate"),
                    ("nist-csf-2", "NIST Cybersecurity Framework 2.0", "NIST CSF 2.0", "fa-landmark"),
                    ("cis-controls-v8", "CIS Controls v8", "CIS v8", "fa-lock"),
                    ("hipaa", "HIPAA", "HIPAA", "fa-heart-pulse"),
                    ("gdpr", "GDPR", "GDPR", "fa-user-shield"),
                    ("cmmc-2", "CMMC 2.0", "CMMC 2.0", "fa-jet-fighter"),
                    ("csa-ccm-v4", "CSA CCM", "CSA CCM", "fa-cloud"),
                    ("pci-dss-v4", "PCI DSS", "PCI DSS", "fa-credit-card"),
                    ("nist-800-53-r5", "NIST SP 800-53", "NIST 800-53", "fa-building-columns"),
                ],
                "is_admin_or_owner": request.session.get("current_team", {}).get("role") in ("owner", "admin"),
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        if request.POST.get("visibility_action") == "update":
            return self._update_visibility(request, team_key)

        if request.POST.get("trust_center_description_action") == "update":
            return self._update_trust_center_description(request, team_key)

        company_nda_action = request.POST.get("company_nda_action")
        if company_nda_action in ("upload", "replace", "delete"):
            return self._handle_company_nda(request, team_key, company_nda_action)

        if request.POST.get("tea_action") == "update":
            return self._update_tea_enabled(request, team_key)

        if request.POST.get("security_txt_action") == "update":
            return self._update_security_txt(request, team_key)

        if request.POST.get("slug_action") == "update":
            return self._update_slug(request, team_key)

        if request.POST.get("_method") == "DELETE":
            if "member_id" in request.POST:
                return self._delete_member(request, team_key)
            elif "invitation_id" in request.POST:
                return self._delete_invitation(request, team_key)

        messages.error(request, "Invalid request method")
        return self._redirect_with_tab(request, team_key)

    def _delete_member(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from sbomify.apps.teams.utils import remove_member_safely

        user = cast(User, request.user)
        form = DeleteMemberForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return self._redirect_with_tab(request, team_key)

        member_id = form.cleaned_data["member_id"]
        try:
            membership = Member.objects.get(pk=member_id, team__key=team_key)
        except Member.DoesNotExist:
            messages.error(request, "Member not found")
            return self._redirect_with_tab(request, team_key)

        if membership.role == "owner":
            # Check if actor is an admin trying to remove an owner
            actor_membership = Member.objects.filter(user=user, team=membership.team).first()
            if actor_membership and actor_membership.role == "admin":
                messages.error(
                    request,
                    "Admins cannot remove workspace owners.",
                )
                return self._redirect_with_tab(request, team_key)

            from sbomify.apps.teams.queries import count_team_owners

            owners_count = count_team_owners(membership.team.id)
            if owners_count <= 1:
                messages.warning(
                    request,
                    "Cannot delete the only owner of the workspace. Please assign another owner first.",
                )
                return self._redirect_with_tab(request, team_key)

        active_tab = request.POST.get("active_tab", "")
        return remove_member_safely(request, membership, active_tab=active_tab if active_tab else None)

    def _delete_invitation(self, request: HttpRequest, team_key: str) -> HttpResponse:
        form = DeleteInvitationForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return self._redirect_with_tab(request, team_key)

        try:
            invitation = Invitation.objects.get(pk=form.cleaned_data["invitation_id"], team__key=team_key)
        except Invitation.DoesNotExist:
            messages.error(request, "Invitation not found")
            return self._redirect_with_tab(request, team_key)

        invitation_email = invitation.email
        invitation.delete()
        messages.info(request, f"Invitation for {invitation_email} deleted")

        return self._redirect_with_tab(request, team_key)

    def _update_visibility(self, request: HttpRequest, team_key: str) -> HttpResponse:
        user = cast(User, request.user)
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change visibility")
            return self._redirect_with_tab(request, team_key)

        visibility_values = request.POST.getlist("is_public")
        desired_visibility = self._parse_checkbox_value(visibility_values, default=team.is_public)

        can_set_private = team.can_be_private()
        if desired_visibility is False and not can_set_private:
            messages.error(request, "Disabling the Trust Center is available on Business or Enterprise plans.")
            return self._redirect_with_tab(request, team_key)

        team.is_public = desired_visibility
        team.save()

        refresh_current_team_session(request, team)

        messages.success(request, f"Trust center is now {'public' if team.is_public else 'private'}.")
        return self._redirect_with_tab(request, team_key)

    def _update_trust_center_description(self, request: HttpRequest, team_key: str) -> HttpResponse:
        user = cast(User, request.user)
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change the trust center description")
            return self._redirect_with_tab(request, team_key)

        description = request.POST.get("trust_center_description", "").strip()

        # Validate length
        if len(description) > 500:
            messages.error(request, "Description must be 500 characters or less")
            return self._redirect_with_tab(request, team_key)

        # Update branding_info with new description
        # Create a copy of the dict to ensure Django detects the change
        branding_info = dict(team.branding_info or {})
        branding_info["trust_center_description"] = description
        team.branding_info = branding_info
        team.save(update_fields=["branding_info"])

        if description:
            messages.success(request, "Trust center description updated.")
        else:
            messages.success(request, "Trust center description cleared. Using default description.")
        return self._redirect_with_tab(request, team_key)

    def _handle_company_nda(self, request: HttpRequest, team_key: str, action: str) -> HttpResponse:
        """Handle company-wide NDA upload, replace, or delete."""
        user = cast(User, request.user)
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can manage company NDA")
            return self._redirect_with_tab(request, team_key)

        if action == "delete":
            return self._delete_company_nda(request, team_key, team)
        else:
            return self._upload_company_nda(request, team_key, team)

    def _upload_company_nda(self, request: HttpRequest, team_key: str, team: Team) -> HttpResponse:
        """Upload a new version of company-wide NDA (versioning enabled)."""
        if "company_nda_file" not in request.FILES:
            messages.error(request, "No file provided")
            return self._redirect_with_tab(request, team_key)

        uploaded_file_raw = request.FILES["company_nda_file"]
        # request.FILES values can be UploadedFile or list; we always get a single file here
        from django.core.files.uploadedfile import UploadedFile

        if not isinstance(uploaded_file_raw, UploadedFile):
            messages.error(request, "Invalid file upload")
            return self._redirect_with_tab(request, team_key)
        uploaded_file: UploadedFile = uploaded_file_raw

        # Validate file
        if uploaded_file.content_type != "application/pdf":
            messages.error(request, "Only PDF files are allowed")
            return self._redirect_with_tab(request, team_key)

        max_size = 50 * 1024 * 1024  # 50MB
        if (uploaded_file.size or 0) > max_size:
            messages.error(request, "File size must be less than 50MB")
            return self._redirect_with_tab(request, team_key)

        try:
            import hashlib
            from decimal import Decimal, InvalidOperation

            from sbomify.apps.core.object_store import StorageClient
            from sbomify.apps.documents.models import Document

            # Read file content
            file_content = uploaded_file.read()
            uploaded_file.seek(0)  # Reset for S3 upload

            # Calculate SHA-256 hash
            content_hash = hashlib.sha256(file_content).hexdigest()

            # Upload to S3
            s3 = StorageClient("DOCUMENTS")
            filename = s3.upload_document(file_content)

            # Get or create company-wide component
            company_component = team.get_or_create_company_wide_component()

            # Find all previous NDA documents for this component to determine next version
            previous_ndas = Document.objects.filter(
                component=company_component,
                document_type=Document.DocumentType.COMPLIANCE,
                compliance_subcategory=Document.ComplianceSubcategory.NDA,
            ).order_by("-created_at")

            # Calculate next version number
            next_version = "1.0"
            if previous_ndas.exists():
                # Try to parse the latest version and increment
                latest_nda = previous_ndas.first()
                latest_version_str = latest_nda.version if latest_nda else "1.0"
                try:
                    # Try to parse as decimal (e.g., "1.0", "2.5")
                    latest_version = Decimal(latest_version_str)
                    next_version = str(latest_version + Decimal("0.1"))
                    # Remove trailing zeros and unnecessary decimal point
                    next_version = next_version.rstrip("0").rstrip(".")
                except (InvalidOperation, ValueError):
                    # If version is not a number, use a simple increment
                    # Try to extract number from version string
                    import re

                    match = re.search(r"(\d+(?:\.\d+)?)", latest_version_str)
                    if match:
                        try:
                            latest_version = Decimal(match.group(1))
                            next_version = str(latest_version + Decimal("0.1"))
                            next_version = next_version.rstrip("0").rstrip(".")
                        except (InvalidOperation, ValueError):
                            # Fallback: append version number
                            version_count = previous_ndas.count()
                            next_version = f"{version_count + 1}.0"
                    else:
                        # No number found, use count-based version
                        version_count = previous_ndas.count()
                        next_version = f"{version_count + 1}.0"

            # Always create a new Document record (versioning)
            document = Document.objects.create(
                name=uploaded_file.name or "NDA",
                version=next_version,
                document_filename=filename,
                component=company_component,
                source="manual_upload",
                document_type=Document.DocumentType.COMPLIANCE,
                compliance_subcategory=Document.ComplianceSubcategory.NDA,
                content_hash=content_hash,
                content_type=uploaded_file.content_type,
                file_size=uploaded_file.size,
            )

            # Store Document ID in team's branding_info (point to latest version)
            # Create a copy of the dict to ensure Django detects the change
            branding_info = dict(team.branding_info or {})
            old_nda_id = branding_info.get("company_nda_document_id")
            branding_info["company_nda_document_id"] = document.id
            team.branding_info = branding_info
            team.save(update_fields=["branding_info"])

            # Note: We don't delete old NDA signatures when a new version is uploaded.
            # The signatures remain linked to the old NDA document, and the display logic
            # will automatically show them as "Invalid" because has_current_nda_signature
            # will be False (signature is for old NDA, not current one).
            # Users will need to sign the new NDA version when requesting access again.

            if old_nda_id:
                messages.success(
                    request,
                    f"Company NDA version {next_version} uploaded successfully. "
                    "Existing NDA signatures are now invalid. Users will need to sign the new NDA version.",
                )
            else:
                # First NDA uploaded - no signatures to invalidate
                messages.success(request, f"Company NDA version {next_version} uploaded successfully.")

            return self._redirect_with_tab(request, team_key)

        except Exception as e:
            logger.error(f"Error uploading company NDA: {e}")
            messages.error(request, "Failed to upload company NDA. Please try again.")
            return self._redirect_with_tab(request, team_key)

    def _delete_company_nda(self, request: HttpRequest, team_key: str, team: Team) -> HttpResponse:
        """Delete company-wide NDA."""
        try:
            company_nda_id = team.branding_info.get("company_nda_document_id")
            if not company_nda_id:
                messages.error(request, "No company NDA found to delete")
                return self._redirect_with_tab(request, team_key)

            # Remove from branding_info
            # Create a copy of the dict to ensure Django detects the change
            branding_info = dict(team.branding_info or {})
            branding_info.pop("company_nda_document_id", None)
            team.branding_info = branding_info
            team.save(update_fields=["branding_info"])

            # Optionally delete the document (or keep for audit trail)
            # For now, we'll keep it for audit trail
            # try:
            #     document = Document.objects.get(id=company_nda_id)
            #     document.delete()
            # except Document.DoesNotExist:
            #     pass

            messages.success(request, "Company NDA deleted successfully.")
            return self._redirect_with_tab(request, team_key)

        except Exception as e:
            logger.error(f"Error deleting company NDA: {e}")
            messages.error(request, "Failed to delete company NDA. Please try again.")
            return self._redirect_with_tab(request, team_key)

    def _update_tea_enabled(self, request: HttpRequest, team_key: str) -> HttpResponse:
        user = cast(User, request.user)
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change TEA settings")
            return self._redirect_with_tab(request, team_key)

        tea_values = request.POST.getlist("tea_enabled")
        desired_tea_enabled = self._parse_checkbox_value(tea_values, default=team.tea_enabled)

        team.tea_enabled = desired_tea_enabled
        team.save()

        refresh_current_team_session(request, team)

        messages.success(request, f"Transparency Exchange API is now {'enabled' if team.tea_enabled else 'disabled'}.")
        return self._redirect_with_tab(request, team_key)

    def _update_security_txt(self, request: HttpRequest, team_key: str) -> HttpResponse:
        user = cast(User, request.user)
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change security.txt settings")
            return self._redirect_with_tab(request, team_key)

        from sbomify.apps.teams.services.security_txt import validate_security_txt_url

        config = dict(team.security_txt_config or {})
        was_enabled = config.get("enabled", False)
        security_txt_values = request.POST.getlist("security_txt_enabled")
        config["enabled"] = self._parse_checkbox_value(security_txt_values, default=was_enabled)

        # Short-circuit when disabling — skip field validation so users can always toggle off
        if not config["enabled"]:
            team.security_txt_config = config
            team.save(update_fields=["security_txt_config"])
            refresh_current_team_session(request, team)
            messages.success(request, "security.txt is now disabled.")
            return self._redirect_with_tab(request, team_key)

        # Validate and store selected contact ID (CharField PK, not int)
        contact_id = request.POST.get("security_txt_contact_id", "").strip()
        if contact_id:
            if not ContactProfileContact.objects.filter(
                id=contact_id, entity__profile__team=team, entity__profile__is_component_private=False
            ).exists():
                messages.error(request, "Selected contact does not belong to this workspace")
                return self._redirect_with_tab(request, team_key)
        config["contact_id"] = contact_id

        # Validate and store URL fields
        # Note: validation is intentionally duplicated here and in the service layer
        # (generate_security_txt) for defense-in-depth — the view rejects bad input early,
        # and the service re-validates at render time to guard against data that bypasses the view.
        url_fields = {
            "policy_url": "security_txt_policy_url",
            "acknowledgments_url": "security_txt_acknowledgments_url",
            "hiring_url": "security_txt_hiring_url",
            "canonical_url": "security_txt_canonical_url",
        }
        for config_key, post_key in url_fields.items():
            value = request.POST.get(post_key, "").strip()
            if value:
                error = validate_security_txt_url(value)
                if error:
                    messages.error(request, f"Invalid {config_key.replace('_', ' ')}: {error}")
                    return self._redirect_with_tab(request, team_key)
            config[config_key] = value

        # Encryption URLs — multiple allowed (stored as JSON list)
        import json as _json

        encryption_urls_raw = request.POST.get("security_txt_encryption_urls", "[]")
        try:
            encryption_urls = _json.loads(encryption_urls_raw)
            if not isinstance(encryption_urls, list):
                encryption_urls = []
        except (ValueError, TypeError):
            encryption_urls = []
        for enc_url in encryption_urls:
            enc_url = str(enc_url).strip()
            if enc_url:
                error = validate_security_txt_url(enc_url)
                if error:
                    messages.error(request, f"Invalid encryption URL: {error}")
                    return self._redirect_with_tab(request, team_key)
        config["encryption_urls"] = [str(u).strip() for u in encryption_urls if str(u).strip()]

        # Preferred languages — use centralized validator
        from datetime import datetime, timedelta, timezone

        from sbomify.apps.teams.services.security_txt import validate_preferred_languages

        preferred_languages = request.POST.get("security_txt_preferred_languages", "").strip()
        lang_error = validate_preferred_languages(preferred_languages)
        if lang_error:
            messages.error(request, lang_error)
            return self._redirect_with_tab(request, team_key)
        config["preferred_languages"] = preferred_languages

        # Refresh Expires on every save per RFC 9116 semantics
        config["expires"] = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

        team.security_txt_config = config
        team.save(update_fields=["security_txt_config"])

        refresh_current_team_session(request, team)
        if config["enabled"] != was_enabled:
            messages.success(request, f"security.txt is now {'enabled' if config['enabled'] else 'disabled'}.")
        else:
            messages.success(request, "security.txt settings saved.")
        return self._redirect_with_tab(request, team_key)

    def _update_slug(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from django.core.exceptions import ValidationError
        from django.db import IntegrityError

        user = cast(User, request.user)
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change the slug")
            return self._redirect_with_tab(request, team_key)

        new_slug = request.POST.get("slug", "").strip().lower()
        if not new_slug:
            messages.error(request, "Slug cannot be empty")
            return self._redirect_with_tab(request, team_key)

        if new_slug == team.slug:
            return self._redirect_with_tab(request, team_key)

        team.slug = new_slug
        try:
            team.full_clean(exclude=["key"])
        except ValidationError as e:
            slug_errors = e.message_dict.get("slug", [])
            if slug_errors:
                messages.error(request, slug_errors[0])
            else:
                messages.error(request, "; ".join(e.messages))
            # Restore original slug on the in-memory instance
            team.refresh_from_db(fields=["slug"])
            return self._redirect_with_tab(request, team_key)

        try:
            team.save(update_fields=["slug"])
        except IntegrityError:
            messages.error(request, f'The slug "{new_slug}" is already taken.')
            team.refresh_from_db(fields=["slug"])
            return self._redirect_with_tab(request, team_key)

        messages.success(request, "Trust Center slug updated successfully.")
        return self._redirect_with_tab(request, team_key)

    @staticmethod
    def _parse_checkbox_value(values: list[str], default: bool) -> bool:
        # Hidden field + checkbox submit two values; reverse to prefer the user's checked value
        if not values:
            return default

        for raw in reversed(values):
            val = (raw or "").strip().lower()
            if val in {"true", "1", "on", "yes"}:
                return True
            if val in {"false", "0", "off", "no"}:
                return False

        return default
