"""The plugins page frame sizes its skeletons from the catalogue."""

import pytest

from sbomify.apps.plugins.models import RegisteredPlugin
from sbomify.apps.plugins.services.catalogue import get_catalogue_shape


def _plugin(name: str, category: str, *, is_enabled: bool = True) -> RegisteredPlugin:
    return RegisteredPlugin.objects.create(
        name=name,
        display_name=name.title(),
        category=category,
        version="1.0.0",
        plugin_class_path=f"sbomify.apps.plugins.builtins.{name}.Plugin",
        is_enabled=is_enabled,
        is_builtin=True,
    )


@pytest.mark.django_db
def test_shape_counts_one_card_per_category_and_one_row_per_plugin() -> None:
    RegisteredPlugin.objects.all().delete()
    _plugin("ntia", "compliance")
    _plugin("cisa", "compliance")
    _plugin("bsi", "compliance")
    _plugin("osv", "security")

    shape = get_catalogue_shape()

    assert shape.ok
    # Two fixed totals (available, enabled) plus one card per category.
    assert shape.value["stat_cards"] == 4
    # One card per category, holding that category's plugins.
    assert shape.value["section_rows"] == [3, 1]


@pytest.mark.django_db
def test_a_disabled_plugin_is_not_a_row_the_page_will_draw() -> None:
    RegisteredPlugin.objects.all().delete()
    _plugin("ntia", "compliance")
    _plugin("retired", "compliance", is_enabled=False)

    shape = get_catalogue_shape()

    assert shape.value["section_rows"] == [1]
    assert shape.value["stat_cards"] == 3


@pytest.mark.django_db
def test_an_empty_catalogue_asks_for_no_cards() -> None:
    RegisteredPlugin.objects.all().delete()

    shape = get_catalogue_shape()

    assert shape.value["section_rows"] == []
    assert shape.value["stat_cards"] == 2
