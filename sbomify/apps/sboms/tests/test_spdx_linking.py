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
        name=f"{name}-comp",
        team=team,
        visibility=Component.Visibility.PUBLIC,
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
        name=f"{name}-comp",
        team=team,
        visibility=Component.Visibility.PUBLIC,
        component_type=Component.ComponentType.BOM,
    )
    body = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"name": name, "type": "library", "version": "1.0.0"}},
            "components": [],
        }
    ).encode()
    filename = f"{name}.cdx.json"
    s3_mock.uploaded_files[filename] = body
    return SBOM.objects.create(
        name=name,
        component=component,
        format="cyclonedx",
        version="1.0.0",
        sbom_filename=filename,
        sha256_hash="c" * 64,
    )


def _spdx3_member(team, s3_mock, name, *, root_uri, sha):
    """A PUBLIC component whose member SBOM is an SPDX 3.0 JSON-LD document."""
    component = Component.objects.create(
        name=f"{name}-comp",
        team=team,
        visibility=Component.Visibility.PUBLIC,
        component_type=Component.ComponentType.BOM,
    )
    body = json.dumps(
        {
            "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
            "@graph": [
                {"type": "software_Package", "spdxId": root_uri, "name": name},
                {"type": "SpdxDocument", "spdxId": f"{root_uri}-doc", "rootElement": [root_uri]},
            ],
        }
    ).encode()
    filename = f"{name}.spdx3.json"
    s3_mock.uploaded_files[filename] = body
    return SBOM.objects.create(
        name=name,
        component=component,
        format="spdx",
        version="1.0.0",
        sbom_filename=filename,
        sha256_hash=sha,
    )


@pytest.mark.django_db
class TestSPDX23Linking:
    def test_spdx2_member_linked_via_external_document_ref(
        self,
        tmp_path,
        team_with_business_plan,
        s3_sboms_mock,  # noqa: F811
    ):
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        member = _spdx2_member(
            team,
            s3_sboms_mock,
            "alpha",
            namespace="https://member.example/spdx/alpha",
            described="SPDXRef-Package-alpha",
            sha="b" * 64,
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
        self,
        tmp_path,
        team_with_business_plan,
        s3_sboms_mock,  # noqa: F811
    ):
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        ReleaseArtifact.objects.create(release=release, sbom=_cdx_member(team, s3_sboms_mock, "beta"))

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx").read_bytes())

        assert out.get("externalDocumentRefs", []) == []  # CDX member can't link natively
        assert "beta" in [p["name"] for p in out["packages"]]  # flattened to a local stub


@pytest.mark.django_db
class TestSPDX30Linking:
    def test_spdx3_member_linked_via_import_map(
        self,
        tmp_path,
        team_with_business_plan,
        s3_sboms_mock,  # noqa: F811
    ):
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        member = _spdx3_member(team, s3_sboms_mock, "gamma", root_uri="https://member.example/g#root", sha="d" * 64)
        ReleaseArtifact.objects.create(release=release, sbom=member)

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx", version="3.0").read_bytes())
        graph = out["@graph"]

        doc = next(e for e in graph if e["type"] == "SpdxDocument")
        imports = doc.get("import", [])
        assert len(imports) == 1
        assert imports[0]["externalSpdxId"] == "https://member.example/g#root"
        assert imports[0]["locationHint"]  # download URL present
        assert imports[0]["verifiedUsing"][0] == {"type": "Hash", "algorithm": "sha256", "hashValue": "d" * 64}

        describes = next(e for e in graph if e["type"] == "Relationship" and e["relationshipType"] == "describes")
        assert "https://member.example/g#root" in describes["to"]
        # No local stub package for the natively-linked member.
        assert "gamma" not in [e.get("name") for e in graph if e["type"] == "software_Package"]

    def test_spdx2_malformed_describes_falls_back_to_document(
        self,
        tmp_path,
        team_with_business_plan,
        s3_sboms_mock,  # noqa: F811
    ):
        """A non-string documentDescribes entry must not produce a garbage
        DocumentRef ref; it falls back to SPDXRef-DOCUMENT."""
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        component = Component.objects.create(
            name="m-comp",
            team=team,
            visibility=Component.Visibility.PUBLIC,
            component_type=Component.ComponentType.BOM,
        )
        body = json.dumps(
            {
                "spdxVersion": "SPDX-2.3",
                "SPDXID": "SPDXRef-DOCUMENT",
                "name": "m",
                "documentNamespace": "https://member.example/m",
                "documentDescribes": ["DocumentRef-9:SPDXRef-x"],  # invalid local id (contains ':')
                "relationships": "not-a-list",  # malformed
            }
        ).encode()
        s3_sboms_mock.uploaded_files["m.spdx.json"] = body
        member = SBOM.objects.create(
            name="m",
            component=component,
            format="spdx",
            version="1.0.0",
            sbom_filename="m.spdx.json",
            sha256_hash="e" * 64,
        )
        ReleaseArtifact.objects.create(release=release, sbom=member)

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx").read_bytes())
        contains = [r for r in out["relationships"] if r["relationshipType"] == "CONTAINS"]
        assert any(r["relatedSpdxElement"] == "DocumentRef-1:SPDXRef-DOCUMENT" for r in contains)

    def test_import_entry_validates_as_typed_external_map(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        """The emitted import-map entry round-trips through the typed ExternalMap model."""
        from sbomify.apps.sboms.sbom_format_schemas.spdx_3_0 import ExternalMap

        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        member = _spdx3_member(team, s3_sboms_mock, "delta", root_uri="https://member.example/d#root", sha="f" * 64)
        ReleaseArtifact.objects.create(release=release, sbom=member)

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx", version="3.0").read_bytes())
        doc = next(e for e in out["@graph"] if e["type"] == "SpdxDocument")
        entry = ExternalMap.model_validate(doc["import"][0])
        assert entry.externalSpdxId == "https://member.example/d#root"
        assert entry.locationHint
        assert entry.verifiedUsing[0].algorithm == "sha256"
        assert entry.verifiedUsing[0].hashValue == "f" * 64


def _spdx2_member_referencing(team, s3_mock, name, *, target_digest, algorithm, sha):
    """An SPDX 2.3 member that declares an externalDocumentRef toward another doc
    identified by (algorithm, target_digest)."""
    component = Component.objects.create(
        name=f"{name}-comp", team=team, visibility=Component.Visibility.PUBLIC,
        component_type=Component.ComponentType.BOM,
    )
    body = json.dumps(
        {
            "spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT", "name": name,
            "documentNamespace": f"https://member.example/{name}",
            "documentDescribes": [f"SPDXRef-Package-{name}"],
            "packages": [{"SPDXID": f"SPDXRef-Package-{name}", "name": name, "downloadLocation": "NOASSERTION"}],
            "externalDocumentRefs": [
                {
                    "externalDocumentId": "DocumentRef-ext",
                    "spdxDocument": "https://evil.example/should-never-be-fetched",
                    "checksum": {"algorithm": algorithm, "checksumValue": target_digest},
                }
            ],
            "relationships": [
                {
                    "spdxElementId": f"SPDXRef-Package-{name}",
                    "relatedSpdxElement": "DocumentRef-ext:SPDXRef-Package-target",
                    "relationshipType": "DEPENDS_ON",
                }
            ],
        }
    ).encode()
    s3_mock.uploaded_files[f"{name}.spdx.json"] = body
    return SBOM.objects.create(
        name=name, component=component, format="spdx", version="1.0.0",
        sbom_filename=f"{name}.spdx.json", sha256_hash=sha,
    )


@pytest.mark.django_db
class TestSPDX2InboundResolve:
    def test_inbound_ref_resolves_to_release_member(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        b_sha = "a" * 64
        b = _spdx2_member(team, s3_sboms_mock, "bbb", namespace="https://member.example/bbb",
                          described="SPDXRef-Package-bbb", sha=b_sha)
        a = _spdx2_member_referencing(team, s3_sboms_mock, "aaa", target_digest=b_sha, algorithm="SHA256", sha="c" * 64)
        ReleaseArtifact.objects.create(release=release, sbom=a)
        ReleaseArtifact.objects.create(release=release, sbom=b)

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx").read_bytes())
        deps = [r for r in out["relationships"] if r["relationshipType"] == "DEPENDS_ON"]
        assert any(
            r["spdxElementId"].endswith(":SPDXRef-Package-aaa")
            and r["relatedSpdxElement"].endswith(":SPDXRef-Package-bbb")
            for r in deps
        ), "A's inbound ref to B (by SHA-256) should become a DEPENDS_ON edge"

    def test_sha1_ref_not_resolved_and_not_fetched(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        b = _spdx2_member(team, s3_sboms_mock, "bbb", namespace="https://member.example/bbb",
                          described="SPDXRef-Package-bbb", sha="a" * 64)
        # A references via SHA1 (sbomify stores only SHA256) -> unresolvable, never fetched.
        a = _spdx2_member_referencing(team, s3_sboms_mock, "aaa", target_digest="d" * 40, algorithm="SHA1", sha="c" * 64)
        ReleaseArtifact.objects.create(release=release, sbom=a)
        ReleaseArtifact.objects.create(release=release, sbom=b)

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx").read_bytes())
        assert [r for r in out["relationships"] if r["relationshipType"] == "DEPENDS_ON"] == []


@pytest.mark.django_db
class TestSPDX3InboundResolve:
    def test_inbound_import_resolves_to_release_member(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        b_sha = "a" * 64
        b = _spdx3_member(team, s3_sboms_mock, "bbb", root_uri="https://member.example/bbb#root", sha=b_sha)
        a_comp = Component.objects.create(
            name="aaa-comp", team=team, visibility=Component.Visibility.PUBLIC,
            component_type=Component.ComponentType.BOM,
        )
        a_root = "https://member.example/aaa#root"
        a_body = json.dumps(
            {
                "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                "@graph": [
                    {"type": "software_Package", "spdxId": a_root, "name": "aaa"},
                    {
                        "type": "Relationship", "spdxId": f"{a_root}-rel",
                        "relationshipType": "dependsOn", "from": a_root, "to": ["https://other/x"],
                    },
                    {
                        "type": "SpdxDocument", "spdxId": f"{a_root}-doc", "rootElement": [a_root],
                        "import": [
                            {
                                "type": "ExternalMap", "externalSpdxId": "https://other/x",
                                "locationHint": "https://evil.example/never-fetched",
                                "verifiedUsing": [{"type": "Hash", "algorithm": "sha256", "hashValue": b_sha}],
                            }
                        ],
                    },
                ],
            }
        ).encode()
        s3_sboms_mock.uploaded_files["aaa.spdx3.json"] = a_body
        a = SBOM.objects.create(
            name="aaa", component=a_comp, format="spdx", version="1.0.0",
            sbom_filename="aaa.spdx3.json", sha256_hash="c" * 64,
        )
        ReleaseArtifact.objects.create(release=release, sbom=a)
        ReleaseArtifact.objects.create(release=release, sbom=b)

        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx", version="3.0").read_bytes())
        deps = [
            e for e in out["@graph"]
            if e.get("type") == "Relationship" and e.get("relationshipType") == "dependsOn"
        ]
        assert any(e["from"] == a_root and "https://member.example/bbb#root" in e["to"] for e in deps)


@pytest.mark.django_db
class TestAggregateSchemaValidity:
    """#357 AC: the aggregate is valid SPDX with referential integrity intact."""

    def test_spdx23_aggregate_validates_against_model(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        from sbomify.apps.sboms.sbom_format_schemas import spdx_2_3

        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        ReleaseArtifact.objects.create(
            release=release,
            sbom=_spdx2_member(team, s3_sboms_mock, "alpha", namespace="https://m/alpha",
                               described="SPDXRef-Package-alpha", sha="a" * 64),
        )
        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx").read_bytes())
        doc = spdx_2_3.SPDXDocument.model_validate(out)  # raises if the serialized output is invalid
        assert doc.externalDocumentRefs  # native link survived serialization + revalidation

    def test_spdx3_aggregate_validates_against_model(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        from sbomify.apps.sboms.sbom_format_schemas.spdx_3_0 import SPDX3Document

        team = team_with_business_plan
        product = Product.objects.create(name="P", team=team, is_public=True)
        release = Release.objects.create(product=product, name="v1.0.0")
        ReleaseArtifact.objects.create(
            release=release,
            sbom=_spdx3_member(team, s3_sboms_mock, "gamma", root_uri="https://m/g#root", sha="b" * 64),
        )
        out = json.loads(get_release_sbom_package(release, tmp_path, output_format="spdx", version="3.0").read_bytes())
        SPDX3Document.model_validate(out)  # raises if the JSON-LD aggregate is structurally invalid
        doc = next(e for e in out["@graph"] if e["type"] == "SpdxDocument")
        assert doc.get("import")  # import map present and the doc validates
