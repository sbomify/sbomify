import pytest

from sbomify.apps.teams.templatetags.teams import (
    avatar_color_index,
    modulo,
    workspace_display,
    workspace_initials,
)


class TestWorkspaceDisplay:
    def test_none_returns_workspace(self):
        assert workspace_display(None) == "Workspace"

    def test_empty_string_returns_workspace(self):
        assert workspace_display("") == "Workspace"

    def test_adds_suffix(self):
        assert workspace_display("John") == "John's Workspace"

    def test_preserves_existing_suffix(self):
        assert workspace_display("John's Workspace") == "John's Workspace"

    def test_preserves_curly_apostrophe_suffix(self):
        assert workspace_display("John's Workspace") == "John's Workspace"

    def test_strips_whitespace(self):
        assert workspace_display("  John  ") == "John's Workspace"


class TestModulo:
    def test_basic_modulo(self):
        assert modulo(10, 3) == 1
        assert modulo(15, 5) == 0
        assert modulo(7, 4) == 3

    def test_string_inputs(self):
        assert modulo("10", "3") == 1
        assert modulo("15", "5") == 0

    def test_invalid_value_returns_zero(self):
        assert modulo("abc", 3) == 0
        assert modulo(10, "xyz") == 0
        assert modulo(None, 3) == 0

    def test_float_truncates(self):
        assert modulo(10.7, 3) == 1


class TestAvatarColorIndex:
    def test_none_returns_zero(self):
        assert avatar_color_index(None) == 0

    def test_empty_string_returns_zero(self):
        assert avatar_color_index("") == 0

    def test_alphabetic_mapping(self):
        # A=0, B=1, C=2, D=3, E=4, F=0 (wraps)
        assert avatar_color_index("Apple") == 0
        assert avatar_color_index("Banana") == 1
        assert avatar_color_index("Cherry") == 2
        assert avatar_color_index("Date") == 3
        assert avatar_color_index("Elderberry") == 4
        assert avatar_color_index("Fig") == 0  # wraps

    def test_case_insensitive(self):
        assert avatar_color_index("apple") == avatar_color_index("Apple")
        assert avatar_color_index("APPLE") == avatar_color_index("apple")

    def test_numeric_first_char(self):
        # Non-alpha uses ord % 5
        result = avatar_color_index("123 Company")
        assert 0 <= result <= 4

    def test_strips_whitespace(self):
        assert avatar_color_index("  Apple") == avatar_color_index("Apple")


class TestWorkspaceInitials:
    def test_none_returns_ws(self):
        assert workspace_initials(None) == "WS"

    def test_empty_string_returns_ws(self):
        assert workspace_initials("") == "WS"

    def test_single_word_two_letters(self):
        assert workspace_initials("Apple") == "AP"
        assert workspace_initials("Go") == "GO"

    def test_single_char_word(self):
        assert workspace_initials("A") == "A"

    def test_two_words_uses_first_letters(self):
        assert workspace_initials("John Doe") == "JD"
        assert workspace_initials("Acme Corporation") == "AC"

    def test_strips_workspace_suffix(self):
        assert workspace_initials("John's Workspace") == "JO"

    def test_strips_curly_apostrophe_suffix(self):
        assert workspace_initials("John's Workspace") == "JO"

    def test_multiple_words_uses_first_two(self):
        assert workspace_initials("Acme Corp Industries") == "AC"

    def test_whitespace_handling(self):
        assert workspace_initials("  John  Doe  ") == "JD"
