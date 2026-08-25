"""Security and edge case tests for branding functionality."""

import pytest
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.branding import (
    DEFAULT_ACCENT_COLOR,
    DEFAULT_BRAND_COLOR,
    DEFAULT_FALLBACK_GRAY,
    build_branding_context,
    hex_to_rgb_tuple,
    ink_on_color,
    is_dark_color,
    relative_luminance,
    resolve_brand_color,
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
        assert context["brand_color_rgb"] == "37, 41, 63"
        assert context["accent_color_rgb"] == "66, 99, 235"

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


class TestIsDarkColor:
    """Which of the two inks belongs on a brand colour."""

    @pytest.mark.parametrize(
        "color",
        ["#000000", "#25293F", "#4263EB", "#0000FF", "#7C2D12"],
    )
    def test_dark_colors_take_light_text(self, color):
        assert is_dark_color(color) is True
        assert ink_on_color(color) == "#ffffff"

    @pytest.mark.parametrize(
        "color",
        ["#ffffff", "#FFFF00", "#00FF00", "#FDE68A", "#808080"],
    )
    def test_light_colors_take_dark_text(self, color):
        assert is_dark_color(color) is False
        assert ink_on_color(color) == DEFAULT_BRAND_COLOR

    def test_luminance_not_lightness_decides_it(self):
        """Yellow and blue share an HSL lightness but not a legible ink.

        A lightness-based check calls both mid and would put white on yellow.
        Relative luminance separates them, which is the whole reason this is
        not a one-line brightness average.
        """
        assert is_dark_color("#FFFF00") is False
        assert is_dark_color("#0000FF") is True
        assert relative_luminance("#FFFF00") > relative_luminance("#0000FF")

    def test_the_answer_is_always_the_higher_contrast_ink(self):
        """Whatever the colour, the ink chosen out-contrasts the other one."""
        for color in ["#000000", "#ffffff", "#FF0000", "#4263EB", "#FDE68A", "#808080", "#00FF00"]:
            luminance = relative_luminance(color)
            against_white = 1.05 / (luminance + 0.05)
            against_black = (luminance + 0.05) / 0.05
            assert is_dark_color(color) is (against_white > against_black), color

    def test_unusable_input_falls_back_to_dark_text(self):
        """An unreadable brand must not produce an unreadable answer."""
        assert is_dark_color(None) is False
        assert is_dark_color("not-a-colour") is False
        assert is_dark_color("#000; }</style><script>alert(1)</script>") is False


class TestResolveBrandColor:
    """The accent a branded surface paints with."""

    def test_a_set_brand_is_used(self):
        assert resolve_brand_color("#7C2D12") == "#7C2D12"

    def test_no_brand_falls_back_to_the_platform_accent(self):
        """Not to the neutral gray: an unbranded page still looks like sbomify."""
        assert resolve_brand_color(None) == DEFAULT_ACCENT_COLOR
        assert resolve_brand_color("") == DEFAULT_ACCENT_COLOR
        assert resolve_brand_color(DEFAULT_FALLBACK_GRAY) == DEFAULT_FALLBACK_GRAY

    def test_css_injection_falls_back_rather_than_escaping(self):
        assert resolve_brand_color("#000; }</style><script>alert(1)</script>") == DEFAULT_ACCENT_COLOR

    def test_fill_and_ink_never_measure_different_colors(self):
        """The pair is resolved the same way, so they cannot disagree."""
        for brand in [None, "", "bogus", "#fff", "#25293F"]:
            fill = resolve_brand_color(brand)
            assert ink_on_color(fill) == ink_on_color(resolve_brand_color(brand))
            assert is_dark_color(fill) is (ink_on_color(fill) == "#ffffff")


@pytest.mark.django_db
class TestBrandingOffNotice:
    """The notice that says saved colours are not reaching public pages.

    It was bound with x-show to ``branding_info``, which is Django context and
    never reaches the Alpine scope, so the page threw
    "branding_info is not defined" and the notice never rendered. Nothing
    caught it because nothing rendered the template.
    """

    NOTICE = "Custom branding is off"

    def _render(self, client, team):
        return client.get(reverse("teams:team_branding", kwargs={"team_key": team.key}))

    def test_the_notice_renders_when_branding_is_off(self, client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        team.branding_info = {"branding_enabled": False}
        team.save(update_fields=["branding_info"])
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = self._render(client, team)

        assert response.status_code == 200
        assert self.NOTICE in response.content.decode()

    def test_the_notice_stays_away_when_branding_is_on(self, client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        team.branding_info = {"branding_enabled": True}
        team.save(update_fields=["branding_info"])
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = self._render(client, team)

        assert response.status_code == 200
        assert self.NOTICE not in response.content.decode()

    def test_the_page_names_no_alpine_variable_it_does_not_define(self, client, sample_team_with_owner_member):
        """x-show on a server-only name is invisible until a browser runs it."""
        team = sample_team_with_owner_member.team
        team.branding_info = {"branding_enabled": False}
        team.save(update_fields=["branding_info"])
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        html = self._render(client, team).content.decode()

        assert "branding_info." not in html, "branding_info is Django context, not Alpine state"
