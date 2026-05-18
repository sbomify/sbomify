"""Unit tests for the public-trust-center helpers.

Focused tests for the Place-removal helper. The view-level integration
test (``test_doc_public.py::test_signature_place_is_removed_in_public_render``)
covers the wiring end-to-end; this file exercises the markdown
substitution in isolation.
"""

from __future__ import annotations

from sbomify.apps.compliance.views._public_helpers import remove_signature_place_for_public


class TestRemoveSignaturePlaceForPublic:
    def test_drops_place_bullet_entirely(self):
        markdown = (
            "## Signed for and on behalf of the manufacturer\n"
            "\n"
            "- **Place:** Berlin, Germany\n"
            "- **Date:** 2026-05-18\n"
        )
        out = remove_signature_place_for_public(markdown)
        assert "Place" not in out
        assert "Berlin" not in out
        assert "Germany" not in out
        # The rest of the section is untouched.
        assert "- **Date:** 2026-05-18" in out
        assert "Signed for and on behalf of the manufacturer" in out

    def test_keeps_other_signature_fields_intact(self):
        markdown = (
            "- **Place:** Tokyo, Japan\n"
            "- **Date:** 2026-05-18\n"
            "- **Name:** Renat Galimov\n"
            "- **Function:** CTO\n"
        )
        out = remove_signature_place_for_public(markdown)
        assert "Tokyo" not in out
        assert "Place" not in out
        assert "- **Date:** 2026-05-18" in out
        assert "- **Name:** Renat Galimov" in out
        assert "- **Function:** CTO" in out

    def test_idempotent_when_place_already_absent(self):
        already = "- **Date:** 2026-05-18\n- **Name:** Test\n"
        assert remove_signature_place_for_public(already) == already

    def test_drops_blank_template_placeholder_too(self):
        """The DoC template renders ``_______________`` for an unsigned
        section. That isn't sensitive but the helper still drops it so
        the public surface is consistent regardless of sign state."""
        markdown = "- **Place:** _______________\n- **Date:** 2026-05-18\n"
        out = remove_signature_place_for_public(markdown)
        assert "Place" not in out
        assert "- **Date:** 2026-05-18" in out

    def test_no_change_when_place_line_absent(self):
        markdown = "## Some Other Section\n\n- **Date:** 2026-05-18\n"
        assert remove_signature_place_for_public(markdown) == markdown

    def test_only_matches_full_line_bullet(self):
        """Inline 'Place:' references mid-paragraph must not be touched —
        only the leading-bullet form the DoC template emits."""
        markdown = "The **Place:** field is required. Here is unrelated text.\n"
        # Not a leading-bullet line, so unchanged.
        assert remove_signature_place_for_public(markdown) == markdown

    def test_handles_unicode_place_value(self):
        markdown = (
            "- **Place:** Naberezhnye Chelny, Russian Federation 🇷🇺\n"
            "- **Date:** 2026-05-18\n"
        )
        out = remove_signature_place_for_public(markdown)
        assert "Naberezhnye Chelny" not in out
        assert "Russian Federation" not in out
        assert "🇷🇺" not in out
        assert "Place" not in out
        # Adjacent bullet kept intact.
        assert "- **Date:** 2026-05-18" in out

    def test_only_one_place_line_removed_when_doc_has_one(self):
        markdown = (
            "## Signed for and on behalf of the manufacturer\n"
            "\n"
            "- **Place:** Berlin, Germany\n"
            "- **Date:** 2026-05-18\n"
            "- **Name:** Test User\n"
        )
        out = remove_signature_place_for_public(markdown)
        # Other bullets and the blank-line spacing preserved.
        assert out.count("**Date:**") == 1
        assert out.count("**Name:**") == 1
        assert out.count("**Place:**") == 0

    def test_removes_place_when_it_is_the_last_line_without_trailing_newline(self):
        """Edge case: if the S3 markdown is trimmed (or the DoC template
        ever changes so Place sits at end-of-file), the bullet must
        still be stripped — otherwise the sensitive value leaks just
        because the doc happened to not end with ``\\n``."""
        markdown = "- **Date:** 2026-05-18\n- **Place:** Paris, France"  # no trailing newline
        out = remove_signature_place_for_public(markdown)
        assert "Place" not in out
        assert "Paris" not in out
        assert "- **Date:** 2026-05-18" in out
