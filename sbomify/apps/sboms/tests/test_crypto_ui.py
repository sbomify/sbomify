"""Crypto UX surfaces: interpreted certificate/protocol views, replacement
suggestions, the inventory-card drill-down, and the cipher-suite CSV export."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_mock.plugin import MockerFixture

from ..crypto_inventory import CryptoAsset
from ..models import SBOM
from ..pqc import PqcStatus, replacement_for
from ..services.sboms import _certificate_view, _protocol_view
from .fixtures import sample_component, sample_sbom  # noqa: F401
from .test_views import setup_test_session

_DATA = Path(__file__).parent / "test_data"
_S3_TARGET = "sbomify.apps.sboms.services.sboms.S3Client"


def _algo(name: str, **kw) -> CryptoAsset:
    return CryptoAsset(name=name, bom_ref=None, oid=None, asset_type="algorithm", **kw)


def test_certificate_view_expiry_countdown():
    soon = (timezone.now() + timedelta(days=30)).isoformat()
    view = _certificate_view({"subjectName": "CN=a", "issuerName": "CN=ca", "notValidAfter": soon})
    assert view is not None
    assert view["expiring_soon"] and not view["expired"]
    assert 28 <= view["days_to_expiry"] <= 30

    past = (timezone.now() - timedelta(days=5)).isoformat()
    expired = _certificate_view({"notValidAfter": past})
    assert expired is not None and expired["expired"]


def test_certificate_view_states_tolerate_shapes():
    view = _certificate_view({"certificateState": [{"state": "active"}, "revoked", {"name": "custom"}]})
    assert view is not None
    assert view["states"] == ["active", "revoked", "custom"]


def test_protocol_view_flags_weak_suites_and_versions():
    view = _protocol_view(
        {
            "type": "tls",
            "version": "1.1",
            "cipherSuites": [
                {"name": "TLS_RSA_WITH_3DES_EDE_CBC_SHA", "identifiers": ["0x00,0x0A"]},
                {"name": "TLS_AES_128_GCM_SHA256"},
            ],
        }
    )
    assert view is not None
    assert view["weak_version"] and "RFC 8996" in view["weak_version"]
    by_name = {s["name"]: s for s in view["cipher_suites"]}
    assert by_name["TLS_RSA_WITH_3DES_EDE_CBC_SHA"]["weaknesses"]
    assert by_name["TLS_AES_128_GCM_SHA256"]["weaknesses"] == []


def test_protocol_view_reads_legacy_tls_cipher_suites():
    view = _protocol_view({"type": "tls", "version": "1.2", "tlsCipherSuites": ["TLS_RSA_WITH_RC4_128_MD5"]})
    assert view is not None
    assert view["weak_version"] is None
    assert view["cipher_suites"][0]["weaknesses"]  # RC4 + MD5


def test_replacement_targets_follow_primitive():
    assert "ML-DSA" in (replacement_for(_algo("ECDSA-P256"), PqcStatus.VULNERABLE) or "")
    assert replacement_for(_algo("X25519"), PqcStatus.VULNERABLE) == "ML-KEM (FIPS 203)"
    combined = replacement_for(_algo("RSA-2048"), PqcStatus.VULNERABLE) or ""
    assert "ML-KEM" in combined and "ML-DSA" in combined
    assert replacement_for(_algo("AES-256"), PqcStatus.SAFE) is None


@pytest.mark.django_db
def test_inventory_card_renders_tabs_and_drilldown(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    mocker.patch(_S3_TARGET).return_value.get_sbom_data.return_value = (_DATA / "cbom_sample_1.6.cdx.json").read_bytes()
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_crypto_inventory", kwargs={"sbom_id": sample_sbom.id}))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Cryptographic Assets" in html
    assert "Certificates" in html  # the 1.6 fixture carries a certificate
    assert "Protocols" in html
    assert "Export CSV" in html
    assert "CN=demo.example.com" in html
    assert "Replacement:" in html  # vulnerable assets carry a migration target


@pytest.mark.django_db
def test_cipher_suite_csv_download(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    mocker.patch(_S3_TARGET).return_value.get_sbom_data.return_value = (_DATA / "cbom_sample_1.6.cdx.json").read_bytes()
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    url = reverse("api-1:download_cipher_suite_inventory_csv", kwargs={"sbom_id": sample_sbom.id})
    response = client.get(url)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    body = response.content.decode()
    assert body.splitlines()[0] == "protocol,type,version,cipher_suite,identifiers,weak,weaknesses"
    assert "TLS" in body


@pytest.mark.django_db
def test_workspace_crypto_rollup_aggregates_runs(sample_sbom: SBOM):  # noqa: F811
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk import RunReason
    from ..services.crypto_dashboard import build_workspace_crypto_rollup

    sample_sbom.bom_type = SBOM.BomType.CBOM
    sample_sbom.save(update_fields=["bom_type"])
    AssessmentRun.objects.create(
        sbom=sample_sbom,
        plugin_name="pqc-readiness",
        plugin_version="1.0",
        plugin_config_hash="x",
        category="compliance",
        status="completed",
        run_reason=RunReason.MANUAL.value,
        result={
            "metadata": {
                "pqc_overall": "at_risk",
                "certificates": {"count": 2, "expired": 1, "expiring_soon": 0, "soonest_not_valid_after": None},
            },
            "findings": [
                {"title": "RSA-2048: Quantum-vulnerable", "metadata": {"pqc_status": "quantum_vulnerable", "asset_name": "RSA-2048"}},
                {"title": "ML-KEM-768: Quantum-safe", "metadata": {"pqc_status": "quantum_safe", "asset_name": "ML-KEM-768"}},
            ],
        },
    )

    rollup = build_workspace_crypto_rollup(sample_sbom.component.team_id)

    assert rollup["has_crypto_data"]
    assert rollup["verdict_counts"].get("at_risk") == 1
    row = next(r for r in rollup["rows"] if r["id"] == sample_sbom.component.id)
    assert row["verdict"] == "at_risk"
    assert row["counts"]["quantum_vulnerable"] == 1
    assert row["certificates"]["expired"] == 1
    assert rollup["top_vulnerable"][0] == {"name": "RSA-2048", "components": 1}
    assert rollup["certificates"]["expired"] == 1


@pytest.mark.django_db
def test_workspace_crypto_page_renders_and_gates(sample_sbom: SBOM, guest_user):  # noqa: F811
    team = sample_sbom.component.team
    url = reverse("sboms:workspace_crypto", kwargs={"team_key": team.key})

    member = Client()
    setup_test_session(member, team, team.members.first())
    response = member.get(url)
    assert response.status_code == 200
    assert "Cryptography" in response.content.decode()

    outsider = Client()
    outsider.force_login(guest_user)
    assert outsider.get(url).status_code == 403


def test_cert_expiry_state_accepts_date_only_values():
    from ..crypto_inventory import cert_expiry_state

    days, expired, expiring = cert_expiry_state("2030-01-01", timezone.now())
    assert days is not None and days > 0 and not expired
    _days, expired_past, _ = cert_expiry_state("2020-01-01", timezone.now())
    assert expired_past


@pytest.mark.django_db
def test_cipher_suite_csv_neutralizes_formula_cells(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    doc = {
        "specVersion": "1.6",
        "components": [
            {
                "type": "cryptographic-asset",
                "name": "=EVIL",
                "cryptoProperties": {
                    "assetType": "protocol",
                    "protocolProperties": {
                        "type": "tls",
                        "version": "1.2",
                        "cipherSuites": [{"name": '=HYPERLINK("https://evil","x")'}],
                    },
                },
            }
        ],
    }
    import json as jsonlib

    mocker.patch(_S3_TARGET).return_value.get_sbom_data.return_value = jsonlib.dumps(doc).encode()
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("api-1:download_cipher_suite_inventory_csv", kwargs={"sbom_id": sample_sbom.id}))

    body = response.content.decode()
    assert "'=HYPERLINK" in body  # formula trigger neutralized with a leading quote
    assert "'=EVIL" in body
    assert "\n=" not in body and not body.startswith("=")


@pytest.mark.django_db
def test_crypto_endpoints_return_declared_503_on_storage_outage(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    from botocore.exceptions import ClientError

    error = ClientError({"Error": {"Code": "ServiceUnavailable"}}, "GetObject")
    mocker.patch(_S3_TARGET).return_value.get_sbom_data.side_effect = error
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    csv_response = client.get(
        reverse("api-1:download_cipher_suite_inventory_csv", kwargs={"sbom_id": sample_sbom.id})
    )
    assert csv_response.status_code == 503


@pytest.mark.django_db
def test_workspace_crypto_page_blocks_guests_of_url_workspace(sample_sbom: SBOM, guest_user):  # noqa: F811
    """The session-based guest mixin can be sidestepped; the view must check the
    member's role against the URL workspace itself."""
    from sbomify.apps.teams.models import Member

    team = sample_sbom.component.team
    Member.objects.create(user=guest_user, team=team, role="guest")
    guest = Client()
    guest.force_login(guest_user)

    # The session-team path is covered by GuestAccessBlockedMixin (redirect).
    same_team_session = guest.get(reverse("sboms:workspace_crypto", kwargs={"team_key": team.key}))
    assert same_team_session.status_code == 302

    # The bypass: session's current team unset (or another workspace) makes the
    # mixin a no-op; the view's own role check must still reject the guest.
    session = guest.session
    session["current_team"] = {}
    session.save()
    response = guest.get(reverse("sboms:workspace_crypto", kwargs={"team_key": team.key}))

    assert response.status_code == 403


@pytest.mark.django_db
def test_workspace_rollup_recomputes_cert_expiry_at_read_time(sample_sbom: SBOM):  # noqa: F811
    """Frozen counts said healthy at scan time; the stored dates say expired now."""
    from datetime import timedelta

    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk import RunReason

    from ..services.crypto_dashboard import build_workspace_crypto_rollup

    sample_sbom.bom_type = SBOM.BomType.CBOM
    sample_sbom.save(update_fields=["bom_type"])
    past = (timezone.now() - timedelta(days=5)).isoformat()
    AssessmentRun.objects.create(
        sbom=sample_sbom,
        plugin_name="pqc-readiness",
        plugin_version="1.0",
        plugin_config_hash="x",
        category="compliance",
        status="completed",
        run_reason=RunReason.MANUAL.value,
        result={
            "metadata": {
                "pqc_overall": "ready",
                "certificates": {
                    "count": 1,
                    "expired": 0,
                    "expiring_soon": 0,
                    "soonest_not_valid_after": past,
                    "not_valid_after": [past],
                },
            },
            "findings": [{"title": "AES-256: Quantum-safe", "metadata": {"pqc_status": "quantum_safe"}}],
        },
    )
    from django.core.cache import cache as django_cache

    django_cache.clear()

    rollup = build_workspace_crypto_rollup(sample_sbom.component.team_id)

    assert rollup["certificates"]["expired"] == 1  # recomputed live, not the frozen 0


@pytest.mark.django_db
def test_workspace_crypto_rollup_reads_crypto_free_stamp_without_a_run(sample_sbom: SBOM):  # noqa: F811
    """The dispatch gate skips crypto plugins for artifacts stamped
    has_crypto_assets=False, so no skipped run exists; the rollup must read
    the stamp itself as the no_crypto verdict instead of not_assessed."""
    from django.core.cache import cache

    from ..services.crypto_dashboard import build_workspace_crypto_rollup

    sample_sbom.has_crypto_assets = False
    sample_sbom.save(update_fields=["has_crypto_assets"])
    cache.clear()

    rollup = build_workspace_crypto_rollup(sample_sbom.component.team_id)

    row = next(r for r in rollup["rows"] if r["id"] == sample_sbom.component.id)
    assert row["verdict"] == "no_crypto"


@pytest.mark.django_db
def test_workspace_crypto_rollup_excludes_document_components(sample_sbom: SBOM):  # noqa: F811
    from django.core.cache import cache

    from sbomify.apps.core.models import Component as CoreComponent

    from ..services.crypto_dashboard import build_workspace_crypto_rollup

    CoreComponent.objects.create(
        name="policy-doc-container",
        team=sample_sbom.component.team,
        component_type="document",
    )
    cache.clear()

    rollup = build_workspace_crypto_rollup(sample_sbom.component.team_id)

    assert all(r["name"] != "policy-doc-container" for r in rollup["rows"])


@pytest.mark.django_db
def test_workspace_crypto_rollup_splits_titles_from_both_separator_eras(sample_sbom: SBOM):  # noqa: F811
    from django.core.cache import cache

    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk import RunReason

    from ..services.crypto_dashboard import build_workspace_crypto_rollup

    sample_sbom.bom_type = SBOM.BomType.CBOM
    sample_sbom.save(update_fields=["bom_type"])
    AssessmentRun.objects.create(
        sbom=sample_sbom,
        plugin_name="pqc-readiness",
        plugin_version="1.0",
        plugin_config_hash="x",
        category="compliance",
        status="completed",
        run_reason=RunReason.MANUAL.value,
        result={
            "metadata": {"pqc_overall": "at_risk"},
            "findings": [
                {"title": "RSA-2048: Quantum-vulnerable", "metadata": {"pqc_status": "quantum_vulnerable"}},
                {"title": "ECDSA-P256 — Quantum-vulnerable", "metadata": {"pqc_status": "quantum_vulnerable"}},
            ],
        },
    )
    cache.clear()

    rollup = build_workspace_crypto_rollup(sample_sbom.component.team_id)

    names = {entry["name"] for entry in rollup["top_vulnerable"]}
    assert "RSA-2048" in names
    assert "ECDSA-P256" in names
