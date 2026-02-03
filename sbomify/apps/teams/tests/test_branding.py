"""Security and edge case tests for branding functionality."""

import pytest

from sbomify.apps.teams.branding import (
    DEFAULT_ACCENT_COLOR,
    DEFAULT_BRAND_COLOR,
    DEFAULT_FALLBACK_GRAY,
    build_branding_context,
    hex_to_rgb_tuple,
    sanitize_hex_color,
)
from sbomify.apps.teams.models import Team


class TestSanitizeHexColor:
    """Test hex color sanitization for XSS prevention."""

    def test_valid_hex_color_passes_through(self):
        """Valid hex colors should pass through unchanged."""
        assert sanitize_hex_color("#123456") == "#123456"
        assert sanitize_hex_color("#ABCDEF") == "#ABCDEF"
        assert sanitize_hex_color("#abcdef") == "#abcdef"
        assert sanitize_hex_color("#000000") == "#000000"
        assert sanitize_hex_color("#FFFFFF") == "#FFFFFF"

    def test_xss_attempt_via_css_injection_rejected(self):
        """XSS attempts via CSS injection should fallback to safe color."""
        malicious_color = "#000; } </style><script>alert('xss')</script><style>"
        assert sanitize_hex_color(malicious_color) == DEFAULT_FALLBACK_GRAY

    def test_malformed_hex_rejected(self):
        """Malformed hex colors should fallback."""
        assert sanitize_hex_color("#zzzzzz") == DEFAULT_FALLBACK_GRAY
        assert sanitize_hex_color("#12345") == DEFAULT_FALLBACK_GRAY  # Too short
        assert sanitize_hex_color("#1234567") == DEFAULT_FALLBACK_GRAY  # Too long
        assert sanitize_hex_color("123456") == DEFAULT_FALLBACK_GRAY  # Missing #
        assert sanitize_hex_color("") == DEFAULT_FALLBACK_GRAY
        assert sanitize_hex_color(None) == DEFAULT_FALLBACK_GRAY

    def test_non_string_input_rejected(self):
        """Non-string inputs should fallback gracefully."""
        assert sanitize_hex_color(12345) == DEFAULT_FALLBACK_GRAY
        assert sanitize_hex_color([]) == DEFAULT_FALLBACK_GRAY
        assert sanitize_hex_color({}) == DEFAULT_FALLBACK_GRAY

    def test_whitespace_stripped(self):
        """Whitespace should be stripped before validation."""
        assert sanitize_hex_color("  #123456  ") == "#123456"
        assert sanitize_hex_color("\n#abcdef\t") == "#abcdef"

    def test_custom_fallback_used(self):
        """Custom fallback color should be used when provided."""
        assert sanitize_hex_color("invalid", fallback="#ff0000") == "#ff0000"

    def test_three_digit_hex_is_supported(self):
        """#RGB shorthand should be expanded to #RRGGBB."""
        assert sanitize_hex_color("#abc") == "#aabbcc"


class TestHexToRgbTuple:
    """Test hex to RGB tuple conversion."""

    def test_valid_hex_converts_correctly(self):
        """Valid hex colors should convert to correct RGB values."""
        assert hex_to_rgb_tuple("#000000") == (0, 0, 0)
        assert hex_to_rgb_tuple("#FFFFFF") == (255, 255, 255)
        assert hex_to_rgb_tuple("#FF0000") == (255, 0, 0)
        assert hex_to_rgb_tuple("#00FF00") == (0, 255, 0)
        assert hex_to_rgb_tuple("#0000FF") == (0, 0, 255)
        assert hex_to_rgb_tuple("#4f46e5") == (79, 70, 229)

    def test_lowercase_hex_converts(self):
        """Lowercase hex should work."""
        assert hex_to_rgb_tuple("#abcdef") == (171, 205, 239)

    def test_invalid_hex_falls_back(self):
        """Invalid hex should fallback to gray RGB."""
        # This function assumes sanitized input, but should handle errors gracefully
        assert hex_to_rgb_tuple("#zzzzzz") == (220, 220, 220)
        assert hex_to_rgb_tuple("") == (220, 220, 220)


@pytest.mark.django_db
class TestBuildBrandingContext:
    """Integration tests for build_branding_context."""

    def test_sanitizes_malicious_brand_color(self):
        """Malicious brand color should be sanitized."""
        team = Team.objects.create(
            name="Evil Corp",
            branding_info={
                "brand_color": "#000; } </style><script>alert('xss')</script><style>",
                "branding_enabled": True,
            },
        )

        context = build_branding_context(team)

        # Should fall back to DEFAULT_BRAND_COLOR, not gray
        assert context["brand_color"] == DEFAULT_BRAND_COLOR
        assert context["branding_enabled"] is True
        assert "<script>" not in context["brand_color"]

    def test_sanitizes_malicious_accent_color(self):
        """Malicious accent color should be sanitized."""
        team = Team.objects.create(
            name="Evil Corp",
            branding_info={
                "accent_color": "'; DROP TABLE teams; --",
                "branding_enabled": True,
            },
        )

        context = build_branding_context(team)

        # Should fall back to DEFAULT_ACCENT_COLOR, not gray
        assert context["accent_color"] == DEFAULT_ACCENT_COLOR

    def test_none_team_returns_safe_defaults(self):
        """None team should return safe default context."""
        context = build_branding_context(None)

        assert context["branding_enabled"] is False
        assert context["brand_color"] == DEFAULT_BRAND_COLOR
        assert context["accent_color"] == DEFAULT_ACCENT_COLOR
        assert context["brand_color_rgb"] == "79, 102, 220"
        assert context["accent_color_rgb"] == "79, 102, 220"

    def test_branding_disabled_returns_defaults(self):
        """Team with branding disabled should return defaults."""
        team = Team.objects.create(
            name="No Branding Team",
            branding_info={
                "branding_enabled": False,
            },
        )

        context = build_branding_context(team)

        assert context["branding_enabled"] is False
        assert context["brand_color"] == DEFAULT_BRAND_COLOR
        assert context["accent_color"] == DEFAULT_ACCENT_COLOR

    def test_valid_colors_pass_through(self):
        """Valid colors should pass through and RGB should be computed."""
        team = Team.objects.create(
            name="Valid Colors Team",
            branding_info={
                "brand_color": "#123456",
                "accent_color": "#abcdef",
                "branding_enabled": True,
            },
        )

        context = build_branding_context(team)

        assert context["brand_color"] == "#123456"
        assert context["accent_color"] == "#abcdef"
        assert context["brand_color_rgb"] == "18, 52, 86"
        assert context["accent_color_rgb"] == "171, 205, 239"
        assert context["branding_enabled"] is True

    def test_empty_colors_use_defaults(self):
        """Empty color strings should use defaults."""
        team = Team.objects.create(
            name="Empty Colors Team",
            branding_info={
                "brand_color": "",
                "accent_color": "",
                "branding_enabled": True,
            },
        )

        context = build_branding_context(team)

        assert context["brand_color"] == DEFAULT_BRAND_COLOR
        assert context["accent_color"] == DEFAULT_ACCENT_COLOR

    def test_rgb_values_precomputed(self):
        """RGB values should be pre-computed as strings."""
        team = Team.objects.create(
            name="RGB Test Team",
            branding_info={
                "brand_color": "#ff0000",
                "accent_color": "#00ff00",
                "branding_enabled": True,
            },
        )

        context = build_branding_context(team)

        # RGB values should be comma-separated strings
        assert isinstance(context["brand_color_rgb"], str)
        assert context["brand_color_rgb"] == "255, 0, 0"
        assert context["accent_color_rgb"] == "0, 255, 0"

    def test_accent_color_dark_computed(self):
        """Darkened accent color should be computed."""
        team = Team.objects.create(
            name="Dark Color Team",
            branding_info={
                "accent_color": "#6366f1",
                "branding_enabled": True,
            },
        )

        context = build_branding_context(team)

        assert "accent_color_dark" in context
        # Should be a valid hex color
        assert context["accent_color_dark"].startswith("#")
        assert len(context["accent_color_dark"]) == 7
