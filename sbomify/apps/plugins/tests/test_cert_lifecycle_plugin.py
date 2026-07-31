"""Tests for the certificate-lifecycle assessment plugin."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sbomify.apps.plugins.builtins.cert_lifecycle import CertificateLifecyclePlugin
from sbomify.apps.plugins.sdk import AssessmentCategory


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cert(name: str, not_before: datetime | str | None, not_after: datetime | str | None) -> dict:
    props: dict = {"subjectName": name}
    if not_before is not None:
        props["notValidBefore"] = _iso(not_before) if isinstance(not_before, datetime) else not_before
    if not_after is not None:
        props["notValidAfter"] = _iso(not_after) if isinstance(not_after, datetime) else not_after
    return {
        "type": "cryptographic-asset",
        "name": name,
        "bom-ref": name.lower(),
        "cryptoProperties": {"assetType": "certificate", "certificateProperties": props},
    }


def _algorithm(name: str) -> dict:
    return {
        "type": "cryptographic-asset",
        "name": name,
        "bom-ref": name.lower(),
        "cryptoProperties": {"assetType": "algorithm"},
    }


def _cbom(*components: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": list(components)}


def _assess(doc: dict, tmp_path: Path):
    path = tmp_path / "cbom.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return CertificateLifecyclePlugin().assess("test-sbom-id", path)


def _one(component: dict, tmp_path: Path):
    return _assess(_cbom(component), tmp_path).findings[0]


_NOW = datetime.now(timezone.utc)


def test_metadata_runs_on_cbom_and_sbom():
    metadata = CertificateLifecyclePlugin().get_metadata()
    assert metadata.name == "certificate-lifecycle"
    assert metadata.category is AssessmentCategory.COMPLIANCE
    assert metadata.supported_bom_types == ["cbom", "sbom"]


def test_expired_certificate_fails(tmp_path: Path):
    finding = _one(_cert("CN=old.example.com", _NOW - timedelta(days=400), _NOW - timedelta(days=10)), tmp_path)
    assert finding.status == "fail"
    assert "expired" in finding.description.lower()


def test_expiring_soon_certificate_warns(tmp_path: Path):
    # An hour of slack so the day count survives truncation to whole days.
    finding = _one(
        _cert("CN=soon.example.com", _NOW - timedelta(days=100), _NOW + timedelta(days=10, hours=1)), tmp_path
    )
    assert finding.status == "warning"
    assert "10" in finding.description


def test_long_validity_window_warns_with_sc081_ceiling(tmp_path: Path):
    # Issued after the SC-081 cutover, so the 200-day ceiling applies.
    finding = _one(_cert("CN=long.example.com", _NOW - timedelta(days=30), _NOW + timedelta(days=700)), tmp_path)
    assert finding.status == "warning"
    assert "200" in finding.description


def test_pre_sc081_certificates_keep_the_398_day_ceiling(tmp_path: Path):
    from datetime import datetime, timezone as tz

    issued = datetime(2026, 1, 1, tzinfo=tz.utc)
    finding = _one(_cert("CN=grandfathered.example.com", issued, issued + timedelta(days=350)), tmp_path)
    assert finding.status in ("pass", "warning")
    if finding.status == "warning":
        assert "Expiring" in finding.title


def test_healthy_certificate_passes(tmp_path: Path):
    finding = _one(_cert("CN=ok.example.com", _NOW - timedelta(days=30), _NOW + timedelta(days=150)), tmp_path)
    assert finding.status == "pass"


def test_unparseable_dates_are_info(tmp_path: Path):
    finding = _one(_cert("CN=odd.example.com", None, "not-a-date"), tmp_path)
    assert finding.status == "info"

    missing = _one(_cert("CN=missing.example.com", None, None), tmp_path)
    assert missing.status == "info"


def test_algorithm_only_document_skips_quietly(tmp_path: Path):
    result = _assess(_cbom(_algorithm("AES-256-GCM")), tmp_path)
    assert result.metadata and result.metadata.get("skipped") is True
    assert result.findings[0].status == "info"


def test_result_serializes_to_json(tmp_path: Path):
    result = _assess(_cbom(_cert("CN=x", _NOW, _NOW + timedelta(days=1))), tmp_path)
    payload = json.dumps(result.to_dict())
    assert json.loads(payload)["category"] == "compliance"
