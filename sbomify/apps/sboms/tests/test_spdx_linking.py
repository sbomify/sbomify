"""Tests for SPDX-native cross-document linking in release aggregation (#357)."""

import json

import pytest

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.s3_fixtures import s3_sboms_mock  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan  # noqa: F401
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import get_release_sbom_package


def _spdx2_member(team, s3_mock, name, *, namespace, described, sha):
    """A PUBLIC component whose member SBOM is an SPDX 2.3 document in mocked S3."""
    component = Component.objects.create(
        name=f"{name}-comp", team=team, visibility=Component.Visibility.PUBLIC,
        component_type=Component.ComponentType.BOM,
    )
    body = json.dumps(
        {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": name,
            "documentNamespace": namespace,
            "documentDescribes": [described],
            "packages": [{"SPDXID": described, "name": name, "downloadLocation": "NOASSERTION"}],
        }
    ).encode()
    filename = f"{name}.spdx.json"
    s3_mock.uploaded_files[filename] = body
    return SBOM.objects.create(
        name=name, component=component, format="spdx", version="1.0.0", sbom_filename=filename, sha256_hash=sha
    )


def _cdx_member(team, s3_mock, name):
    component = Component.objects.create(
        name=f"{name}-comp", team=team, visibility=Component.Visibility.PUBLIC,
        component_type=Component.ComponentType.BOM,
    )
    body = json.dumps(
        {
            "bomFormat": "CycloneDX", "specVersion": "1.6",
            "metadata": {"component": {"name": name, "type": "library", "version": "1.0.0"}},
            "components": [],
        }
    ).encode()
    filename = f"{name}.cdx.json"
    s3_mock.uploaded_files[filename] = body
    return SBOM.objects.create(
        name=name, component=component, format="cyclonedx", version="1.0.0",
        sbom_filename=filename, sha256_hash="c" * 64,
    )


@pytest.mark.django_db
class TestSPDX23Linking:
    def test_spdx2_member_linked_via_external_document_ref(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        member = _spdx2_member(
            team, s3_sboms_mock, "alpha",
            namespace="https://member.example/spdx/alpha", described="SPDXRef-Package-alpha", sha="b" * 64,
        )
        ReleaseArtifact.objects.create(release=release, sbom=member)

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx").read_bytes())

        refs = out.get("externalDocumentRefs", [])
        assert len(refs) == 1
        assert refs[0]["externalDocumentId"] == "DocumentRef-1"
        assert refs[0]["spdxDocument"] == "https://member.example/spdx/alpha"
        assert refs[0]["checksum"] == {"algorithm": "SHA256", "checksumValue": "b" * 64}
        # CONTAINS references the external element, not a local stub.
        contains = [r for r in out["relationships"] if r["relationshipType"] == "CONTAINS"]
        assert any(r["relatedSpdxElement"] == "DocumentRef-1:SPDXRef-Package-alpha" for r in contains)
        assert "alpha" not in [p["name"] for p in out["packages"]]  # no flattened stub

    def test_cdx_member_falls_back_to_local_stub(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        ReleaseArtifact.objects.create(release=release, sbom=_cdx_member(team, s3_sboms_mock, "beta"))

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx").read_bytes())

        assert out.get("externalDocumentRefs", []) == []  # CDX member can't link natively
        assert "beta" in [p["name"] for p in out["packages"]]  # flattened to a local stub
