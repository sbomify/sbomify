from django import template
from sbomify.apps.teams.branding import (
    DEFAULT_FALLBACK_GRAY,
    darken_hex,
    hex_to_rgb_tuple,
    lighten_hex,
)

register = template.Library()


@register.filter
def hex_to_rgb(hex_color):
    """Convert hex color to RGB string."""
    try:
        # Use centralized logic from branding.py
        # Check if it's a valid hex string first to avoid errors
        if not isinstance(hex_color, str) or not hex_color.startswith("#"):
            return DEFAULT_FALLBACK_GRAY

        r, g, b = hex_to_rgb_tuple(hex_color)
        return f"{r}, {g}, {b}"
    except Exception:
        return DEFAULT_FALLBACK_GRAY


@register.filter
def lighten(hex_color, amount=0.1):
    """Lighten a hex color by a given amount (0.0 to 1.0)."""
    return lighten_hex(hex_color, amount)


@register.filter
def darken(hex_color, amount=0.1):
    """Darken a hex color by a given amount (0.0 to 1.0)."""
    return darken_hex(hex_color, amount)
