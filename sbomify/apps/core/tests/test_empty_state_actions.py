"""Empty-state actions respect write access and never appear on public artifact lists."""

import pytest
from django.template.loader import render_to_string
from django.urls import reverse


@pytest.mark.parametrize("kind", ["products", "components", "releases"])
@pytest.mark.parametrize("can_manage", [False, True])
def test_inventory_creation_requires_manage_access(kind: str, can_manage: bool) -> None:
    html = render_to_string(
        "components/inventory/results.html",
        {
            "inventory": {"kind": kind, "singular": kind[:-1], "rows": [], "total": 0},
            "can_manage": can_manage,
            "preview": True,
        },
    )
    assert (f'href="{reverse(f"core:{kind[:-1]}_new")}"' in html) is can_manage


@pytest.mark.parametrize("kind", ["sboms", "documents"])
@pytest.mark.parametrize("has_crud_permissions", [False, True])
@pytest.mark.parametrize("is_public_view", [False, True])
def test_empty_upload_requires_private_write_access(
    kind: str, has_crud_permissions: bool, is_public_view: bool
) -> None:
    html = render_to_string(
        f"{kind}/{kind}_table_content.html.j2",
        {
            kind: [],
            "component_id": "empty1234567",
            "has_crud_permissions": has_crud_permissions,
            "is_public_view": is_public_view,
        },
    )
    assert ("#upload-artifact" in html) is (has_crud_permissions and not is_public_view)


@pytest.mark.parametrize("can_manage", [False, True])
def test_empty_scoped_release_preserves_product(can_manage: bool) -> None:
    html = render_to_string(
        "components/inventory/results.html",
        {
            "inventory": {
                "kind": "releases",
                "singular": "release",
                "rows": [],
                "total": 0,
                "scope_product": "product12345",
            },
            "can_manage": can_manage,
            "preview": True,
        },
    )
    destination = reverse("core:release_new") + "?product=product12345"
    assert (f'href="{destination}"' in html) is can_manage


@pytest.mark.parametrize("has_crud_permissions", [False, True])
def test_empty_vex_upload_requires_write_access(has_crud_permissions: bool) -> None:
    html = render_to_string(
        "sboms/vex_documents.html.j2",
        {
            "vex_documents": [],
            "component_id": "empty1234567",
            "has_crud_permissions": has_crud_permissions,
        },
    )
    assert ("#upload-artifact" in html) is has_crud_permissions
