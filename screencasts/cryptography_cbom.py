"""Record the cryptography (CBOM) screencast.

Drives: Dashboard → sidebar Cryptography (workspace quantum readiness: verdict
cards, "Migrate first", one row per component) → a component's CBOM →
its Cryptographic Assets card (asset grading and drill-down, Certificates and
Protocols tabs).

Seeding: one CycloneDX 1.6 CBOM per component, stored in a dict-backed S3
(the screencast stack has no bucket), and graded by running the real PQC
readiness plugin over each file, so every verdict on screen is the plugin's.
The Web Dashboard keeps only its ordinary SBOM, stamped crypto-free, so the
page also shows the "No crypto" case.
"""

import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    narrate,
    pace,
    settle,
    sidebar_link,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM

WORKSPACE_NAME = "Pied Piper"
CORE_COMPONENT = "Compression Core Library"

NOW = datetime.now(tz=timezone.utc)


def _algorithm(name: str, primitive: str, nist_level: int, **extra: Any) -> dict[str, Any]:
    props: dict[str, Any] = {"primitive": primitive, "nistQuantumSecurityLevel": nist_level, **extra}
    return {
        "type": "cryptographic-asset",
        "name": name,
        "bom-ref": f"crypto-{name.lower()}",
        "cryptoProperties": {"assetType": "algorithm", "algorithmProperties": props},
    }


def _certificate(subject: str, issuer: str, days_left: int) -> dict[str, Any]:
    return {
        "type": "cryptographic-asset",
        "name": subject.removeprefix("CN="),
        "bom-ref": f"cert-{subject.removeprefix('CN=')}",
        "cryptoProperties": {
            "assetType": "certificate",
            "certificateProperties": {
                "subjectName": subject,
                "issuerName": issuer,
                "notValidBefore": (NOW - timedelta(days=365 - days_left)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "notValidAfter": (NOW + timedelta(days=days_left)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "certificateFormat": "X.509",
            },
        },
    }


def _tls(version: str, suites: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "type": "cryptographic-asset",
        "name": f"TLS {version}",
        "bom-ref": f"proto-tls-{version}",
        "cryptoProperties": {
            "assetType": "protocol",
            "protocolProperties": {
                "type": "tls",
                "version": version,
                "cipherSuites": [{"name": name, "identifiers": [ident]} for name, ident in suites],
            },
        },
    }


# Per component: the crypto its CBOM declares.
CBOM_ASSETS: dict[str, list[dict[str, Any]]] = {
    CORE_COMPONENT: [
        _algorithm("RSA-2048", "pke", 0, parameterSetIdentifier="2048", classicalSecurityLevel=112),
        _algorithm("ECDSA-P256", "signature", 0, curve="secp256r1"),
        _algorithm("AES-256-GCM", "ae", 5, parameterSetIdentifier="256", mode="gcm"),
        _algorithm("SHA-256", "hash", 2),
        _algorithm("ML-KEM-768", "kem", 3, parameterSetIdentifier="768"),
        _certificate("CN=sync.piedpiper.example.com", "CN=Pied Piper Issuing CA", 42),
        _tls(
            "1.2",
            [
                ("TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384", "0xC0,0x30"),
                ("TLS_RSA_WITH_3DES_EDE_CBC_SHA", "0x00,0x0A"),
            ],
        ),
    ],
    "REST API Service": [
        _algorithm("RSA-3072", "signature", 0, parameterSetIdentifier="3072", classicalSecurityLevel=128),
        _algorithm("ECDH-P384", "kem", 0, curve="secp384r1"),
        _algorithm("AES-128-GCM", "ae", 1, parameterSetIdentifier="128", mode="gcm"),
        _algorithm("HMAC-SHA256", "mac", 2),
        _certificate("CN=api.piedpiper.example.com", "CN=Pied Piper Issuing CA", 210),
        _tls("1.3", [("TLS_AES_256_GCM_SHA384", "0x13,0x02"), ("TLS_CHACHA20_POLY1305_SHA256", "0x13,0x03")]),
    ],
    "Data Pipeline Worker": [
        _algorithm("ML-DSA-65", "signature", 3, parameterSetIdentifier="65"),
        _algorithm("ML-KEM-1024", "kem", 5, parameterSetIdentifier="1024"),
        _algorithm("AES-256-GCM", "ae", 5, parameterSetIdentifier="256", mode="gcm"),
        _algorithm("SHA-384", "hash", 4),
    ],
}


def _cbom(component_name: str, version: str) -> dict[str, Any]:
    slug = component_name.lower().replace(" ", "-")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, slug)}",
        "version": 1,
        "metadata": {
            "timestamp": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": {"type": "application", "name": f"com.piedpiper/{slug}", "version": version},
        },
        "components": CBOM_ASSETS[component_name],
    }


@pytest.fixture
def fake_s3(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], bytes]:
    """Back S3 with a dict: the inventory card reads each CBOM back."""
    store: dict[tuple[str, str], bytes] = {}

    def _put(self: StorageClient, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: StorageClient, bucket_name: str, object_name: str) -> bytes | None:
        return store.get((bucket_name, object_name))

    monkeypatch.setattr(StorageClient, "upload_data_as_file", _put)
    monkeypatch.setattr(StorageClient, "get_file_data", _get)
    return store


@pytest.fixture
def crypto_workspace(sample_user: AbstractBaseUser, pied_piper_with_sboms: dict, fake_s3: dict) -> dict:
    """A CBOM per component, graded by the real PQC readiness plugin."""
    from sbomify.apps.plugins.builtins.pqc import PqcReadinessPlugin
    from sbomify.apps.plugins.sdk.base import SBOMContext

    team = pied_piper_with_sboms["product"].team
    team.name = WORKSPACE_NAME
    team.save(update_fields=["name"])
    sample_user.first_name = "Richard"
    sample_user.last_name = "Hendricks"
    sample_user.save(update_fields=["first_name", "last_name"])

    # The ordinary SBOMs carry no crypto; the CBOMs below do.
    SBOM.objects.filter(pk__in=[s.pk for s in pied_piper_with_sboms["sboms"].values()]).update(has_crypto_assets=False)

    plugin = PqcReadinessPlugin()
    cboms = {}
    for name, component in pied_piper_with_sboms["components"].items():
        if name not in CBOM_ASSETS:
            continue
        payload = json.dumps(_cbom(name, "2.4.0"), indent=2).encode()
        filename = StorageClient("SBOMS").upload_sbom(payload)
        slug = name.lower().replace(" ", "-")
        cbom = SBOM.objects.create(
            name=f"com.piedpiper/{slug}",
            version="2.4.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename=filename,
            source="api",
            bom_type=SBOM.BomType.CBOM,
            has_crypto_assets=True,
            component=component,
        )
        cboms[name] = cbom

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cbom.json"
            path.write_bytes(payload)
            result = plugin.assess(str(cbom.id), path, context=SBOMContext(bom_type="cbom"))
        AssessmentRun.objects.create(
            id=uuid.uuid4(),
            sbom=cbom,
            plugin_name="pqc-readiness",
            plugin_version=plugin.VERSION,
            plugin_config_hash="0" * 64,
            category="compliance",
            run_reason="on_upload",
            status="completed",
            started_at=NOW,
            completed_at=NOW,
            input_content_digest="0" * 64,
            result=result.to_dict(),
            result_schema_version="1.0",
        )

    return {**pied_piper_with_sboms, "cboms": cboms}


@pytest.mark.django_db(transaction=True)
def cryptography_cbom(crypto_workspace: dict, recording_page: Page) -> None:
    page = recording_page

    start_on_dashboard(page, 800)
    narrate(page, "intro")
    settle(page)

    hover_and_click(page, sidebar_link(page, "Cryptography"))
    page.wait_for_load_state("networkidle")
    page.get_by_text("Migrate first").wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    narrate(page, "cryptography_page_grades")
    settle(page)
    narrate(page, "glance_which_components")
    settle(page)

    migrate = page.get_by_text("Migrate first")
    smooth_scroll(page, migrate, 400)
    narrate(page, "migrate_first_lists")
    settle(page)

    table = page.locator("table").last
    smooth_scroll(page, table, 400)
    narrate(page, "each_component_shows")
    settle(page)

    hover_and_click(page, page.get_by_role("link", name=CORE_COMPONENT))
    page.wait_for_load_state("networkidle")
    card = page.locator("#crypto-inventory-card")
    card.wait_for(state="visible", timeout=20_000)
    smooth_scroll(page, card, 800)
    narrate(page, "open_component_see")
    settle(page)

    first_row = card.get_by_role("button", name="Show details for RSA-2048")
    hover_and_click(page, first_row)
    pace(page, 800)
    narrate(page, "expand_asset_see")
    settle(page)
    hover_and_click(page, first_row)
    pace(page, 400)

    certs_tab = card.get_by_role("tab", name="Certificates")
    hover_and_click(page, certs_tab)
    pace(page, 800)
    narrate(page, "certificates_shows_each")
    settle(page)

    protocols_tab = card.get_by_role("tab", name="Protocols")
    hover_and_click(page, protocols_tab)
    pace(page, 800)
    narrate(page, "protocols_lists_cipher")
    settle(page)
    pace(page, 600)
