"""Merged release-level CBOM: one crypto BOM per release, built from the CBOM
artifacts pinned in the release's slots, gated like the SBOM/VEX downloads."""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.sboms.cbom import build_release_cbom
from sbomify.apps.sboms.models import SBOM


def _release_with_components(team, *, is_public: bool):
    product = Product.objects.create(name="P", team=team, is_public=is_public)
    release = Release.objects.create(product=product, name="v1")
    c1 = Component.objects.create(name="c1", team=team)
    c2 = Component.objects.create(name="c2", team=team)
    return product, release, c1, c2


def _cbom_sbom(component, filename: str) -> SBOM:
    return SBOM.objects.create(
        name=f"cbom-{filename}",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=filename,
        component=component,
        bom_type=SBOM.BomType.CBOM,
    )


def _doc(ref: str) -> bytes:
    return json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"type": "cryptographic-asset", "bom-ref": ref, "name": ref.split("/")[-1]}],
        }
    ).encode()


def _mock_s3(mocker, docs_by_filename: dict[str, bytes]):
    s3 = mocker.patch("sbomify.apps.core.object_store.S3Client")
    s3.return_value.get_sbom_data.side_effect = lambda filename: docs_by_filename[filename]
    return s3


@pytest.mark.django_db
def test_build_release_cbom_merges_slot_documents(sample_team_with_owner_member, mocker):
    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "c1.cbom.json"))
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c2, "c2.cbom.json"))
    _mock_s3(mocker, {"c1.cbom.json": _doc("crypto/a"), "c2.cbom.json": _doc("crypto/b")})

    merged = build_release_cbom(release)

    assert merged is not None
    assert {c["bom-ref"] for c in merged["components"]} == {"crypto/a", "crypto/b"}


@pytest.mark.django_db
def test_build_release_cbom_unions_shared_dependency_edges(sample_team_with_owner_member, mocker):
    """Two components' CBOMs sharing a source node union their dependsOn targets
    rather than dropping the second edge (which would hide crypto usage)."""
    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "a.cbom.json"))
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c2, "b.cbom.json"))
    import json as _json

    doc_a = _json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"bom-ref": "tls-ctx"}, {"bom-ref": "rsa2048"}],
            "dependencies": [{"ref": "tls-ctx", "dependsOn": ["rsa2048"]}],
        }
    ).encode()
    doc_b = _json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"bom-ref": "tls-ctx"}, {"bom-ref": "ecdsaP256"}],
            "dependencies": [{"ref": "tls-ctx", "dependsOn": ["ecdsaP256"]}],
        }
    ).encode()
    _mock_s3(mocker, {"a.cbom.json": doc_a, "b.cbom.json": doc_b})

    merged = build_release_cbom(release)

    edges = {d["ref"]: sorted(d["dependsOn"]) for d in merged["dependencies"]}
    assert edges == {"tls-ctx": ["ecdsaP256", "rsa2048"]}
    assert {c["bom-ref"] for c in merged["components"]} == {"tls-ctx", "rsa2048", "ecdsaP256"}


@pytest.mark.django_db
def test_build_release_cbom_skips_non_dict_components(sample_team_with_owner_member, mocker):
    """A malformed CBOM with a non-dict component entry is skipped, not appended
    (which would produce an invalid merged CycloneDX document)."""
    import json as _json

    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "a.cbom.json"))
    doc = _json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"bom-ref": "good"}, "junk", None, 42],
        }
    ).encode()
    _mock_s3(mocker, {"a.cbom.json": doc})

    merged = build_release_cbom(release)
    assert all(isinstance(c, dict) for c in merged["components"])
    assert {c["bom-ref"] for c in merged["components"]} == {"good"}


@pytest.mark.django_db
def test_build_release_cbom_skips_missing_s3_object(sample_team_with_owner_member, mocker):
    """A missing/unreadable CBOM object is skipped, not 500 — the S3 ClientError
    must be swallowed by the loader."""
    from botocore.exceptions import ClientError

    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "gone.cbom.json"))
    s3 = mocker.patch("sbomify.apps.core.object_store.S3Client")
    s3.return_value.get_sbom_data.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    assert build_release_cbom(release) is None


@pytest.mark.django_db
def test_build_release_cbom_tolerates_malformed_dependsOn(sample_team_with_owner_member, mocker):
    """A malformed dependsOn (non-list, or containing non-string entries) is
    coerced to its string targets instead of raising."""
    import json as _json

    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "a.cbom.json"))
    doc = _json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"bom-ref": "x"}, {"bom-ref": {"weird": 1}}, {"name": "no-ref"}],
            "dependencies": [
                {"ref": "x", "dependsOn": ["ok", {"nested": 1}, 42, None]},
                {"ref": "y", "dependsOn": "not-a-list"},
                {"ref": 99, "dependsOn": ["ignored"]},
            ],
        }
    ).encode()
    _mock_s3(mocker, {"a.cbom.json": doc})

    merged = build_release_cbom(release)
    edges = {d["ref"]: d["dependsOn"] for d in merged["dependencies"]}
    assert edges == {"x": ["ok"], "y": []}
    # Non-string / missing bom-ref components are kept without raising on the set key.
    assert len(merged["components"]) == 3
    assert all(isinstance(c, dict) for c in merged["components"])


@pytest.mark.django_db
def test_build_release_cbom_none_without_slot(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    _product, release, _c1, _c2 = _release_with_components(team, is_public=True)
    assert build_release_cbom(release) is None


@pytest.mark.django_db
def test_download_release_cbom_public_returns_attachment(sample_team_with_owner_member, mocker):
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "c1.cbom.json"))
    _mock_s3(mocker, {"c1.cbom.json": _doc("crypto/a")})
    cache.clear()

    resp = Client().get(reverse("api-1:download_release_cbom", kwargs={"release_id": release.id}))

    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]
    assert resp["Content-Disposition"].rstrip('"').endswith(".cbom.cdx.json")


@pytest.mark.django_db
def test_download_release_cbom_404_when_absent(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    _product, release, _c1, _c2 = _release_with_components(team, is_public=True)
    cache.clear()
    resp = Client().get(reverse("api-1:download_release_cbom", kwargs={"release_id": release.id}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_release_cbom_private_requires_auth(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    _product, release, _c1, _c2 = _release_with_components(team, is_public=False)
    resp = Client().get(reverse("api-1:download_release_cbom", kwargs={"release_id": release.id}))
    assert resp.status_code == 403


def _lineage_docs() -> dict[str, bytes]:
    legacy = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "components": [
            {
                "type": "crypto-asset",
                "bom-ref": "legacy/aes",
                "name": "AES",
                "cryptoProperties": {
                    "assetType": "algorithm",
                    "algorithmProperties": {
                        "variant": "AES-128-GCM",
                        "implementationLevel": "softwarePlainRam",
                        "certificationLevel": "none",
                    },
                    "classicalSecurityLevel": 128,
                    "nistQuantumSecurityLevel": 1,
                },
            },
            {
                "type": "crypto-asset",
                "bom-ref": "legacy/keystore",
                "name": "app-keystore",
                "cryptoProperties": {"assetType": "relatedCryptoMaterial"},
            },
        ],
    }
    modern = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "components": [
            {
                "type": "cryptographic-asset",
                "bom-ref": "modern/ecdsa",
                "name": "ECDSA-P384",
                "cryptoProperties": {
                    "assetType": "algorithm",
                    "algorithmProperties": {"algorithmFamily": "ECDSA", "ellipticCurve": "nist/P-384"},
                },
            }
        ],
    }
    return {"legacy.cbom.json": json.dumps(legacy).encode(), "modern.cbom.json": json.dumps(modern).encode()}


@pytest.mark.django_db
def test_build_release_cbom_normalizes_lineages_for_1_6(sample_team_with_owner_member, mocker):
    """Legacy spellings lift to the 1.6 shape; 1.7-only vocabulary down-converts or drops."""
    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "legacy.cbom.json"))
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c2, "modern.cbom.json"))
    _mock_s3(mocker, _lineage_docs())

    merged = build_release_cbom(release)

    assert merged is not None and merged["specVersion"] == "1.6"
    by_ref = {c["bom-ref"]: c for c in merged["components"]}
    aes = by_ref["legacy/aes"]
    assert aes["type"] == "cryptographic-asset"  # legacy type lifted
    algo = aes["cryptoProperties"]["algorithmProperties"]
    assert algo["parameterSetIdentifier"] == "AES-128-GCM"  # variant renamed
    assert algo["executionEnvironment"] == "software-plain-ram"  # legacy camelCase re-cased to the spec enum
    assert algo["certificationLevel"] == ["none"]  # bare string -> array
    assert algo["classicalSecurityLevel"] == 128  # root levels moved inside
    assert "classicalSecurityLevel" not in aes["cryptoProperties"]
    assert by_ref["legacy/keystore"]["cryptoProperties"]["assetType"] == "related-crypto-material"
    ecdsa_algo = by_ref["modern/ecdsa"]["cryptoProperties"]["algorithmProperties"]
    assert ecdsa_algo["curve"] == "nist/P-384"  # ellipticCurve down-converted
    assert "algorithmFamily" not in ecdsa_algo  # no 1.6 home -> dropped with log
    from sbomify.apps.sboms.apis import validate_cyclonedx_sbom

    assert validate_cyclonedx_sbom(merged)[1] == "1.6"  # the whole document schema-validates


@pytest.mark.django_db
def test_build_release_cbom_1_7_keeps_registry_vocabulary(sample_team_with_owner_member, mocker):
    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "legacy.cbom.json"))
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c2, "modern.cbom.json"))
    _mock_s3(mocker, _lineage_docs())

    merged = build_release_cbom(release, spec_version="1.7")

    assert merged is not None and merged["specVersion"] == "1.7"
    by_ref = {c["bom-ref"]: c for c in merged["components"]}
    ecdsa_algo = by_ref["modern/ecdsa"]["cryptoProperties"]["algorithmProperties"]
    assert ecdsa_algo["algorithmFamily"] == "ECDSA"  # kept for native 1.7
    assert ecdsa_algo["ellipticCurve"] == "nist/P-384"
    # legacy lifting happens for every target version
    assert by_ref["legacy/aes"]["cryptoProperties"]["algorithmProperties"]["parameterSetIdentifier"] == "AES-128-GCM"
    from sbomify.apps.sboms.apis import validate_cyclonedx_sbom

    assert validate_cyclonedx_sbom(merged)[1] == "1.7"  # the whole document schema-validates


@pytest.mark.django_db
def test_download_release_cbom_version_param(sample_team_with_owner_member, mocker):
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "modern.cbom.json"))
    _mock_s3(mocker, _lineage_docs())
    cache.clear()
    url = reverse("api-1:download_release_cbom", kwargs={"release_id": release.id})

    default = Client().get(url)
    assert default.status_code == 200
    assert json.loads(default.content)["specVersion"] == "1.6"

    native = Client().get(url + "?version=1.7")
    assert native.status_code == 200
    assert json.loads(native.content)["specVersion"] == "1.7"

    assert Client().get(url + "?version=2.0").status_code == 400


@pytest.mark.django_db
def test_build_release_cbom_lifts_metadata_component_asset(sample_team_with_owner_member, mocker):
    """A pure CBOM whose sole crypto asset lives in metadata.component must
    contribute it to the merged deliverable, mirroring derive_crypto_inventory."""
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_cbom_sbom(c1, "meta-only.cbom.json"))
    doc = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {
                "component": {
                    "type": "cryptographic-asset",
                    "bom-ref": "crypto/meta-asset",
                    "name": "meta-asset",
                    "cryptoProperties": {"assetType": "algorithm"},
                }
            },
            "components": [],
        }
    ).encode()
    _mock_s3(mocker, {"meta-only.cbom.json": doc})

    merged = build_release_cbom(release)

    assert merged is not None
    assert {c["bom-ref"] for c in merged["components"]} == {"crypto/meta-asset"}
