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
    """Return a template-friendly branding payload for public views."""
    default_image = static("img/sbomify.svg")
    if not team:
        return {"brand_image": default_image, "branding_enabled": False}

    raw_branding = (getattr(team, "branding_info", {}) or {}).copy()
    try:
        branding_info = BrandingInfo(**raw_branding)
    except ValidationError as exc:
        logger.warning("Invalid branding data for team %s: %s", getattr(team, "id", None), exc)
        branding_info = BrandingInfo()
    name = getattr(team, "display_name", getattr(team, "name", ""))

    branding_enabled_flag = raw_branding.get("branding_enabled", None)
    if branding_enabled_flag is False:
        # Preserve name but fall back to platform defaults for assets/colors.
        return {"branding_enabled": False, "name": name, "brand_image": default_image}

    brand_color = branding_info.brand_color or "#4f46e5"
    accent_color = branding_info.accent_color or "#7c8b9d"
    brand_logo_url = branding_info.brand_logo_url
    brand_icon_url = branding_info.brand_icon_url
    brand_image = brand_logo_url or branding_info.brand_image or default_image

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
    }
