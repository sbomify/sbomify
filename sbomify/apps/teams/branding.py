from __future__ import annotations

import colorsys
import logging
import re
from typing import TYPE_CHECKING

from django.templatetags.static import static
from pydantic import ValidationError

from sbomify.apps.teams.schemas import BrandingInfo

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

logger = logging.getLogger(__name__)

# Default fallback colors
DEFAULT_BRAND_COLOR = "#4f46e5"
DEFAULT_ACCENT_COLOR = "#7c8b9d"
DEFAULT_FALLBACK_GRAY = "#dcdcdc"


def sanitize_hex_color(color: str | None, fallback: str = DEFAULT_FALLBACK_GRAY) -> str:
    """
    Validate and sanitize hex colors to prevent CSS injection attacks.
    
    Args:
        color: Input color string (potentially user-controlled)
        fallback: Fallback color to use if validation fails
        
    Returns:
        Valid hex color string (guaranteed safe for CSS injection)
        
    Security:
        This function prevents XSS attacks via CSS injection by strictly
        validating hex color format. Any deviation from #RRGGBB format
        triggers a fallback to prevent malicious payloads like:
        "#000; } </style><script>alert('xss')</script><style>"
    """
    if not color:
        return fallback
    
    # Handle non-string inputs defensively
    if not isinstance(color, str):
        logger.warning(f"Non-string color value rejected: {type(color).__name__}")
        return fallback
    
    # Strip whitespace and validate strict hex format
    color = color.strip()
    # Allow either #RRGGBB or #RGB
    pattern = r"^#[0-9A-Fa-f]{6}$|^#[0-9A-Fa-f]{3}$"
    
    if not re.match(pattern, color):
        # Log security event for monitoring
        logger.warning(f"Invalid hex color rejected for security: {color[:50]}")  # Limit log size
        return fallback
    
    # Expand #RGB to #RRGGBB for consistent downstream handling
    if len(color) == 4:
        color = f"#{color[1]*2}{color[2]*2}{color[3]*2}"
    
    return color


def hex_to_rgb_tuple(hex_color: str) -> tuple[int, int, int]:
    """
    Convert hex color to RGB tuple.
    
    Args:
        hex_color: Valid hex color string (e.g., "#4f46e5")
        
    Returns:
        Tuple of (r, g, b) integer values
        
    Note:
        This function assumes input is already sanitized via sanitize_hex_color.
        For performance, it doesn't re-validate the format.
    """
    hex_color = hex_color.lstrip("#")
    
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b)
    except (ValueError, IndexError):
        # Fallback to gray if conversion fails
        logger.error(f"Failed to convert hex to RGB: {hex_color}")
        return (220, 220, 220)


def build_branding_context(team: "Team | None") -> dict:
    """
    Return a template-friendly branding payload for public views.
    
    Includes custom domain information for URL generation in templates.
    
    This function consolidates all branding logic, sanitization, and fallback
    handling in one place. Templates receive guaranteed-valid, ready-to-use data.
    
    Security:
        All color inputs are sanitized to prevent CSS injection attacks.
        
    Performance:
        RGB values are pre-computed here rather than in templates, avoiding
        repeated conversions on every page render.
    """
    default_image = static("img/sbomify.svg")
    
    if not team:
        return {
            "brand_image": default_image,
            "branding_enabled": False,
            "custom_domain": None,
            "custom_domain_validated": False,
            "workspace_key": None,
            "brand_color": DEFAULT_BRAND_COLOR,
            "accent_color": DEFAULT_ACCENT_COLOR,
            "brand_color_rgb": "79, 70, 229",  # Pre-computed for DEFAULT_BRAND_COLOR
            "accent_color_rgb": "124, 139, 157",  # Pre-computed for DEFAULT_ACCENT_COLOR
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
        default_brand_rgb = hex_to_rgb_tuple(DEFAULT_BRAND_COLOR)
        default_accent_rgb = hex_to_rgb_tuple(DEFAULT_ACCENT_COLOR)
        
        return {
            "branding_enabled": False,
            "name": name,
            "brand_image": default_image,
            "custom_domain": custom_domain,
            "custom_domain_validated": custom_domain_validated,
            "workspace_key": workspace_key,
            "brand_color": DEFAULT_BRAND_COLOR,
            "accent_color": DEFAULT_ACCENT_COLOR,
            "brand_color_rgb": f"{default_brand_rgb[0]}, {default_brand_rgb[1]}, {default_brand_rgb[2]}",
            "accent_color_rgb": f"{default_accent_rgb[0]}, {default_accent_rgb[1]}, {default_accent_rgb[2]}",
        }

    # Sanitize colors to prevent XSS attacks via CSS injection
    brand_color = sanitize_hex_color(branding_info.brand_color, DEFAULT_BRAND_COLOR)
    accent_color = sanitize_hex_color(branding_info.accent_color, DEFAULT_ACCENT_COLOR)
    
    # Pre-compute RGB values for template use
    brand_rgb = hex_to_rgb_tuple(brand_color)
    accent_rgb = hex_to_rgb_tuple(accent_color)
    
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
        # Sanitized colors (guaranteed valid, XSS-safe)
        "brand_color": brand_color,
        "accent_color": accent_color,
        # Pre-computed RGB values (performance optimization)
        "brand_color_rgb": f"{brand_rgb[0]}, {brand_rgb[1]}, {brand_rgb[2]}",
        "accent_color_rgb": f"{accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}",
        # Derived colors for CSS
        "accent_color_dark": sanitize_hex_color(
            darken_hex(accent_color, 0.1), 
            accent_color
        ),
        # Legacy aliases used by some templates/components
        "primary_color": brand_color,
        "secondary_color": accent_color,
        # Custom domain information
        "custom_domain": custom_domain,
        "custom_domain_validated": custom_domain_validated,
        # Workspace key for URL generation
        "workspace_key": workspace_key,
    }


def darken_hex(hex_color: str, amount: float = 0.1) -> str:
    """
    Darken a hex color by a given amount.
    
    Args:
        hex_color: Valid hex color (already sanitized)
        amount: Darkening amount (0.0 to 1.0)
        
    Returns:
        Darkened hex color string
    """
    try:
        r, g, b = hex_to_rgb_tuple(hex_color)
        # Convert RGB (0-255) to HLS (0-1)
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        
        # Reduce lightness
        l = max(0.0, l * (1 - amount))
        
        # Convert back to RGB
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        
        # Convert back to 0-255 ints
        r = int(r * 255)
        g = int(g * 255)
        b = int(b * 255)
        
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def lighten_hex(hex_color: str, amount: float = 0.1) -> str:
    """
    Lighten a hex color by a given amount.

    Args:
        hex_color: Valid hex color (already sanitized)
        amount: Lightening amount (0.0 to 1.0)

    Returns:
        Lightened hex color string
    """
    try:
        r, g, b = hex_to_rgb_tuple(hex_color)
        # Convert RGB (0-255) to HLS (0-1)
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        
        # Increase lightness
        l = min(1.0, l + (1 - l) * amount)
        
        # Convert back to RGB
        r, g, b = colorsys.hls_to_rgb(h, l, s)

        # Convert back to 0-255 ints
        r = int(r * 255)
        g = int(g * 255)
        b = int(b * 255)
        
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color
