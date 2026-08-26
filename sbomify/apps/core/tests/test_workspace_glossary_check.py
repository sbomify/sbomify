"""The gate that keeps new code off the retired tenant words.

It reads a diff rather than the tree on purpose: `team_key` appears about 1200
times and retiring it is a staged job, so the check rejects only newly added
lines and lets the count fall as files are touched.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core import glossary


def _diff(path: str, *added: str, removed: tuple[str, ...] = ()) -> str:
    body = "\n".join(f"-{line}" for line in removed) + "\n" if removed else ""
    body += "\n".join(f"+{line}" for line in added)
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}\n"


class TestAddedOffences:
    def test_a_new_line_using_a_retired_word_is_caught(self):
        diff = _diff("sbomify/apps/core/views.py", '    key = request.session["current_team"]["key"]')

        offences = glossary.added_offences(diff)

        assert [(o[0], o[1]) for o in offences] == [("sbomify/apps/core/views.py", "current_team")]

    def test_a_removed_line_is_not_an_offence(self):
        """Deleting the old word is the point, not a violation."""
        diff = _diff("sbomify/apps/core/views.py", "    key = workspace_key", removed=("    key = team_key",))

        assert glossary.added_offences(diff) == []

    def test_the_teams_app_may_say_team(self):
        """It owns the model and its own vocabulary."""
        diff = _diff("sbomify/apps/teams/utils.py", "    return request.session['current_team']")

        assert glossary.added_offences(diff) == []

    @pytest.mark.parametrize("path", ["sbomify/apps/core/migrations/0009_x.py", "sbomify/apps/core/tests/test_x.py"])
    def test_migrations_and_tests_are_exempt(self, path):
        """Migrations are frozen history; tests follow what they test."""
        assert glossary.added_offences(_diff(path, "    team_key = models.CharField()")) == []

    def test_workspace_key_does_not_trip_on_the_team_key_inside_it(self):
        """Word boundaries: the replacement must not flag itself."""
        diff = _diff("sbomify/apps/core/views.py", "    workspace_key = resolve(request)")

        assert glossary.added_offences(diff) == []

    def test_every_retired_word_maps_to_its_replacement(self):
        """A word with no replacement would print 'team_key -> None' at someone."""
        assert all(replacement for replacement in glossary.RETIRED.values())

    def test_several_offences_in_one_diff_are_all_reported(self):
        diff = _diff(
            "sbomify/apps/core/views.py",
            "    a = team_key",
            "    b = user_teams",
        )

        assert {o[1] for o in glossary.added_offences(diff)} == {"team_key", "user_teams"}

    def test_a_line_whose_content_starts_with_plus_plus_is_still_scanned(self):
        """Only "+++ " with the space is a diff header. C and JS lines are not."""
        diff = _diff("sbomify/apps/core/x.c", "++team_key;")

        assert [o[1] for o in glossary.added_offences(diff)] == ["team_key"]

    def test_the_wrapper_script_is_not_exempt(self):
        """It names no retired word, so exempting it would only blind the gate."""
        assert not glossary.is_exempt("bin/check_workspace_glossary.py")

    def test_the_module_that_defines_them_is_exempt(self):
        """Otherwise the dictionary keys would flag themselves."""
        assert glossary.is_exempt("sbomify/apps/core/glossary.py")
