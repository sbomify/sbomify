"""Dependency Track reads SPDX through a derived CycloneDX copy.

DT takes CycloneDX only, so every SPDX document used to come back as a skip.
The upload now carries a converted copy instead. The stored artifact is never
modified and the findings come back against it (ADR-004).

The conversion is deliberately not done at the format gate. That gate runs on
every poll of an in-flight scan, so converting there would spend a subprocess
each time to learn what the previous pass already knew.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any
from unittest.mock import patch

import pytest

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.sboms.conversion import ConversionFailed

SPDX_2_3 = json.dumps({"spdxVersion": "SPDX-2.3", "name": "image", "packages": []})
SPDX_3 = json.dumps({"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": []})
CYCLONEDX = json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1})
CONVERTED = b'{"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}'


def _as_dict(result: Any) -> dict[str, Any]:
    return result.model_dump() if hasattr(result, "model_dump") else dataclasses.asdict(result)


@pytest.fixture
def plugin() -> DependencyTrackPlugin:
    return DependencyTrackPlugin()


class TestNamingTheSourceFormat:
    @pytest.mark.parametrize(
        ("document", "expected"),
        [
            (SPDX_2_3, "SPDX-2.3"),
            (SPDX_3, "SPDX-3.0"),
            ('{"nothing": "familiar"}', "unknown"),
            ("not json at all", "unknown"),
            ("[1, 2, 3]", "unknown"),
        ],
    )
    def test_the_label_recorded_on_a_converted_scan(
        self, plugin: DependencyTrackPlugin, document: str, expected: str
    ) -> None:
        assert plugin._source_format_label(document.encode()) == expected


class TestWithoutAConverter:
    def test_spdx_still_skips_and_says_why(self, plugin: DependencyTrackPlugin, tmp_path) -> None:
        """A deployment with no converter behaves as it always did."""
        path = tmp_path / "sbom.json"
        path.write_text(SPDX_2_3)

        with patch("sbomify.apps.plugins.builtins.dependency_track.converter_path", return_value=None):
            result = _as_dict(plugin.assess("sbom-1", path))

        assert result["metadata"].get("skipped") is True
        assert result["findings"][0]["id"] == "dependency-track:unsupported-format"
        assert "no converter installed" in result["metadata"]["conversion_error"]


@pytest.mark.django_db
class TestTheUploadCarriesTheConversion:
    @pytest.fixture
    def scannable(self, tmp_path):
        from sbomify.apps.core.models import Component, Product
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.teams.models import Team
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        team = Team.objects.create(name="DT Conv Team", key="dtconvteam", billing_plan="business")
        server = DependencyTrackServer.objects.create(
            name="DT Conv Server",
            url="https://dt-conv.example.com",
            api_key="key",
            health_status="healthy",
            max_concurrent_scans=10,
        )
        component = Component.objects.create(name="DT Conv Component", team=team)
        product = Product.objects.create(name="DT Conv Product", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="spdx", format_version="2.3")

        path = tmp_path / "sbom.json"
        path.write_text(SPDX_2_3)
        return sbom, path, server

    def _assess_capturing_upload(self, plugin, scannable, convert_patch):
        sbom, path, server = scannable
        captured: dict[str, Any] = {}

        def capture(**kwargs: Any) -> None:
            captured["bytes"] = kwargs["sbom_bytes"]
            raise RuntimeError("stop after the upload was handed its bytes")

        with (
            # The gate checks a converter exists before letting the run
            # continue; the tests container has no binary installed.
            patch(
                "sbomify.apps.plugins.builtins.dependency_track.converter_path",
                return_value="/usr/local/bin/syft",
            ),
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=True),
            patch.object(DependencyTrackPlugin, "_select_dt_server", return_value=server),
            patch.object(DependencyTrackPlugin, "_resolve_release_context", return_value=[]),
            patch.object(DependencyTrackPlugin, "_upload_new_sbom_version", side_effect=capture),
            convert_patch,
        ):
            result = _as_dict(plugin.assess(str(sbom.id), path))
        return captured, result

    def test_the_upload_gets_cyclonedx_not_the_spdx(self, plugin: DependencyTrackPlugin, scannable) -> None:
        convert = patch(
            "sbomify.apps.plugins.builtins.dependency_track.convert_sbom",
            return_value=CONVERTED,
        )
        captured, _ = self._assess_capturing_upload(plugin, scannable, convert)

        assert captured["bytes"] == CONVERTED
        assert json.loads(captured["bytes"])["bomFormat"] == "CycloneDX"

    def test_the_stored_document_is_left_alone(self, plugin: DependencyTrackPlugin, scannable) -> None:
        _, path, _ = scannable
        convert = patch(
            "sbomify.apps.plugins.builtins.dependency_track.convert_sbom",
            return_value=CONVERTED,
        )
        self._assess_capturing_upload(plugin, scannable, convert)

        assert path.read_text() == SPDX_2_3

    def test_a_document_no_converter_reads_is_a_skip(self, plugin: DependencyTrackPlugin, scannable) -> None:
        convert = patch(
            "sbomify.apps.plugins.builtins.dependency_track.convert_sbom",
            side_effect=ConversionFailed("no SPDX document found"),
        )
        _, result = self._assess_capturing_upload(plugin, scannable, convert)

        assert result["metadata"].get("skipped") is True
        assert result["findings"][0]["id"] == "dependency-track:unsupported-format"
        assert "no SPDX document found" in result["metadata"]["conversion_error"]


@pytest.mark.django_db
class TestWhatIsNotConverted:
    def test_cyclonedx_never_reaches_the_converter(self, plugin: DependencyTrackPlugin, tmp_path) -> None:
        path = tmp_path / "sbom.cdx.json"
        path.write_text(CYCLONEDX)

        with (
            patch("sbomify.apps.plugins.builtins.dependency_track.convert_sbom") as convert,
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=False),
        ):
            plugin.assess("sbom-1", path)

        convert.assert_not_called()

    def test_conversion_waits_for_the_upload(self, plugin: DependencyTrackPlugin, tmp_path) -> None:
        """The gate runs on every poll, so it must not convert.

        Stopping the run before the upload (the workspace has DT switched off)
        proves the conversion is not done on the way past the gate.
        """
        path = tmp_path / "sbom.json"
        path.write_text(SPDX_2_3)

        with (
            patch("sbomify.apps.plugins.builtins.dependency_track.convert_sbom") as convert,
            patch(
                "sbomify.apps.plugins.builtins.dependency_track.converter_path",
                return_value="/usr/local/bin/syft",
            ),
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=False),
        ):
            plugin.assess("sbom-1", path)

        convert.assert_not_called()
