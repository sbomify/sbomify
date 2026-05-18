"""Unit tests for the public-trust-center helpers.

Focused tests for the place-redaction helper. The view-level integration
test (``test_doc_public.py::test_signature_place_is_redacted_in_public_render``)
covers the wiring end-to-end; this file exercises the markdown
substitution in isolation.
"""

from __future__ import annotations

from sbomify.apps.compliance.views._public_helpers import redact_signature_place_for_public


class TestRedactSignaturePlaceForPublic:
    def test_replaces_place_value_with_redacted_placeholder(self):
        markdown = (
            "## Signed for and on behalf of the manufacturer\n"
            "\n"
            "- **Place:** Berlin, Germany\n"
            "- **Date:** 2026-05-18\n"
        )
        out = redact_signature_place_for_public(markdown)
        assert "- **Place:** _Redacted_" in out
        assert "Berlin" not in out
        assert "Germany" not in out

    def test_keeps_other_signature_fields_intact(self):
        markdown = (
            "- **Place:** Tokyo, Japan\n"
            "- **Date:** 2026-05-18\n"
            "- **Name:** Renat Galimov\n"
            "- **Function:** CTO\n"
        )
        out = redact_signature_place_for_public(markdown)
        assert "Tokyo" not in out
        # Only the Place line is touched.
        assert "- **Date:** 2026-05-18" in out
        assert "- **Name:** Renat Galimov" in out
        assert "- **Function:** CTO" in out

    def test_idempotent_on_already_redacted_input(self):
        already = "- **Place:** _Redacted_\n"
        assert redact_signature_place_for_public(already) == already

    def test_handles_blank_doc_template_placeholder(self):
        """The DoC template renders ``_______________`` for an unsigned
        section. That isn't sensitive but the helper still rewrites it
        to keep the public surface consistent regardless of sign state."""
        markdown = "- **Place:** _______________\n"
        out = redact_signature_place_for_public(markdown)
        assert "- **Place:** _Redacted_" in out

    def test_no_change_when_place_line_absent(self):
        markdown = "## Some Other Section\n\n- **Date:** 2026-05-18\n"
        assert redact_signature_place_for_public(markdown) == markdown

    def test_only_matches_full_line_bullet(self):
        """Inline 'Place:' references mid-paragraph must not be touched —
        only the leading-bullet form the DoC template emits."""
        markdown = "The **Place:** field is required. Here is unrelated text.\n"
        # Not a leading-bullet line, so unchanged.
        assert redact_signature_place_for_public(markdown) == markdown

    def test_handles_unicode_place_value(self):
        markdown = "- **Place:** Naberezhnye Chelny, Russian Federation 🇷🇺\n"
        out = redact_signature_place_for_public(markdown)
        assert "Naberezhnye Chelny" not in out
        assert "Russian Federation" not in out
        assert "🇷🇺" not in out
        assert "- **Place:** _Redacted_" in out
