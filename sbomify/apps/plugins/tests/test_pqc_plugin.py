"""Tests for the PQC-readiness assessment plugin (#1001 increment 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sbomify.apps.plugins.builtins.pqc import PqcReadinessPlugin
from sbomify.apps.plugins.sdk import AssessmentCategory
from sbomify.apps.sboms.tests.fixtures import sample_component  # noqa: F401


def _crypto(name: str, asset_type: str = "algorithm", **algo) -> dict:
    comp = {
        "type": "cryptographic-asset",
        "name": name,
        "bom-ref": name.lower(),
        "cryptoProperties": {"assetType": asset_type},
    }
    if algo:
        comp["cryptoProperties"]["algorithmProperties"] = algo
    return comp


def _cbom(*components: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": list(components)}


def _assess(doc: dict, tmp_path: Path):
    path = tmp_path / "cbom.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return PqcReadinessPlugin().assess("test-sbom-id", path)


def test_metadata_runs_on_cbom_and_sbom():
    metadata = PqcReadinessPlugin().get_metadata()
    assert metadata.name == "pqc-readiness"
    assert metadata.category is AssessmentCategory.COMPLIANCE
    # Both types: pure CBOMs and mixed software SBOMs with embedded crypto.
    assert metadata.supported_bom_types == ["cbom", "sbom"]


def test_assess_classifies_each_crypto_asset(tmp_path: Path):
    doc = _cbom(
        _crypto("RSA-2048", primitive="pke"),
        _crypto("ML-KEM-768", primitive="kem"),
        _crypto("AES-128-GCM", primitive="ae"),
    )
    result = _assess(doc, tmp_path)

    assert result.plugin_name == "pqc-readiness"
    assert result.category == AssessmentCategory.COMPLIANCE.value
    assert result.summary.total_findings == 3
    assert result.summary.fail_count == 1  # RSA
    assert result.summary.pass_count == 1  # ML-KEM
    assert result.summary.warning_count == 1  # AES-128

    by_status = {f.status for f in result.findings}
    assert by_status == {"pass", "fail", "warning"}
    rsa = next(f for f in result.findings if "RSA" in f.title)
    assert rsa.status == "fail"
    assert rsa.remediation  # migration guidance present
    assert rsa.metadata and rsa.metadata["pqc_status"] == "quantum_vulnerable"


def test_non_algorithm_asset_is_not_labelled_unrecognized_algorithm(tmp_path: Path):
    # A certificate/protocol the classifier can't grade is "not assessed", not an "unrecognized algorithm".
    doc = _cbom(_crypto("server-cert", asset_type="certificate"))
    finding = _assess(doc, tmp_path).findings[0]
    assert finding.status == "info"
    assert "not assessed" in finding.title.lower()
    assert "certificate" in finding.title.lower()
    assert "algorithm" not in finding.title.lower()
    assert finding.remediation is None


def test_named_algorithm_inside_certificate_still_classified(tmp_path: Path):
    # If a non-algorithm asset's name does identify an algorithm, keep the real verdict.
    doc = _cbom(_crypto("RSA-2048-signing-cert", asset_type="certificate"))
    finding = _assess(doc, tmp_path).findings[0]
    assert finding.status == "fail"  # RSA -> quantum-vulnerable


def test_summary_counts_include_info_and_sum_to_total(tmp_path: Path):
    # A cert produces a status="info" finding; the summary must count it so the
    # per-status counts sum to total_findings.
    doc = _cbom(_crypto("RSA-2048", primitive="pke"), _crypto("server-cert", asset_type="certificate"))
    summary = _assess(doc, tmp_path).summary
    assert summary.info_count == 1
    assert (
        summary.pass_count + summary.fail_count + summary.warning_count + summary.error_count + summary.info_count
        == summary.total_findings
    )


@pytest.mark.django_db
def test_assess_crypto_free_document_is_skipped_not_warned(tmp_path: Path):
    # The plugin runs on ordinary SBOMs too; a crypto-free document must not
    # accumulate warning findings, it flags itself skipped.
    result = _assess(_cbom(), tmp_path)
    assert result.summary.total_findings == 1
    assert result.findings[0].status == "info"
    assert result.metadata and result.metadata.get("skipped") is True


def test_assess_invalid_json_returns_error_not_raise(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = PqcReadinessPlugin().assess("test-sbom-id", path)
    assert result.summary.error_count == 1
    assert result.findings[0].status == "error"


def test_result_serializes_to_json(tmp_path: Path):
    result = _assess(_cbom(_crypto("RSA-2048", primitive="pke")), tmp_path)
    # The UI consumes result.to_dict() as JSON; it must round-trip.
    payload = json.dumps(result.to_dict())
    assert json.loads(payload)["category"] == "compliance"


def test_metadata_block_includes_standard_reference(tmp_path: Path):
    result = _assess(_cbom(_crypto("RSA-2048", primitive="pke")), tmp_path)
    assert result.metadata and result.metadata["standard_name"]
    assert result.metadata["pqc_overall"] == "at_risk"


def test_assess_crypto_free_explicit_cbom_warns_not_skips(tmp_path: Path):
    """An artifact deliberately tagged cbom with zero crypto assets is a
    generator misfire: it keeps a visible warning instead of a filtered skip.
    The bom_type arrives via the orchestrator-provided SBOMContext."""
    from sbomify.apps.plugins.sdk.base import SBOMContext

    path = tmp_path / "empty.json"
    path.write_text(json.dumps(_cbom()), encoding="utf-8")

    result = PqcReadinessPlugin().assess("test-sbom-id", path, context=SBOMContext(bom_type="cbom"))

    assert result.findings[0].status == "warning"
    assert not (result.metadata or {}).get("skipped")
