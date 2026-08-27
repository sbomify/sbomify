from __future__ import annotations

import colorsys
import logging
import re
from typing import TYPE_CHECKING, Any, Callable

from django.templatetags.static import static
from pydantic import ValidationError

from sbomify.apps.teams.schemas import BrandingInfo

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

logger = logging.getLogger(__name__)

# Default fallback colors - matches the brand navy ink (--color-primary: 37 41 63)
DEFAULT_BRAND_COLOR = "#25293F"
DEFAULT_ACCENT_COLOR = "#4263EB"
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
        color = f"#{color[1] * 2}{color[2] * 2}{color[3] * 2}"

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


def relative_luminance(hex_color: str) -> float:
    """
    WCAG relative luminance of a colour, 0.0 (black) to 1.0 (white).

    This is not the same as HSL lightness: the channels are gamma-expanded and
    then weighted for how bright the eye finds them, so a saturated blue and a
    saturated yellow of equal HSL lightness land far apart. Text legibility
    follows this number, not lightness, which is why it backs is_dark_color.

    Args:
        hex_color: Valid hex color (already sanitized)

    Returns:
        Relative luminance in the range 0.0 to 1.0
    """
    channels = []
    for value in hex_to_rgb_tuple(hex_color):
        srgb = value / 255.0
        channels.append(srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4)

    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


# Luminance at which white and black text contrast equally against a colour.
# Solving 1.05 / (L + 0.05) == (L + 0.05) / 0.05 gives L = sqrt(0.0525) - 0.05.
_CONTRAST_PIVOT = 0.0525**0.5 - 0.05


def is_dark_color(color: str | None) -> bool:
    """
    Is this colour dark enough that light text belongs on top of it?

    True means put white text on it, False means put dark text on it. The
    threshold is the luminance where white and black text contrast equally
    against the colour, so the answer is always the more readable of the two
    rather than a guess.

    A user's brand colour reaches this unvalidated, so the input is sanitized
    first: anything that is not a hex colour is treated as the fallback gray,
    which is light, so the safe dark-text answer comes back.

    Args:
        color: Brand colour as hex, or None

    Returns:
        True if light text should sit on this colour
    """
    return relative_luminance(sanitize_hex_color(color)) < _CONTRAST_PIVOT


def resolve_brand_color(color: str | None) -> str:
    """
    The colour a branded surface should paint with.

    A workspace's brand when it has set one, the platform accent when it has
    not. The neutral gray that sanitize_hex_color falls back to is right for an
    unknown swatch but wrong for an accent, so the fallback is named here and
    every branded caller resolves through this one function. That is what stops
    a fill and its text from measuring different colours.

    Args:
        color: Brand colour as hex, or None

    Returns:
        A valid hex colour, safe to place in CSS
    """
    return sanitize_hex_color(color, fallback=DEFAULT_ACCENT_COLOR)


def ink_on_color(color: str | None) -> str:
    """
    The text colour to print on top of a brand colour.

    White on a dark brand, the platform ink on a light one. Callers should not
    branch on is_dark_color themselves to pick a colour: doing it here keeps
    every branded surface using the same two inks, so a workspace cannot end up
    with text that is technically readable but visibly off from the rest.

    Args:
        color: Brand colour as hex, or None

    Returns:
        Hex colour for text drawn on `color`
    """
    return "#ffffff" if is_dark_color(color) else DEFAULT_BRAND_COLOR


def _apply_lightness_transform(hex_color: str, transform: Callable[[float], float]) -> str:
    """Shared RGB<->HLS helper used by lighten_hex/darken_hex."""
    try:
        r_int, g_int, b_int = hex_to_rgb_tuple(hex_color)
        hue, lightness, saturation = colorsys.rgb_to_hls(r_int / 255.0, g_int / 255.0, b_int / 255.0)

        lightness = max(0.0, min(1.0, transform(lightness)))

        r_float, g_float, b_float = colorsys.hls_to_rgb(hue, lightness, saturation)
        r_out = int(r_float * 255)
        g_out = int(g_float * 255)
        b_out = int(b_float * 255)

        return f"#{r_out:02x}{g_out:02x}{b_out:02x}"
    except (ValueError, TypeError, OverflowError):
        return hex_color


def build_branding_context(team: Team | None) -> dict[str, Any]:
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
            "slug": None,
            "brand_color": DEFAULT_BRAND_COLOR,
            "accent_color": DEFAULT_ACCENT_COLOR,
            "brand_color_rgb": "37, 41, 63",  # Pre-computed for DEFAULT_BRAND_COLOR
            "accent_color_rgb": "66, 99, 235",  # Pre-computed for DEFAULT_ACCENT_COLOR
            "trust_center_description": "",
        }

    raw_branding: dict[str, Any] = (getattr(team, "branding_info", {}) or {}).copy()
    try:
        branding_info = BrandingInfo(**raw_branding)
    except ValidationError as exc:
        logger.warning("Invalid branding data for team %s: %s", getattr(team, "id", None), exc)
        branding_info = BrandingInfo()

    name = getattr(team, "display_name", getattr(team, "name", ""))

    # Get custom domain information
    custom_domain = getattr(team, "custom_domain", None)
    custom_domain_validated = getattr(team, "custom_domain_validated", False)

    # Get workspace key and slug for URL generation
    workspace_key = getattr(team, "key", None)
    slug = getattr(team, "slug", None)

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
            "slug": slug,
            "brand_color": DEFAULT_BRAND_COLOR,
            "accent_color": DEFAULT_ACCENT_COLOR,
            "brand_color_rgb": f"{default_brand_rgb[0]}, {default_brand_rgb[1]}, {default_brand_rgb[2]}",
            "accent_color_rgb": f"{default_accent_rgb[0]}, {default_accent_rgb[1]}, {default_accent_rgb[2]}",
            "trust_center_description": branding_info.trust_center_description,
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
        "accent_color_dark": sanitize_hex_color(darken_hex(accent_color, 0.1), accent_color),
        # Legacy aliases used by some templates/components
        "primary_color": brand_color,
        "secondary_color": accent_color,
        # Custom domain information
        "custom_domain": custom_domain,
        "custom_domain_validated": custom_domain_validated,
        # Workspace key and slug for URL generation
        "workspace_key": workspace_key,
        "slug": slug,
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
    return _apply_lightness_transform(hex_color, lambda lightness: lightness * (1 - amount))


def lighten_hex(hex_color: str, amount: float = 0.1) -> str:
    """
    Lighten a hex color by a given amount.

    Args:
        hex_color: Valid hex color (already sanitized)
        amount: Lightening amount (0.0 to 1.0)

    Returns:
        Lightened hex color string
    """
    return _apply_lightness_transform(hex_color, lambda lightness: lightness + (1 - lightness) * amount)
