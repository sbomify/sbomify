from __future__ import annotations

import pytest
from django.template import Context, Template, TemplateDoesNotExist
from django.template.loader import get_template

from sbomify.apps.core.templatetags.design_system import (
    _ALIASES,
    _BLOCK_COMPONENTS,
    _LEAF_COMPONENTS,
    _TEMPLATE_DIR,
)


def render(source: str, **context: object) -> str:
    return Template("{% load design_system %}" + source).render(Context(context))


class TestComponentRegistration:
    """Every registered tag must map to a template that actually exists."""

    @pytest.mark.parametrize("name", _LEAF_COMPONENTS + _BLOCK_COMPONENTS)
    def test_component_template_exists(self, name: str) -> None:
        try:
            get_template(f"{_TEMPLATE_DIR}/{_ALIASES.get(name, name)}.html.j2")
        except TemplateDoesNotExist:  # pragma: no cover - guard, should never fire
            pytest.fail(f"{name} is registered as a component tag but has no template")

    def test_registered_names_are_unique(self) -> None:
        names = _LEAF_COMPONENTS + _BLOCK_COMPONENTS
        assert len(names) == len(set(names))


class TestLeafTags:
    def test_renders_the_component(self) -> None:
        out = render('{% badge text="Overdue" variant="danger" %}')
        assert "tw-badge tw-badge-danger" in out
        assert "Overdue" in out

    def test_variant_defaults_are_applied(self) -> None:
        assert "tw-badge-primary" in render('{% badge text="New" %}')

    def test_extra_classes_are_appended(self) -> None:
        assert "ml-auto" in render('{% badge text="New" class="ml-auto" %}')


class TestBlockTags:
    def test_content_is_placed_inside_the_container(self) -> None:
        out = render('{% page_header title="Releases" %}{% badge text="3" %}{% endpage_header %}')
        assert "tw-page-header" in out
        assert "Releases" in out
        # The badge must land inside the header, after its title.
        assert out.index("tw-page-header-title") < out.index("tw-badge")

    def test_nested_containers_compose(self) -> None:
        out = render(
            '{% page_header title="Products" %}'
            '{% actions_menu label="Product actions" %}<span class="tw-dropdown-item">Open</span>{% endactions_menu %}'
            "{% endpage_header %}"
        )
        assert "tw-page-header" in out
        assert "Product actions" in out
        assert out.index("tw-page-header") < out.index("tw-dropdown-item")

    def test_block_content_still_sees_the_outer_context(self) -> None:
        out = render(
            '{% page_header title="Products" %}{{ product_name }}{% endpage_header %}',
            product_name="Acme Gateway",
        )
        assert "Acme Gateway" in out


class TestAttributePassthrough:
    def test_prefixed_kwargs_become_dashed_attributes(self) -> None:
        out = render('{% button text="Save" hx_post="/save/" hx_target="#panel" %}')
        assert 'hx-post="/save/"' in out
        assert 'hx-target="#panel"' in out
        assert "hx_post" not in out

    def test_alpine_and_aria_and_data_prefixes(self) -> None:
        out = render('{% button text="Go" x_show="open" data_testid="go" aria_label="Go now" %}')
        assert 'x-show="open"' in out
        assert 'data-testid="go"' in out
        assert 'aria-label="Go now"' in out

    def test_true_renders_a_bare_attribute(self) -> None:
        out = render('{% button text="Boost" hx_boost=True %}')
        assert "hx-boost" in out
        assert 'hx-boost="' not in out

    def test_none_and_false_are_omitted(self) -> None:
        out = render('{% button text="Save" hx_get=missing hx_boost=False %}', missing=None)
        assert "hx-get" not in out
        assert "hx-boost" not in out

    def test_attribute_values_are_escaped(self) -> None:
        out = render('{% button text="Save" hx_get=url %}', url='/a"onmouseover="alert(1)')
        assert 'onmouseover="alert(1)' not in out
        assert "&quot;" in out

    def test_raw_attrs_pass_through_for_non_identifier_attributes(self) -> None:
        out = render("""{% button text="Open" attrs='@click="open = true"' %}""")
        assert '@click="open = true"' in out

    def test_raw_attrs_and_prefixed_kwargs_combine(self) -> None:
        out = render("""{% button text="Open" hx_get="/x/" attrs=':class="{ active: on }"' %}""")
        assert 'hx-get="/x/"' in out
        assert ':class="{ active: on }"' in out

    def test_attrs_is_not_leaked_as_a_literal_parameter(self) -> None:
        assert "attrs=" not in render('{% badge text="New" %}')


class TestFormControls:
    """All form inputs come from the library, so their contracts are pinned here."""

    def test_input_renders_label_hint_and_name(self) -> None:
        out = render('{% input name="q" label="Search" hint="Name or id" %}')
        assert 'name="q"' in out
        assert "tw-form-label" in out
        assert "tw-form-hint" in out

    def test_input_error_replaces_hint(self) -> None:
        out = render('{% input name="q" hint="Name or id" error="Required" %}')
        assert "tw-form-error" in out
        assert "tw-form-hint" not in out

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [
            ('{% textarea name="notes" %}', "tw-form-textarea"),
            ('{% select name="kind" options=options %}', "tw-form-select"),
            ('{% checkbox name="agree" label="Agree" %}', "tw-checkbox"),
            ('{% radio name="fmt" value="spdx" label="SPDX" %}', "tw-radio"),
            ('{% toggle name="notify" label="Notify" %}', "tw-toggle"),
        ],
    )
    def test_each_control_uses_its_library_class(self, tag: str, expected: str) -> None:
        assert expected in render(tag, options=[{"value": "spdx", "label": "SPDX"}])

    def test_select_marks_the_selected_option(self) -> None:
        out = render(
            '{% select name="kind" options=options selected="spdx" %}',
            options=[{"value": "cdx", "label": "CycloneDX"}, {"value": "spdx", "label": "SPDX"}],
        )
        assert out.count("selected") == 1
