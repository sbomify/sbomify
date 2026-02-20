"""Test that all templates are valid Django templates.

This test suite ensures:
1. No template accidentally includes itself (infinite recursion)
2. All templates have valid Django template syntax (no Jinja2-only constructs)
3. No Jinja2-only variables/filters that silently fail in Django
"""

import re
import sys
from pathlib import Path

import pytest
from django.template import TemplateSyntaxError, engines


def discover_all_templates() -> list[str]:
    """Discover all .j2 template files in the sbomify apps directory.

    Returns:
        List of template paths relative to template directories
        (e.g., 'core/component_item.html.j2')
    """
    templates = []
    # Path: test file -> tests/ -> core/ -> apps/
    base_path = Path(__file__).parent.parent.parent  # sbomify/apps/

    # Find all template directories
    for app_dir in base_path.iterdir():
        if not app_dir.is_dir():
            continue

        templates_dir = app_dir / "templates"
        if not templates_dir.exists():
            continue

        # Find all .j2 files
        for template_file in templates_dir.rglob("*.j2"):
            # Get path relative to templates dir
            relative_path = template_file.relative_to(templates_dir)
            templates.append(str(relative_path))

    return sorted(templates)


def discover_all_template_files() -> list[tuple[str, Path]]:
    """Discover all .j2 template files with their absolute paths.

    Returns:
        List of (relative_name, absolute_path) tuples
    """
    templates = []
    base_path = Path(__file__).parent.parent.parent  # sbomify/apps/

    for app_dir in base_path.iterdir():
        if not app_dir.is_dir():
            continue

        templates_dir = app_dir / "templates"
        if not templates_dir.exists():
            continue

        for template_file in templates_dir.rglob("*.j2"):
            relative_path = template_file.relative_to(templates_dir)
            templates.append((str(relative_path), template_file))

    return sorted(templates, key=lambda t: t[0])


class TestTemplateRecursion:
    """Test that all templates can be loaded and rendered without recursion."""

    @pytest.fixture
    def django_engine(self):
        """Get the Django template engine."""
        return engines["django"]

    def test_all_templates_discovered(self):
        """Sanity check: ensure we discover templates."""
        templates = discover_all_templates()
        assert len(templates) > 0, "Should discover at least some templates"
        # We know these exist
        assert any("component" in t for t in templates)

    @pytest.mark.parametrize("template_name", discover_all_templates())
    def test_template_does_not_cause_recursion(self, django_engine, template_name: str) -> None:
        """Test that loading and rendering a template doesn't cause infinite recursion.

        This catches bugs where multi-line comments using {# ... #} syntax
        contain {% include %} tags that get parsed as real code, causing
        templates to include themselves infinitely.

        Args:
            django_engine: Django template engine fixture
            template_name: Path to the template file
        """
        # Set a lower recursion limit to fail faster on recursion bugs
        original_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(200)

        try:
            # Load the template - this parses it
            try:
                template = django_engine.get_template(template_name)
            except TemplateSyntaxError as e:
                pytest.fail(f"Template has invalid syntax: {template_name}: {e}")

            assert template is not None, f"Template {template_name} should load"

            # Try to render with empty context
            # This will trigger any {% include %} tags that were accidentally
            # parsed from documentation comments
            try:
                template.render({})
            except RecursionError:
                pytest.fail(
                    f"Template '{template_name}' causes infinite recursion. "
                    f"Check for multi-line {{# ... #}} comments containing "
                    f"{{% include %}} tags - use {{% comment %}}...{{% endcomment %}} instead."
                )
            except TemplateSyntaxError:
                # Template syntax errors during render are OK
                pass
            except Exception:
                # Other errors (missing context variables, etc.) are OK
                # We only care about catching RecursionError
                pass

        finally:
            sys.setrecursionlimit(original_limit)


class TestSpecificProblematicTemplates:
    """Test templates that previously had recursion bugs.

    These templates had multi-line {# ... #} comments containing
    {% include %} documentation that caused infinite recursion.
    """

    @pytest.fixture
    def django_engine(self):
        """Get the Django template engine."""
        return engines["django"]

    @pytest.mark.parametrize(
        "template_name,context",
        [
            (
                "plugins/components/public_assessment_badge.html.j2",
                {"assessment": {"category": "compliance", "display_name": "Test"}},
            ),
            (
                "core/components/_empty_state.html.j2",
                {"icon": "fa-test", "title": "Test Title"},
            ),
            (
                "core/components/_loading_indicator.html.j2",
                {"indicator_id": "test-spinner"},
            ),
            (
                "core/components/public_card.html.j2",
                {"title": "Test Card"},
            ),
            (
                "core/components/_form_field.html.j2",
                {},  # Will fail with missing field, but shouldn't recurse
            ),
            (
                "core/components/_page_header.html.j2",
                {"title": "Test Page", "icon": "fa-test"},
            ),
        ],
    )
    def test_previously_buggy_template_renders(self, django_engine, template_name: str, context: dict) -> None:
        """Test that previously buggy templates can render without recursion.

        Args:
            django_engine: Django template engine fixture
            template_name: Path to the template file
            context: Minimal context to render the template
        """
        original_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(200)

        try:
            template = django_engine.get_template(template_name)

            try:
                result = template.render(context)
                # If we get here, rendering succeeded
                assert result is not None
            except RecursionError:
                pytest.fail(f"Template '{template_name}' causes infinite recursion!")
            except Exception:
                # Other errors are OK - we only care about recursion
                pass

        finally:
            sys.setrecursionlimit(original_limit)


# Regex to strip Django template comments before scanning for Jinja2 syntax.
# Matches {# single-line comments #} and {% comment %}...{% endcomment %} blocks.
_COMMENT_RE = re.compile(
    r"\{#.*?#\}"  # single-line comments
    r"|"
    r"\{%[-\s]*comment\s*%\}.*?\{%[-\s]*endcomment\s*%\}",  # block comments
    re.DOTALL,
)

# Jinja2 loop variable patterns that silently resolve to empty in Django.
# Django uses forloop.*, Jinja2 uses loop.* — the Jinja2 forms don't crash,
# they just silently evaluate to "" which causes wrong behavior.
_JINJA2_LOOP_RE = re.compile(
    r"\bloop\."
    r"(?:first|last|index|index0|length|revindex|revindex0|depth|depth0"
    r"|previtem|nextitem|changed|cycle)\b"
)

# Jinja2-only template tags that cause TemplateSyntaxError in Django.
# Included here for completeness — the template loading test also catches these,
# but this gives a clearer error message pointing to the exact line.
_JINJA2_TAG_RE = re.compile(r"\{%[-\s]*(?:set|macro|call|import|from|raw)\b")

# Jinja2-only filters that don't exist in Django.
_JINJA2_FILTER_RE = re.compile(
    r"\|\s*(?:tojson|selectattr|rejectattr|xmlattr|pprint"
    r"|groupby|unique|batch)\b"
)

# Jinja2 inline if-else expression: {{ x if condition else y }}
# Django templates don't support this — they require {% if %} blocks.
_JINJA2_INLINE_IF_RE = re.compile(r"\{\{[^}]*\bif\b[^}]*\belse\b[^}]*\}\}")


def _strip_comments(content: str) -> str:
    """Remove template comments so we don't flag patterns inside comments."""
    return _COMMENT_RE.sub("", content)


class TestNoJinja2Syntax:
    """Static analysis: detect Jinja2-only syntax in Django templates.

    These patterns don't always cause TemplateSyntaxError — some (like loop.last)
    silently resolve to empty strings in Django, producing wrong behavior
    without any error. This test catches them at the source level.
    """

    @pytest.mark.parametrize(
        "template_name,template_path",
        discover_all_template_files(),
        ids=[t[0] for t in discover_all_template_files()],
    )
    def test_no_jinja2_loop_variables(self, template_name: str, template_path: Path) -> None:
        """Templates must use Django's forloop.* instead of Jinja2's loop.*."""
        content = _strip_comments(template_path.read_text())
        matches = _JINJA2_LOOP_RE.findall(content)
        if matches:
            # Find line numbers for better error messages
            lines = []
            for i, line in enumerate(template_path.read_text().splitlines(), 1):
                if _JINJA2_LOOP_RE.search(line):
                    lines.append(f"  line {i}: {line.strip()}")
            pytest.fail(
                f"Template '{template_name}' uses Jinja2 loop variable(s) "
                f"instead of Django's forloop.*:\n" + "\n".join(lines)
            )

    @pytest.mark.parametrize(
        "template_name,template_path",
        discover_all_template_files(),
        ids=[t[0] for t in discover_all_template_files()],
    )
    def test_no_jinja2_tags(self, template_name: str, template_path: Path) -> None:
        """Templates must not use Jinja2-only tags (set, macro, raw, etc.)."""
        content = _strip_comments(template_path.read_text())
        matches = _JINJA2_TAG_RE.findall(content)
        if matches:
            lines = []
            for i, line in enumerate(template_path.read_text().splitlines(), 1):
                if _JINJA2_TAG_RE.search(line):
                    lines.append(f"  line {i}: {line.strip()}")
            pytest.fail(f"Template '{template_name}' uses Jinja2-only tag(s):\n" + "\n".join(lines))

    @pytest.mark.parametrize(
        "template_name,template_path",
        discover_all_template_files(),
        ids=[t[0] for t in discover_all_template_files()],
    )
    def test_no_jinja2_filters(self, template_name: str, template_path: Path) -> None:
        """Templates must not use Jinja2-only filters."""
        content = _strip_comments(template_path.read_text())
        matches = _JINJA2_FILTER_RE.findall(content)
        if matches:
            lines = []
            for i, line in enumerate(template_path.read_text().splitlines(), 1):
                if _JINJA2_FILTER_RE.search(line):
                    lines.append(f"  line {i}: {line.strip()}")
            pytest.fail(f"Template '{template_name}' uses Jinja2-only filter(s):\n" + "\n".join(lines))

    @pytest.mark.parametrize(
        "template_name,template_path",
        discover_all_template_files(),
        ids=[t[0] for t in discover_all_template_files()],
    )
    def test_no_jinja2_inline_if_else(self, template_name: str, template_path: Path) -> None:
        """Templates must not use Jinja2 inline if-else expressions."""
        content = _strip_comments(template_path.read_text())
        matches = _JINJA2_INLINE_IF_RE.findall(content)
        if matches:
            lines = []
            for i, line in enumerate(template_path.read_text().splitlines(), 1):
                if _JINJA2_INLINE_IF_RE.search(line):
                    lines.append(f"  line {i}: {line.strip()}")
            pytest.fail(f"Template '{template_name}' uses Jinja2 inline if-else:\n" + "\n".join(lines))
