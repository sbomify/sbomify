from __future__ import annotations

from typing import Any

from django import template

from sbomify.apps.teams.branding import (
    DEFAULT_FALLBACK_GRAY,
    darken_hex,
    hex_to_rgb_tuple,
    ink_on_color,
    is_dark_color,
    lighten_hex,
    resolve_brand_color,
)

register = template.Library()

# Pre-compute fallback RGB string once to avoid duplicating logic in the filter.
_fallback_r, _fallback_g, _fallback_b = hex_to_rgb_tuple(DEFAULT_FALLBACK_GRAY)
DEFAULT_FALLBACK_GRAY_RGB = f"{_fallback_r}, {_fallback_g}, {_fallback_b}"


@register.filter
def hex_to_rgb(hex_color: Any) -> Any:
    """Convert hex color to RGB string."""
    try:
        # Use centralized logic from branding.py
        # Check if it's a valid hex string first to avoid errors
        if not isinstance(hex_color, str) or not hex_color.startswith("#"):
            return DEFAULT_FALLBACK_GRAY_RGB

        r, g, b = hex_to_rgb_tuple(hex_color)
        return f"{r}, {g}, {b}"
    except Exception:
        return DEFAULT_FALLBACK_GRAY_RGB


@register.filter
def lighten(hex_color: Any, amount: Any = 0.1) -> Any:
    """Lighten a hex color by a given amount (0.0 to 1.0)."""
    return lighten_hex(hex_color, amount)


@register.filter
def darken(hex_color: Any, amount: Any = 0.1) -> Any:
    """Darken a hex color by a given amount (0.0 to 1.0)."""
    return darken_hex(hex_color, amount)


@register.filter
def is_dark(hex_color: Any) -> bool:
    """Should light text sit on this colour? True means white text."""
    return is_dark_color(hex_color if isinstance(hex_color, str) else None)


@register.filter
def ink_on(hex_color: Any) -> str:
    """The text colour to print on top of this colour."""
    return ink_on_color(hex_color if isinstance(hex_color, str) else None)


@register.filter
def brand_fill(hex_color: Any) -> str:
    """The colour a branded surface paints with: the workspace's, or ours.

    Brand colours are user input and land in a style attribute, so anything
    that is not #RGB or #RRGGBB is replaced rather than escaped. An absent
    brand falls back to the platform accent, never to the neutral gray, so an
    unbranded page still looks like sbomify.
    """
    return resolve_brand_color(hex_color if isinstance(hex_color, str) else None)


@register.filter
def brand_ink(hex_color: Any) -> str:
    """The text colour for the surface brand_fill paints.

    Resolves the brand exactly as brand_fill does before measuring it, so the
    fill and its text can never disagree about which colour is underneath.
    """
    return ink_on_color(resolve_brand_color(hex_color if isinstance(hex_color, str) else None))
