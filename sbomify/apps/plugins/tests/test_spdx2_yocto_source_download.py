"""A Yocto source download is exempt from the per-package identifier check.

Beside every recipe, Yocto's create-spdx emits one package per fetched source:
``SPDXRef-Download-openssl-1``, named ``openssl-source-1``, carrying the
tarball URL and its SHA256 and no purl, CPE or SWID. No producer can add one,
so every Yocto recipe document scored one identifier short. It is exempted the
way CycloneDX ``type=file`` components are. Ordinary packages are not.
"""

from __future__ import annotations

from typing import Any

import pytest

from sbomify.apps.plugins.builtins._spdx_shared import spdx2_yocto_source_downloads
from sbomify.apps.plugins.tests.test_spdx2_identifier_iri import IRI, PLUGINS
from sbomify.apps.plugins.tests.test_spdx2_identifier_iri import _document as _recipe_document

YOCTO_CREATOR = "Tool: OpenEmbedded Core create-spdx.bbclass"
TARBALL = "https://github.com/openssl/openssl/releases/download/openssl-3.2.3/openssl-3.2.3.tar.gz"


def _download(spdx_id: str = "SPDXRef-Download-openssl-1", location: str = TARBALL) -> dict[str, Any]:
    return {
        "SPDXID": spdx_id,
        "name": "openssl-source-1",
        "downloadLocation": location,
        "checksums": [{"algorithm": "SHA256", "checksumValue": "b" * 64}],
        "supplier": "NOASSERTION",
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
    }


def _document(download: dict[str, Any], creator: str = YOCTO_CREATOR) -> dict[str, Any]:
    """The Yocto 5.0.x recipe shape: the recipe with its CPE, plus its source download."""
    document = _recipe_document(IRI)
    document["creationInfo"]["creators"] = [creator, "Organization: OpenEmbedded ()"]
    document["packages"].append(download)
    document["relationships"].append(
        {
            "spdxElementId": download["SPDXID"],
            "relationshipType": "BUILD_DEPENDENCY_OF",
            "relatedSpdxElement": "SPDXRef-Recipe-openssl",
        }
    )
    return document


def _identifier_finding(plugin_cls: type, finding_id: str, extra_args: tuple, document: dict[str, Any]):
    plugin = plugin_cls()
    validate = getattr(plugin, "_validate_spdx", None) or plugin._validate_spdx2
    matches = [f for f in validate(document, *extra_args) if getattr(f, "id", None) == finding_id]
    assert matches, f"{plugin_cls.__name__} reported no finding {finding_id!r}"
    return matches[0]


@pytest.mark.parametrize(("plugin_cls", "finding_id", "extra_args"), PLUGINS)
class TestYoctoSourceDownload:
    def test_the_source_download_does_not_need_an_identifier(
        self, plugin_cls: type, finding_id: str, extra_args: tuple
    ) -> None:
        finding = _identifier_finding(plugin_cls, finding_id, extra_args, _document(_download()))

        assert finding.status == "pass", finding.description

    def test_a_git_fetch_is_a_source_download_too(self, plugin_cls: type, finding_id: str, extra_args: tuple) -> None:
        document = _document(_download(location="git+https://git.example.com/openssl.git@0123abcd"))
        del document["packages"][-1]["checksums"]

        assert _identifier_finding(plugin_cls, finding_id, extra_args, document).status == "pass"

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param(_document(_download(), creator="Tool: some-other-generator-1.0"), id="other-producer"),
            pytest.param(_document(_download(spdx_id="SPDXRef-Package-openssl-source-1")), id="ordinary-package"),
            pytest.param(_document(_download(location="NOASSERTION")), id="no-location"),
        ],
    )
    def test_anything_else_still_needs_one(
        self, plugin_cls: type, finding_id: str, extra_args: tuple, document: dict[str, Any]
    ) -> None:
        finding = _identifier_finding(plugin_cls, finding_id, extra_args, document)

        assert finding.status != "pass"
        assert "openssl-source-1" in (finding.description or "")


def test_only_the_download_is_exempt() -> None:
    assert spdx2_yocto_source_downloads(_document(_download())) == {"SPDXRef-Download-openssl-1"}


@pytest.mark.parametrize("creation_info", [None, "x", {"creators": None}, {"creators": [None, 3]}])
def test_malformed_creation_info_exempts_nothing(creation_info: Any) -> None:
    document = _document(_download())
    document["creationInfo"] = creation_info

    assert spdx2_yocto_source_downloads(document) == frozenset()
