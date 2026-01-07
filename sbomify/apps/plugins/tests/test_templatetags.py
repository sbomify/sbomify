"""Tests for plugins template tags and filters."""

from sbomify.apps.plugins.templatetags.plugins_extras import (
    format_finding_description,
    format_run_reason,
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
