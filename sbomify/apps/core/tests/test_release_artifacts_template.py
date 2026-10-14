"""The release artifacts table pages in the browser, so its page size has to reach Alpine as a number."""

from django.template.loader import render_to_string


def test_page_size_select_binds_a_number() -> None:
    html = render_to_string(
        "core/components/release_artifacts.html.j2",
        {"release_id": "r1", "product_id": "p1", "can_edit": False, "is_latest": False},
    )

    select = next(part for part in html.split("<select") if 'id="artifact-page-size"' in part).split("</select>")[0]

    assert 'x-model.number="pageSize"' in select
