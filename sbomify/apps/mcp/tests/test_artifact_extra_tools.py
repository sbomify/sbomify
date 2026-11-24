"""Documents, crypto inventory, assessment re-runs, plugins and licensing over MCP."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core import object_store
from sbomify.apps.core.authz import SCOPE_PRESETS

from .test_protocol import call, mcp_http, parse, structured
from .test_write_tools import call_tool

SHA = "a" * 64


def _refusal(response) -> str:
    payload = parse(response)
    assert payload["result"].get("isError") is True, payload
    return json.dumps(payload)


def _document_component(team):
    from sbomify.apps.core.models import Component

    return Component.objects.create(name="Docs", team=team, component_type=Component.ComponentType.DOCUMENT)


def _sbom(component, **fields):
    from sbomify.apps.sboms.models import SBOM

    return SBOM.objects.create(
        name="widget",
        version="1.0",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="stored.json",
        sha256_hash=SHA,
        **fields,
    )


def _document(component, name="Policy"):
    from sbomify.apps.documents.models import Document

    return Document.objects.create(name=name, version="1.0", component=component, document_filename="doc.bin")


@pytest.fixture
def stored(monkeypatch):
    """Record object store writes instead of making them."""
    writes: dict[str, bytes] = {}

    def keep(name):
        def store(self, *args):
            writes[name] = args[-1]
            return f"{name}-key"

        return store

    for method in ("upload_document", "upload_sbom_signature", "upload_sbom_provenance"):
        monkeypatch.setattr(object_store.StorageClient, method, keep(method))
    return writes


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_create_document_stores_the_decoded_file(mcp_owner, make_token, stored):
    from sbomify.apps.documents.models import Document

    _, bound, _ = mcp_owner
    component = await sync_to_async(_document_component)(bound)
    token = await sync_to_async(make_token)(["artifact:publish"])
    content = b"%PDF-1.7 security policy"

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "create_document",
            {
                "component_id": component.id,
                "name": "Security policy",
                "version": "2.0",
                "document_type": "compliance",
                "content_type": "application/pdf",
                "content_base64": base64.b64encode(content).decode(),
            },
        )

    created = structured(response)
    document = await sync_to_async(Document.objects.get)(pk=created["id"])
    assert stored["upload_document"] == content
    assert document.sha256_hash == hashlib.sha256(content).hexdigest()
    assert (document.name, document.version, document.content_type) == ("Security policy", "2.0", "application/pdf")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_create_document_refuses_another_workspaces_component(mcp_owner, make_token, stored):
    _, _, other = mcp_owner
    component = await sync_to_async(_document_component)(other)
    token = await sync_to_async(make_token)(["artifact:publish"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "create_document",
            {"component_id": component.id, "name": "x", "content_base64": base64.b64encode(b"x").decode()},
        )

    assert "No component found" in _refusal(response)
    assert stored == {}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_create_document_names_the_valid_types(mcp_owner, make_token, stored):
    _, bound, _ = mcp_owner
    component = await sync_to_async(_document_component)(bound)
    token = await sync_to_async(make_token)(["artifact:publish"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "create_document",
            {
                "component_id": component.id,
                "name": "x",
                "document_type": "poem",
                "content_base64": base64.b64encode(b"x").decode(),
            },
        )

    assert "release-notes" in _refusal(response)
    assert stored == {}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_document_renames_it(mcp_owner, make_token):
    from sbomify.apps.documents.models import Document

    _, bound, _ = mcp_owner
    document = await sync_to_async(_document)(await sync_to_async(_document_component)(bound))
    token = await sync_to_async(make_token)(["document:manage"])

    async with mcp_http() as client:
        response = await call_tool(
            client, token, "update_document", {"document_id": document.id, "name": "Renamed", "version": "3.0"}
        )

    assert structured(response)["name"] == "Renamed"
    refreshed = await sync_to_async(Document.objects.get)(pk=document.id)
    assert (refreshed.name, refreshed.version) == ("Renamed", "3.0")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_document_refuses_another_workspaces_document(mcp_owner, make_token):
    _, _, other = mcp_owner
    document = await sync_to_async(_document)(await sync_to_async(_document_component)(other))
    token = await sync_to_async(make_token)(["document:manage"])

    async with mcp_http() as client:
        response = await call_tool(client, token, "update_document", {"document_id": document.id, "name": "Mine"})

    assert "No Document found" in _refusal(response)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "tool, arguments",
    [
        ("rerun_assessment", {"plugin_name": "anything"}),
    ],
)
async def test_artifact_writes_refuse_another_workspaces_artifact(
    make_token, component_in_other_workspace, stored, tool, arguments
):
    sbom = await sync_to_async(_sbom)(component_in_other_workspace)
    token = await sync_to_async(make_token)(None)

    async with mcp_http() as client:
        response = await call_tool(client, token, tool, {"artifact_id": sbom.id, **arguments})

    assert "No Artifact found" in _refusal(response)
    assert stored == {}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_crypto_inventory_pages_the_assets(make_token, component_in_bound_workspace, monkeypatch):
    sbom = await sync_to_async(_sbom)(component_in_bound_workspace)
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {
                "type": "cryptographic-asset",
                "name": name,
                "bom-ref": name,
                "cryptoProperties": {"assetType": "algorithm", "algorithmProperties": {"primitive": "ae"}},
            }
            for name in ("AES-128-GCM", "AES-256-GCM", "ChaCha20")
        ],
    }
    fetches: list[str] = []

    def fetch(self, name):
        fetches.append(name)
        return json.dumps(document).encode()

    monkeypatch.setattr(object_store.StorageClient, "get_sbom_size", lambda self, name: 1024)
    monkeypatch.setattr(object_store.StorageClient, "get_sbom_data", fetch)
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        response = await call_tool(
            client, token, "get_crypto_inventory", {"artifact_id": sbom.id, "asset_type": "algorithm", "page_size": 2}
        )
        second_page = await call_tool(
            client,
            token,
            "get_crypto_inventory",
            {"artifact_id": sbom.id, "asset_type": "algorithm", "page_size": 2, "page": 2},
        )

    inventory = structured(response)
    assert [asset["name"] for asset in structured(second_page)["assets"]["items"]] == ["ChaCha20"]
    # Fetched once, through the bounded loader; the second page is served from the inventory cache.
    assert len(fetches) == 1
    assert inventory["count"] == 3
    assert inventory["assets"]["total"] == 3
    assert inventory["assets"]["has_more"] is True
    assert [asset["name"] for asset in inventory["assets"]["items"]] == ["AES-128-GCM", "AES-256-GCM"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_crypto_inventory_refuses_an_artifact_too_large_to_parse(
    make_token, component_in_bound_workspace, monkeypatch
):
    from sbomify.apps.mcp.limits import MAX_ARTIFACT_PARSE_BYTES

    sbom = await sync_to_async(_sbom)(component_in_bound_workspace)
    monkeypatch.setattr(object_store.StorageClient, "get_sbom_size", lambda self, name: MAX_ARTIFACT_PARSE_BYTES + 1)

    def never(self, name):
        raise AssertionError("an oversized artifact must not be fetched")

    monkeypatch.setattr(object_store.StorageClient, "get_sbom_data", never)
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        response = await call_tool(client, token, "get_crypto_inventory", {"artifact_id": sbom.id})

    assert "limit for inspection over MCP" in _refusal(response)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_crypto_inventory_refuses_a_document_too_costly_to_parse(
    make_token, component_in_bound_workspace, monkeypatch
):
    """Under the byte ceiling is not enough: a document of tiny parts can still take too much memory parsed."""
    from sbomify.apps.mcp import limits

    sbom = await sync_to_async(_sbom)(component_in_bound_workspace)
    monkeypatch.setattr(object_store.StorageClient, "get_sbom_size", lambda self, name: 1024)
    monkeypatch.setattr(object_store.StorageClient, "get_sbom_data", lambda self, name: b"[" + b"0," * 400 + b"0]")
    monkeypatch.setattr(limits, "within_parse_budget", lambda raw, ceiling: False)
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        response = await call_tool(client, token, "get_crypto_inventory", {"artifact_id": sbom.id})

    assert "too many small parts" in _refusal(response)


def _plugins(team, *names, enabled=("extra-check",)):
    from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings

    for name in names:
        RegisteredPlugin.objects.create(
            name=name,
            display_name=name,
            category="compliance",
            version="1.0.0",
            plugin_class_path="sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
            is_enabled=True,
        )
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": list(enabled)})


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_rerun_assessment_queues_a_run(mcp_owner, make_token, component_in_bound_workspace, monkeypatch):
    from sbomify.apps.plugins import apis

    _, bound, _ = mcp_owner
    sbom = await sync_to_async(_sbom)(component_in_bound_workspace)
    await sync_to_async(_plugins)(bound, "extra-check")
    sent: list[dict] = []
    monkeypatch.setattr(apis.run_assessment_task, "send", lambda **kwargs: sent.append(kwargs))
    token = await sync_to_async(make_token)(["component:manage"])

    async with mcp_http() as client:
        response = await call_tool(
            client, token, "rerun_assessment", {"artifact_id": sbom.id, "plugin_name": "extra-check"}
        )

    assert structured(response)["status"] == "queued"
    assert [(run["sbom_id"], run["plugin_name"]) for run in sent] == [(sbom.id, "extra-check")]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_plugins_says_which_the_workspace_runs(mcp_owner, make_token):
    _, bound, _ = mcp_owner
    await sync_to_async(_plugins)(bound, "extra-check", "other-check")
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        response = await call_tool(client, token, "list_plugins", {})

    enabled = {plugin["name"]: plugin["enabled"] for plugin in structured(response)["plugins"]["items"]}
    assert (enabled["extra-check"], enabled["other-check"]) == (True, False)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_search_and_validate_licenses(make_token):
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        found = await call_tool(client, token, "search_licenses", {"search": "apache-2"})
        valid = await call_tool(client, token, "validate_license_expression", {"expression": "MIT OR Apache-2.0"})
        invalid = await call_tool(client, token, "validate_license_expression", {"expression": "MIT OR ("})

    assert "Apache-2.0" in [entry["key"] for entry in structured(found)["items"]]
    assert structured(valid)["status"] == 200
    assert structured(invalid)["status"] == 400


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_guest_is_refused_the_license_tools(mcp_owner, make_token):
    """The license list is reference data, but a guest is refused every tool, these included."""
    from sbomify.apps.teams.models import Member

    user, bound, _ = mcp_owner
    await sync_to_async(Member.objects.filter(user=user, team=bound).update)(role="guest")
    token = await sync_to_async(make_token)(None)

    async with mcp_http() as client:
        found = await call_tool(client, token, "search_licenses", {"search": "MIT"})
        valid = await call_tool(client, token, "validate_license_expression", {"expression": "MIT"})

    for response in (found, valid):
        payload = parse(response)
        assert payload["result"].get("isError") is True, payload
        assert "Guest members" in json.dumps(payload)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_artifact_and_get_document_name_their_releases(
    mcp_owner, make_token, product_in_bound_workspace, component_in_bound_workspace
):
    from sbomify.apps.core.models import Release, ReleaseArtifact

    _, bound, _ = mcp_owner
    sbom = await sync_to_async(_sbom)(component_in_bound_workspace)
    document = await sync_to_async(_document)(await sync_to_async(_document_component)(bound))
    release = await sync_to_async(Release.objects.create)(product=product_in_bound_workspace, name="v1.0")
    await sync_to_async(ReleaseArtifact.objects.create)(release=release, sbom=sbom)
    await sync_to_async(ReleaseArtifact.objects.create)(release=release, document=document)
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        artifact = await call_tool(client, token, "get_artifact", {"artifact_id": sbom.id})
        doc = await call_tool(client, token, "get_document", {"document_id": document.id})

    assert [r["name"] for r in structured(artifact)["releases"]["items"]] == ["v1.0"]
    assert [r["name"] for r in structured(doc)["releases"]["items"]] == ["v1.0"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_new_tools_follow_the_token_scopes(make_token):
    read_only = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])
    sbom_read = await sync_to_async(make_token)(["sbom:read"])

    async with mcp_http() as client:
        read_only_tools = {
            t["name"] for t in parse(await call(client, "tools/list", token=read_only.encoded_token))["result"]["tools"]
        }
        sbom_read_tools = {
            t["name"] for t in parse(await call(client, "tools/list", token=sbom_read.encoded_token))["result"]["tools"]
        }

    writes = {
        "create_document",
        "update_document",
        "rerun_assessment",
    }
    assert read_only_tools & writes == set()
    # Signatures and provenance are one-shot, publicly served attestations, uploaded by CI rather than an agent.
    from sbomify.apps.mcp import registry

    assert {"upload_artifact_signature", "upload_artifact_provenance"} & set(registry.all_specs()) == set()
    assert {"get_crypto_inventory", "list_plugins", "search_licenses", "validate_license_expression"} <= read_only_tools
    # The inventory service also checks component:access, which sbom:read alone does not grant.
    assert "get_crypto_inventory" not in sbom_read_tools
    assert "get_artifact" in sbom_read_tools
