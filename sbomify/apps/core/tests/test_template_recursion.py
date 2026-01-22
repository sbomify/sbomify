"""Test that all templates can be rendered without infinite recursion.

This test suite ensures that no template accidentally includes itself,
which can happen when documentation comments use {# ... #} syntax
(single-line only in Django) instead of {% comment %}...{% endcomment %}
for multi-line comments containing {% include %} examples.
"""

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
            except TemplateSyntaxError:
                # Some templates use Jinja2-only syntax (macros, etc.)
                # that Django's engine can't parse. Skip them.
                pytest.skip(f"Template uses Jinja2-only syntax: {template_name}")
                return

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
