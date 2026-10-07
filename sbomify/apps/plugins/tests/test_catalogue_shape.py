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
def test_rows_follow_the_order_the_page_renders_its_categories() -> None:
    # Compliance leads the settings page whatever its size, so a bigger security
    # section must not hand the compliance card the taller placeholder.
    RegisteredPlugin.objects.all().delete()
    _plugin("ntia", "compliance")
    _plugin("osv", "security")
    _plugin("grype", "security")
    _plugin("trivy", "security")

    shape = get_catalogue_shape()

    assert shape.value["section_rows"] == [1, 3]


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


@pytest.mark.django_db
@pytest.mark.parametrize(("registered", "heading_drawn"), [(True, True), (False, False)])
def test_the_frame_draws_the_list_heading_only_when_sections_arrive(
    client, sample_team_with_owner_member, registered: bool, heading_drawn: bool
) -> None:
    """An empty catalogue loads as "No plugins available", with no section heading
    or save action, so its placeholder must not draw a heading that never arrives."""
    from django.urls import reverse

    from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

    RegisteredPlugin.objects.all().delete()
    if registered:
        _plugin("ntia", "compliance")
    member = sample_team_with_owner_member
    setup_authenticated_client_session(client, member.team, member.user)

    html = client.get(reverse("plugins:plugins_page")).content.decode()

    # The heading's title skeleton is the only 12rem-wide one on the page.
    assert ("width: 12rem" in html) is heading_drawn
