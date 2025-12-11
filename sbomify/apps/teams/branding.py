from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.templatetags.static import static
from pydantic import ValidationError

from sbomify.apps.teams.schemas import BrandingInfo

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

logger = logging.getLogger(__name__)


def build_branding_context(team: "Team | None") -> dict:
    """
    Return a template-friendly branding payload for public views.

    Includes custom domain information for URL generation in templates.
    """
    default_image = static("img/sbomify.svg")
    if not team:
        return {
            "brand_image": default_image,
            "branding_enabled": False,
            "custom_domain": None,
            "custom_domain_validated": False,
            "workspace_key": None,
        }

    raw_branding = (getattr(team, "branding_info", {}) or {}).copy()
    try:
        branding_info = BrandingInfo(**raw_branding)
    except ValidationError as exc:
        logger.warning("Invalid branding data for team %s: %s", getattr(team, "id", None), exc)
        branding_info = BrandingInfo()
    name = getattr(team, "display_name", getattr(team, "name", ""))

    # Get custom domain information
    custom_domain = getattr(team, "custom_domain", None)
    custom_domain_validated = getattr(team, "custom_domain_validated", False)

    # Get workspace key for URL generation
    workspace_key = getattr(team, "key", None)

    branding_enabled_flag = raw_branding.get("branding_enabled", None)
    if branding_enabled_flag is False:
        # Preserve name but fall back to platform defaults for assets/colors.
        return {
            "branding_enabled": False,
            "name": name,
            "brand_image": default_image,
            "custom_domain": custom_domain,
            "custom_domain_validated": custom_domain_validated,
            "workspace_key": workspace_key,
        }

    brand_color = branding_info.brand_color or "#4f46e5"
    accent_color = branding_info.accent_color or "#7c8b9d"
    brand_logo_url = branding_info.brand_logo_url
    brand_icon_url = branding_info.brand_icon_url
    brand_image = branding_info.brand_image or default_image

    return {
        **branding_info.model_dump(),
        "branding_enabled": True,
        "name": name,
        # Prefer full logo when available, otherwise fall back to the chosen brand asset.
        "brand_image": brand_image,
        "brand_logo_url": brand_logo_url,
        "brand_icon_url": brand_icon_url,
        "brand_color": brand_color,
        "accent_color": accent_color,
        # Legacy aliases used by some templates/components
        "primary_color": brand_color,
        "secondary_color": accent_color,
        # Custom domain information
        "custom_domain": custom_domain,
        "custom_domain_validated": custom_domain_validated,
        # Workspace key for URL generation
        "workspace_key": workspace_key,
    }
