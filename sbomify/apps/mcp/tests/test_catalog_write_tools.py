"""The product, component and release editing tools, called for real.

Each happy path uses a token scoped to exactly the tool's declared actions, so a
declaration that falls short of what the delegated view checks fails here.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async

from .test_protocol import call, mcp_http, parse, structured
from .test_write_tools import call_tool

WRITE_TOOLS = (
    "create_product",
    "update_product",
    "add_component_to_product",
    "add_product_identifier",
    "update_product_identifier",
    "add_product_link",
    "update_product_link",
    "create_component",
    "update_component",
    "update_component_metadata",
    "update_release",
    "link_release",
)


def refusal(response) -> str:
    payload = parse(response)
    assert payload["result"].get("isError") is True, payload
    return json.dumps(payload)


@pytest.fixture
def business_workspace(mcp_owner, ensure_billing_plans):
    """The bound workspace on an active Business plan: creating products and components counts against a plan."""
    _, bound, _ = mcp_owner
    bound.billing_plan = "business"
    bound.billing_plan_limits = {"max_products": 10, "max_components": 100, "subscription_status": "active"}
    bound.save()
    return bound


@pytest.fixture
def release_in_bound_workspace(product_in_bound_workspace):
    from sbomify.apps.core.models import Release

    return Release.objects.create(product=product_in_bound_workspace, name="v1.0", version="1.0")


@pytest.fixture
def release_in_other_workspace(product_in_other_workspace):
    from sbomify.apps.core.models import Release

    return Release.objects.create(product=product_in_other_workspace, name="v9.0", version="9.0")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_create_and_update_a_product(business_workspace, make_token):
    from sbomify.apps.core.models import Product

    bound = business_workspace
    token = await sync_to_async(make_token)(["product:create", "product:manage"])

    async with mcp_http() as client:
        created = structured(await call_tool(client, token, "create_product", {"name": "Router"}))
        updated = structured(
            await call_tool(
                client,
                token,
                "update_product",
                {"product_id": created["id"], "description": "Edge router", "end_of_life": "2030-01-31"},
            )
        )

    product = await sync_to_async(Product.objects.get)(pk=created["id"])
    assert product.team_id == bound.pk
    assert product.description == "Edge router"
    assert str(product.end_of_life) == "2030-01-31"
    assert updated["name"] == "Router"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_dates_are_cleared_by_name_not_by_null(make_token, component_in_bound_workspace, product_in_bound_workspace, release_in_bound_workspace):
    """A left-out argument and a null look the same to a tool, so a date is emptied by naming it in clear."""
    import datetime

    from sbomify.apps.core.models import Component, Product, Release

    def dated() -> None:
        day = datetime.date(2030, 1, 31)
        Product.objects.filter(pk=product_in_bound_workspace.pk).update(end_of_life=day, end_of_support=day)
        Component.objects.filter(pk=component_in_bound_workspace.pk).update(end_of_support=day)
        Release.objects.filter(pk=release_in_bound_workspace.pk).update(
            released_at=datetime.datetime(2030, 1, 31, tzinfo=datetime.UTC)
        )

    await sync_to_async(dated)()
    token = await sync_to_async(make_token)(["product:manage", "component:manage", "release:manage"])
    product_id = product_in_bound_workspace.id

    async with mcp_http() as client:
        await call_tool(client, token, "update_product", {"product_id": product_id, "clear": ["end_of_life"]})
        await call_tool(
            client,
            token,
            "update_component_metadata",
            {"component_id": component_in_bound_workspace.id, "clear": ["end_of_support"]},
        )
        await call_tool(
            client, token, "update_release", {"release_id": release_in_bound_workspace.id, "clear": ["released_at"]}
        )
        unknown = await call_tool(client, token, "update_product", {"product_id": product_id, "clear": ["name"]})
        both = await call_tool(
            client,
            token,
            "update_product",
            {"product_id": product_id, "end_of_life": "2031-01-01", "clear": ["end_of_life"]},
        )

    product = await sync_to_async(Product.objects.get)(pk=product_id)
    assert product.end_of_life is None
    assert str(product.end_of_support) == "2030-01-31"
    component = await sync_to_async(Component.objects.get)(pk=component_in_bound_workspace.pk)
    assert component.end_of_support is None
    release = await sync_to_async(Release.objects.get)(pk=release_in_bound_workspace.pk)
    assert release.released_at is None
    assert "cannot be cleared" in refusal(unknown)
    assert "both set and cleared" in refusal(both)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_adding_a_component_keeps_the_products_others(
    mcp_owner, make_token, product_in_bound_workspace, component_in_bound_workspace
):
    from sbomify.apps.core.models import Component

    _, bound, _ = mcp_owner
    second = await sync_to_async(Component.objects.create)(name="Second Component", team=bound)
    await sync_to_async(product_in_bound_workspace.components.add)(component_in_bound_workspace)
    token = await sync_to_async(make_token)(["product:manage", "component:manage"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "add_component_to_product",
            {"product_id": product_in_bound_workspace.id, "component_id": second.id},
        )

    assert structured(response)["added"] is True
    ids = await sync_to_async(lambda: set(product_in_bound_workspace.components.values_list("id", flat=True)))()
    assert ids == {component_in_bound_workspace.id, second.id}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_adding_a_component_already_there_still_checks_the_role(
    mcp_owner, product_in_bound_workspace, component_in_bound_workspace, django_user_model
):
    """A component already in the product never reaches the view, so the tool checks the role itself."""
    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.access_tokens.utils import create_personal_access_token
    from sbomify.apps.teams.models import Member

    _, bound, _ = mcp_owner

    def operator_token() -> AccessToken:
        user = django_user_model.objects.create_user(username="mcpoperator", email="op@example.com", password="pw")
        Member.objects.create(user=user, team=bound, role="operator", is_default_team=True)
        product_in_bound_workspace.components.add(component_in_bound_workspace)
        return AccessToken.objects.create(
            user=user,
            encoded_token=create_personal_access_token(user),
            team=bound,
            scopes=["product:manage", "component:manage"],
            description="operator",
        )

    token = await sync_to_async(operator_token)()

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "add_component_to_product",
            {"product_id": product_in_bound_workspace.id, "component_id": component_in_bound_workspace.id},
        )

    assert "Not permitted" in refusal(response)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_component_metadata_returns_every_author_and_license(make_token, component_in_bound_workspace):
    """The update replaces these lists, so the read must not cut them."""

    def many() -> None:
        for n in range(60):
            component_in_bound_workspace.authors.create(name=f"Author {n}", order=n)
            component_in_bound_workspace.licenses.create(license_type="spdx", license_id=f"LicenseRef-{n}", order=n)

    await sync_to_async(many)()
    token = await sync_to_async(make_token)(["component:read_internal"])

    async with mcp_http() as client:
        metadata = structured(
            await call_tool(client, token, "get_component_metadata", {"component_id": component_in_bound_workspace.id})
        )

    assert len(metadata["authors"]) == 60
    assert len(metadata["licenses"]) == 60


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_identifiers_and_links_are_added_and_partly_updated(
    business_workspace, make_token, product_in_bound_workspace
):
    from sbomify.apps.sboms.models import ProductIdentifier, ProductLink

    token = await sync_to_async(make_token)(["product:manage"])
    product_id = product_in_bound_workspace.id

    async with mcp_http() as client:
        identifier = structured(
            await call_tool(
                client,
                token,
                "add_product_identifier",
                {"product_id": product_id, "identifier_type": "sku", "value": "RTR-1"},
            )
        )
        await call_tool(
            client,
            token,
            "update_product_identifier",
            {"product_id": product_id, "identifier_id": identifier["id"], "value": "RTR-2"},
        )
        link = structured(
            await call_tool(
                client,
                token,
                "add_product_link",
                {
                    "product_id": product_id,
                    "link_type": "security",
                    "title": "Security",
                    "url": "https://example.com/security",
                    "description": "How to report a vulnerability",
                },
            )
        )
        await call_tool(
            client,
            token,
            "update_product_link",
            {"product_id": product_id, "link_id": link["id"], "url": "https://example.com/psirt"},
        )

    stored_identifier = await sync_to_async(ProductIdentifier.objects.get)(pk=identifier["id"])
    assert (stored_identifier.identifier_type, stored_identifier.value) == ("sku", "RTR-2")
    stored_link = await sync_to_async(ProductLink.objects.get)(pk=link["id"])
    assert stored_link.url == "https://example.com/psirt"
    # Left out of the update, so kept rather than blanked by the view's full replace.
    assert stored_link.description == "How to report a vulnerability"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_create_and_update_a_component(business_workspace, make_token):
    from sbomify.apps.core.models import Component

    bound = business_workspace
    token = await sync_to_async(make_token)(["component:create", "component:manage"])

    async with mcp_http() as client:
        created = structured(await call_tool(client, token, "create_component", {"name": "Firmware"}))
        await call_tool(client, token, "update_component", {"component_id": created["id"], "name": "Firmware Core"})

    component = await sync_to_async(Component.objects.get)(pk=created["id"])
    assert component.team_id == bound.pk
    assert component.name == "Firmware Core"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_component_metadata_round_trip(make_token, component_in_bound_workspace):
    token = await sync_to_async(make_token)(["component:manage", "component:read_internal"])
    component_id = component_in_bound_workspace.id

    async with mcp_http() as client:
        await call_tool(
            client,
            token,
            "update_component_metadata",
            {
                "component_id": component_id,
                "supplier_name": "Example Ltd",
                "supplier_urls": ["https://example.com"],
                "supplier_contacts": [{"name": "Grace", "email": "grace@example.com", "bom_ref": "contact-grace"}],
                "authors": [{"name": "Ada", "email": "ada@example.com", "bom_ref": "author-ada"}],
                "licenses": ["Apache-2.0 OR MIT", {"name": "Example EULA", "url": "https://example.com/eula"}],
                "lifecycle_phase": "build",
            },
        )
        # A later supplier change that names only the address keeps the name, URLs and contacts.
        await call_tool(
            client, token, "update_component_metadata", {"component_id": component_id, "supplier_address": "1 Main St"}
        )
        metadata = structured(await call_tool(client, token, "get_component_metadata", {"component_id": component_id}))
        # Sent back as read, then with the contacts emptied: the empty list clears them.
        await call_tool(
            client,
            token,
            "update_component_metadata",
            {"component_id": component_id, "licenses": metadata["licenses"], "supplier_contacts": []},
        )
        cleared = structured(await call_tool(client, token, "get_component_metadata", {"component_id": component_id}))
        bad_phase = await call_tool(
            client, token, "update_component_metadata", {"component_id": component_id, "lifecycle_phase": "shipping"}
        )

    assert metadata["supplier"]["name"] == "Example Ltd"
    assert metadata["supplier"]["url"] == ["https://example.com"]
    assert metadata["supplier"]["address"] == "1 Main St"
    assert metadata["supplier"]["contacts"] == [
        {"name": "Grace", "email": "grace@example.com", "bom_ref": "contact-grace"}
    ]
    assert metadata["authors"] == [{"name": "Ada", "email": "ada@example.com", "bom_ref": "author-ada"}]
    assert metadata["licenses"] == [
        "Apache-2.0 OR MIT",
        {"name": "Example EULA", "url": "https://example.com/eula", "text": None},
    ]
    assert cleared["licenses"] == metadata["licenses"]
    assert not cleared["supplier"].get("contacts")
    assert metadata["lifecycle_phase"] == "build"
    assert "Unknown lifecycle_phase" in refusal(bad_phase)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_release_and_refuse_the_latest_one(
    make_token, product_in_bound_workspace, release_in_bound_workspace
):
    from sbomify.apps.core.models import Release

    latest = await sync_to_async(Release.objects.create)(
        product=product_in_bound_workspace, name="latest", is_latest=True
    )
    token = await sync_to_async(make_token)(["release:manage"])

    async with mcp_http() as client:
        updated = structured(
            await call_tool(
                client,
                token,
                "update_release",
                {"release_id": release_in_bound_workspace.id, "version": "1.0.1", "is_prerelease": True},
            )
        )
        refused = await call_tool(client, token, "update_release", {"release_id": latest.id, "name": "renamed"})

    assert updated["version"] == "1.0.1"
    assert updated["is_prerelease"] is True
    assert "automatically managed" in refusal(refused)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_link_a_release_and_read_it_back(mcp_owner, make_token, release_in_bound_workspace):
    from sbomify.apps.core.models import Product, Release

    _, bound, _ = mcp_owner
    library = await sync_to_async(Product.objects.create)(name="Library", team=bound)
    bundled = await sync_to_async(Release.objects.create)(product=library, name="v2.1", version="2.1")
    token = await sync_to_async(make_token)(["release:tag", "release:read"])

    async with mcp_http() as client:
        linked = structured(
            await call_tool(
                client,
                token,
                "link_release",
                {
                    "release_id": release_in_bound_workspace.id,
                    "linked_product_id": library.id,
                    "linked_version": "2.1",
                },
            )
        )
        release = structured(
            await call_tool(client, token, "get_release", {"release_id": release_in_bound_workspace.id})
        )

    assert linked["id"] == bundled.id
    assert [row["id"] for row in release["linked_releases"]["items"]] == [bundled.id]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("update_product", lambda ids: {"product_id": ids["other_product"], "name": "x"}),
        (
            "add_component_to_product",
            lambda ids: {"product_id": ids["product"], "component_id": ids["other_component"]},
        ),
        (
            "add_product_identifier",
            lambda ids: {"product_id": ids["other_product"], "identifier_type": "sku", "value": "X"},
        ),
        (
            "update_product_identifier",
            lambda ids: {"product_id": ids["other_product"], "identifier_id": "1", "value": "X"},
        ),
        (
            "add_product_link",
            lambda ids: {
                "product_id": ids["other_product"],
                "link_type": "website",
                "title": "t",
                "url": "https://example.com",
            },
        ),
        ("update_product_link", lambda ids: {"product_id": ids["other_product"], "link_id": "1", "title": "t"}),
        ("update_component", lambda ids: {"component_id": ids["other_component"], "name": "x"}),
        ("update_component_metadata", lambda ids: {"component_id": ids["other_component"], "lifecycle_phase": "build"}),
        ("get_component_metadata", lambda ids: {"component_id": ids["other_component"]}),
        ("update_release", lambda ids: {"release_id": ids["other_release"], "name": "x"}),
        ("link_release", lambda ids: {"release_id": ids["release"], "linked_release_id": ids["other_release"]}),
    ],
)
async def test_another_workspaces_ids_are_not_found(
    make_token,
    product_in_bound_workspace,
    product_in_other_workspace,
    component_in_other_workspace,
    release_in_bound_workspace,
    release_in_other_workspace,
    tool,
    arguments,
):
    """The user owns both workspaces, so only the token's pinning stands between them."""
    ids = {
        "product": product_in_bound_workspace.id,
        "other_product": product_in_other_workspace.id,
        "other_component": component_in_other_workspace.id,
        "release": release_in_bound_workspace.id,
        "other_release": release_in_other_workspace.id,
    }
    token = await sync_to_async(make_token)(None)

    async with mcp_http() as client:
        response = await call_tool(client, token, tool, arguments(ids))

    assert "found with id" in refusal(response)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_read_only_token_is_not_offered_the_editing_tools(make_token):
    token = await sync_to_async(make_token)(["product:read", "component:read_internal", "release:read"])

    async with mcp_http() as client:
        response = await call(client, "tools/list", token=token.encoded_token)

    names = {tool["name"] for tool in parse(response)["result"]["tools"]}
    assert "get_component_metadata" in names
    assert names & set(WRITE_TOOLS) == set()
