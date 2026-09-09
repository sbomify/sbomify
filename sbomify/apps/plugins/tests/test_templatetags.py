"""Tests for plugins template tags and filters."""

from sbomify.apps.plugins.templatetags.plugins_extras import (
    advisory_prose,
    format_finding_description,
    format_run_reason,
    has_compliance_failures,
    status_border_class,
    status_icon,
    status_text_class,
)


class TestFormatRunReason:
    """Tests for format_run_reason filter."""

    def test_on_upload(self) -> None:
        assert format_run_reason("on_upload") == "Upload"

    def test_manual(self) -> None:
        assert format_run_reason("manual") == "Manual"

    def test_scheduled(self) -> None:
        assert format_run_reason("scheduled") == "Scheduled"

    def test_config_change(self) -> None:
        assert format_run_reason("config_change") == "Config Change"

    def test_migration(self) -> None:
        assert format_run_reason("migration") == "Migration"

    def test_unknown_returns_original(self) -> None:
        assert format_run_reason("unknown_reason") == "unknown_reason"


class TestStatusBorderClass:
    """Tests for status_border_class filter."""

    def test_pass(self) -> None:
        assert status_border_class("pass") == "border-success"

    def test_fail(self) -> None:
        assert status_border_class("fail") == "border-warning"

    def test_error(self) -> None:
        assert status_border_class("error") == "border-danger"

    def test_warning(self) -> None:
        assert status_border_class("warning") == "border-info"

    def test_info(self) -> None:
        assert status_border_class("info") == "border-secondary"

    def test_unknown_returns_secondary(self) -> None:
        assert status_border_class("unknown") == "border-secondary"


class TestStatusTextClass:
    """Tests for status_text_class filter."""

    def test_pass(self) -> None:
        assert status_text_class("pass") == "text-success"

    def test_fail(self) -> None:
        assert status_text_class("fail") == "text-warning"

    def test_error(self) -> None:
        assert status_text_class("error") == "text-danger"

    def test_warning(self) -> None:
        assert status_text_class("warning") == "text-info"

    def test_info(self) -> None:
        assert status_text_class("info") == "text-secondary"

    def test_unknown_returns_secondary(self) -> None:
        assert status_text_class("unknown") == "text-secondary"


class TestStatusIcon:
    """Tests for status_icon filter."""

    def test_pass(self) -> None:
        assert status_icon("pass") == "fas fa-check-circle"

    def test_fail(self) -> None:
        assert status_icon("fail") == "fas fa-times-circle"

    def test_warning(self) -> None:
        assert status_icon("warning") == "fas fa-exclamation-circle"

    def test_error(self) -> None:
        assert status_icon("error") == "fas fa-exclamation-triangle"

    def test_info(self) -> None:
        assert status_icon("info") == "fas fa-info-circle"

    def test_unknown_returns_info(self) -> None:
        assert status_icon("unknown") == "fas fa-info-circle"


class TestFormatFindingDescription:
    """Tests for format_finding_description filter."""

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert format_finding_description("") == ""

    def test_none_returns_empty(self) -> None:
        """None returns empty string."""
        assert format_finding_description(None) == ""

    def test_no_missing_for_returns_escaped(self) -> None:
        """Text without 'Missing for:' is escaped and returned."""
        result = format_finding_description("Simple description text")
        assert result == "Simple description text"

    def test_missing_for_with_packages(self) -> None:
        """'Missing for:' with package list is formatted with styled spans."""
        desc = "Name of entity. Missing for: pkg1, pkg2, pkg3"
        result = format_finding_description(desc)

        assert "missing-packages" in result
        assert 'class="pkg"' in result
        assert "pkg1" in result
        assert "pkg2" in result
        assert "pkg3" in result

    def test_missing_for_with_many_packages(self) -> None:
        """'Missing for:' with many packages shows expandable list."""
        desc = "Description. Missing for: pkg1, pkg2, pkg3, pkg4, pkg5, pkg6, pkg7"
        result = format_finding_description(desc)

        assert "missing-packages" in result
        assert "pkg1" in result
        assert "pkg7" in result
        # Should have toggle button since >5 packages
        assert "pkg-toggle" in result
        assert "Show all 7" in result

    def test_not_found_in_pattern(self) -> None:
        """'Not found in:' pattern is also recognized."""
        desc = "Component version. Not found in: comp1, comp2"
        result = format_finding_description(desc)

        assert "missing-packages" in result
        assert "comp1" in result
        assert "comp2" in result

    def test_missing_in_pattern(self) -> None:
        """'Missing in:' pattern is also recognized."""
        desc = "Supplier info. Missing in: supplier1, supplier2"
        result = format_finding_description(desc)

        assert "missing-packages" in result
        assert "supplier1" in result
        assert "supplier2" in result

    def test_html_escaping(self) -> None:
        """HTML special characters are escaped."""
        desc = "Test. Missing for: <script>alert('xss')</script>"
        result = format_finding_description(desc)

        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_long_path_with_title(self) -> None:
        """Long paths get title attribute for tooltip."""
        desc = "Missing for: /home/runner/work/project/dist/component"
        result = format_finding_description(desc)

        assert 'title="/home/runner/work/project/dist/component"' in result

    def test_case_insensitive_matching(self) -> None:
        """Pattern matching is case insensitive."""
        desc = "Test. MISSING FOR: pkg1, pkg2"
        result = format_finding_description(desc)

        assert "missing-packages" in result
        assert "pkg1" in result

    def test_long_list_has_hidden_packages(self) -> None:
        """Lists with more than 5 packages have hidden items and toggle."""
        desc = "Test. Missing for: pkg1, pkg2, pkg3, pkg4, pkg5, pkg6, pkg7"
        result = format_finding_description(desc)

        # First 5 should be visible (no pkg-hidden class)
        assert 'class="pkg"' in result  # At least some visible
        # Items after 5 should be hidden
        assert "pkg-hidden" in result
        # Should have toggle button to expand the 7 actual packages
        assert "pkg-toggle" in result
        assert "Show all 7" in result

    def test_short_list_no_toggle(self) -> None:
        """Lists with 5 or fewer packages don't have toggle button."""
        desc = "Test. Missing for: pkg1, pkg2, pkg3"
        result = format_finding_description(desc)

        assert "missing-packages" in result
        assert "pkg1" in result
        # No toggle needed for short lists
        assert "pkg-toggle" not in result


class TestHasComplianceFailures:
    """Tests for has_compliance_failures filter."""

    def test_none_returns_false(self) -> None:
        """None input returns False."""
        assert has_compliance_failures(None) is False

    def test_empty_dict_returns_false(self) -> None:
        """Empty dict returns False."""
        assert has_compliance_failures({}) is False

    def test_empty_latest_runs_returns_false(self) -> None:
        """Empty latest_runs list returns False."""
        assert has_compliance_failures({"latest_runs": []}) is False

    def test_no_compliance_runs_returns_false(self) -> None:
        """Non-compliance runs don't trigger CTA."""
        data = {
            "latest_runs": [
                {
                    "category": "security",
                    "status": "completed",
                    "result": {"summary": {"fail_count": 5, "error_count": 0}},
                },
                {
                    "category": "license",
                    "status": "completed",
                    "result": {"summary": {"fail_count": 3, "error_count": 0}},
                },
            ]
        }
        assert has_compliance_failures(data) is False

    def test_compliance_passing_returns_false(self) -> None:
        """Passing compliance runs don't trigger CTA."""
        data = {
            "latest_runs": [
                {
                    "category": "compliance",
                    "status": "completed",
                    "result": {"summary": {"fail_count": 0, "error_count": 0}},
                }
            ]
        }
        assert has_compliance_failures(data) is False

    def test_compliance_with_fail_count_returns_true(self) -> None:
        """Compliance run with fail_count > 0 triggers CTA."""
        data = {
            "latest_runs": [
                {
                    "category": "compliance",
                    "status": "completed",
                    "result": {"summary": {"fail_count": 2, "error_count": 0}},
                }
            ]
        }
        assert has_compliance_failures(data) is True

    def test_compliance_with_error_count_returns_true(self) -> None:
        """Compliance run with error_count > 0 triggers CTA."""
        data = {
            "latest_runs": [
                {
                    "category": "compliance",
                    "status": "completed",
                    "result": {"summary": {"fail_count": 0, "error_count": 1}},
                }
            ]
        }
        assert has_compliance_failures(data) is True

    def test_compliance_run_failed_status_returns_true(self) -> None:
        """Compliance run with 'failed' status (execution error) triggers CTA."""
        data = {
            "latest_runs": [
                {
                    "category": "compliance",
                    "status": "failed",
                    "error_message": "Plugin execution failed",
                }
            ]
        }
        assert has_compliance_failures(data) is True

    def test_compliance_pending_returns_false(self) -> None:
        """Pending compliance runs don't trigger CTA."""
        data = {
            "latest_runs": [
                {
                    "category": "compliance",
                    "status": "pending",
                }
            ]
        }
        assert has_compliance_failures(data) is False

    def test_compliance_running_returns_false(self) -> None:
        """Running compliance runs don't trigger CTA."""
        data = {
            "latest_runs": [
                {
                    "category": "compliance",
                    "status": "running",
                }
            ]
        }
        assert has_compliance_failures(data) is False

    def test_mixed_runs_with_compliance_failure_returns_true(self) -> None:
        """Mixed runs where one compliance run has failures triggers CTA."""
        data = {
            "latest_runs": [
                {
                    "category": "security",
                    "status": "completed",
                    "result": {"summary": {"fail_count": 10, "error_count": 0}},
                },
                {
                    "category": "compliance",
                    "status": "completed",
                    "result": {"summary": {"fail_count": 0, "error_count": 0}},
                },
                {
                    "category": "compliance",
                    "status": "completed",
                    "result": {"summary": {"fail_count": 1, "error_count": 0}},
                },
            ]
        }
        assert has_compliance_failures(data) is True

    def test_missing_result_returns_false(self) -> None:
        """Compliance run with missing result doesn't crash."""
        data = {
            "latest_runs": [
                {
                    "category": "compliance",
                    "status": "completed",
                    "result": None,
                }
            ]
        }
        assert has_compliance_failures(data) is False

    def test_missing_summary_returns_false(self) -> None:
        """Compliance run with missing summary doesn't crash."""
        data = {
            "latest_runs": [
                {
                    "category": "compliance",
                    "status": "completed",
                    "result": {},
                }
            ]
        }
        assert has_compliance_failures(data) is False


class TestVulnerabilityTotal:
    """The count the card shows is the by_severity sum and nothing else."""

    def test_sums_the_severity_map(self):
        from sbomify.apps.plugins.templatetags.plugins_extras import vulnerability_total

        assert vulnerability_total({"by_severity": {"critical": 2, "high": 1, "low": 0}}) == 3

    def test_non_dict_shapes_count_zero(self):
        from sbomify.apps.plugins.templatetags.plugins_extras import vulnerability_total

        assert vulnerability_total(None) == 0
        assert vulnerability_total("summary") == 0
        assert vulnerability_total({"by_severity": "high"}) == 0
        assert vulnerability_total({"by_severity": None}) == 0

    def test_non_integer_values_do_not_count(self):
        from sbomify.apps.plugins.templatetags.plugins_extras import vulnerability_total

        assert vulnerability_total({"by_severity": {"critical": "2", "high": 1.5, "low": None}}) == 0

    def test_a_stray_boolean_is_not_a_vulnerability(self):
        from sbomify.apps.plugins.templatetags.plugins_extras import vulnerability_total

        assert vulnerability_total({"by_severity": {"critical": True, "high": 2}}) == 2


class TestAdvisoryProse:
    """OSV serves GHSA's CommonMark verbatim, and the cards show the opening
    words of it, so the markup has to come off before the text is cut."""

    def test_the_advisory_that_was_rendering_its_own_markup(self) -> None:
        """The fast-uri body, as it reached the page on production."""
        body = (
            "### Impact\n"
            "`fast-uri` decodes percent-encoded characters in the scheme component "
            "with the legacy global `unescape()` and serializes the result back.\n"
        )

        assert advisory_prose(body) == (
            "Impact fast-uri decodes percent-encoded characters in the scheme component "
            "with the legacy global unescape() and serializes the result back."
        )

    def test_headings_of_every_depth_lose_their_markers(self) -> None:
        assert advisory_prose("# One\n## Two\n###### Six") == "One Two Six"

    def test_a_hash_that_is_not_a_heading_is_left_alone(self) -> None:
        """C# is a language and #1 is an issue number; neither opens a heading."""
        assert advisory_prose("Affects C# and issue #1") == "Affects C# and issue #1"

    def test_links_keep_their_text_and_lose_their_target(self) -> None:
        assert advisory_prose("See [the advisory](https://example.test/a) for more") == ("See the advisory for more")

    def test_an_image_keeps_its_alt_text(self) -> None:
        assert advisory_prose("![a diagram](https://example.test/d.png) shows it") == "a diagram shows it"

    def test_emphasis_markers_come_off(self) -> None:
        assert advisory_prose("**Critical** and _urgent_ and *both*") == "Critical and urgent and both"

    def test_a_dunder_survives_being_bold_shaped(self) -> None:
        """__init__ and __reduce__ are the shape of underscore bold. An advisory
        about pickle or prototype pollution is written almost entirely in them,
        and the identifier is the thing the reader came for."""
        assert advisory_prose("calls `__init__` then `__reduce__`") == "calls __init__ then __reduce__"
        assert advisory_prose("pollutes __proto__ on every merge") == "pollutes __proto__ on every merge"
        assert advisory_prose("the __init__ method") == "the __init__ method"

    def test_underscore_bold_around_words_still_comes_off(self) -> None:
        assert advisory_prose("__Impact__ is high") == "Impact is high"

    def test_a_code_span_keeps_whatever_it_holds(self) -> None:
        """Backticks mean literal, so nothing inside one is read as markup."""
        assert advisory_prose("the `*` wildcard") == "the * wildcard"
        assert advisory_prose("send `#include <x>` first") == "send #include <x> first"
        assert advisory_prose("read `a_b_c` from disk") == "read a_b_c from disk"

    def test_a_bare_underscore_inside_a_name_survives(self) -> None:
        """Package and symbol names carry underscores, and they are not emphasis."""
        assert advisory_prose("calls parse_uri_string on every request") == "calls parse_uri_string on every request"

    def test_lists_quotes_and_fences_flatten_to_a_sentence(self) -> None:
        body = "> Note\n\n- first\n- second\n\n1. one\n\n```py\ncode()\n```"

        assert advisory_prose(body) == "Note first second one code()"

    def test_a_github_alert_marker_comes_off_with_its_quote(self) -> None:
        """GHSA advisories open with one, and it rides inside a block quote, so
        removing the quote marker alone left the marker sitting in the prose."""
        body = "> [!NOTE]\n> Scored assuming a deployment where policy is a boundary."

        assert advisory_prose(body) == "Scored assuming a deployment where policy is a boundary."

    def test_a_thematic_break_leaves_nothing_behind(self) -> None:
        assert advisory_prose("Before\n\n---\n\nAfter") == "Before After"

    def test_empty_and_non_string_input(self) -> None:
        assert advisory_prose("") == ""
        assert advisory_prose(None) == ""
        assert advisory_prose(3) == ""

    def test_an_oversized_body_is_returned_rather_than_scanned(self) -> None:
        body = "#" * 200_001

        assert advisory_prose(body) == body

    def test_plain_prose_is_unchanged(self) -> None:
        assert advisory_prose("A plain sentence about a package.") == "A plain sentence about a package."
