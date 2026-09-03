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
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.sboms.conversion import ConversionFailed, ConversionUnavailable

SPDX_2_3 = json.dumps({"spdxVersion": "SPDX-2.3", "name": "image", "packages": []})
SPDX_3 = json.dumps({"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": []})
CYCLONEDX = json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1})
CONVERTED = b'{"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}'


def _as_dict(result: Any) -> dict[str, Any]:
    return result.model_dump() if hasattr(result, "model_dump") else dataclasses.asdict(result)


def _document_version(document: str) -> str:
    """The version the document declares, so the row matches its own bytes.

    A hardcoded "1.6" put a CycloneDX spec version on SPDX rows, which is
    data no upload could produce and would mask a bug the day anything
    branches on ``sbom.format_version``.
    """
    data = json.loads(document)
    if spdx2 := data.get("spdxVersion"):
        return str(spdx2).removeprefix("SPDX-")
    context = data.get("@context")
    if isinstance(context, str) and "spdx-context" in context:
        return context.rsplit("/spdx-context", 1)[0].rsplit("/", 1)[-1]
    return str(data.get("specVersion", ""))


def _records(tmp_path, document: str, fmt: str, key: str, filename: str):
    """Real rows, so assess() gets past the lookup and reaches the upload."""
    from sbomify.apps.core.models import Component, Product
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.teams.models import Team
    from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

    team = Team.objects.create(name=f"Team {key}", key=key, billing_plan="business")
    server = DependencyTrackServer.objects.create(
        name=f"Server {key}",
        url=f"https://{key}.example.com",
        api_key="key",
        health_status="healthy",
        max_concurrent_scans=10,
    )
    component = Component.objects.create(name=f"Component {key}", team=team)
    product = Product.objects.create(name=f"Product {key}", team=team)
    product.components.add(component)
    sbom = SBOM.objects.create(name="s", component=component, format=fmt, format_version=_document_version(document))

    path = tmp_path / filename
    path.write_text(document)
    return sbom, path, server


@pytest.fixture
def plugin() -> DependencyTrackPlugin:
    return DependencyTrackPlugin()


class TestRecognisingSpdx3Lines:
    """A 3.1 document is convertible, and the label says which line it came from."""

    @pytest.mark.parametrize(
        ("context", "expected"),
        [
            ("https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "SPDX-3.0"),
            ("https://spdx.org/rdf/3.1.0/spdx-context.jsonld", "SPDX-3.1"),
            ("https://spdx.org/rdf/3.2/spdx-context.jsonld", "SPDX-3.2"),
        ],
    )
    def test_any_3x_line_is_spdx3(self, plugin: DependencyTrackPlugin, context: str, expected: str) -> None:
        document = json.dumps({"@context": context, "@graph": []}).encode()

        assert plugin._source_format_label(document) == expected

    def test_a_bare_graph_is_still_spdx3(self, plugin: DependencyTrackPlugin) -> None:
        """No context, so the graph is the only signal, and the label falls back to 3.0."""
        assert plugin._source_format_label(json.dumps({"@graph": []}).encode()) == "SPDX-3.0"

    def test_something_that_is_neither_is_unknown(self, plugin: DependencyTrackPlugin) -> None:
        assert plugin._source_format_label(json.dumps({"hello": "world"}).encode()) == "unknown"


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

    def test_no_converter_installed_is_a_skip_that_says_so(self, plugin: DependencyTrackPlugin, scannable) -> None:
        """A deployment without the binary behaves as it always did."""
        convert = patch(
            "sbomify.apps.plugins.builtins.dependency_track.convert_sbom",
            side_effect=ConversionUnavailable("no SBOM converter is installed"),
        )
        _, result = self._assess_capturing_upload(plugin, scannable, convert)

        assert result["metadata"].get("skipped") is True
        assert "no SBOM converter is installed" in result["metadata"]["conversion_error"]
        # The longer sweep backoff, so a converter that is not there is not
        # re-attempted on every pass.
        assert result["metadata"]["unsupported_input"] is True

    def test_a_poll_neither_converts_nor_needs_a_converter(self, plugin: DependencyTrackPlugin, scannable) -> None:
        """The upload already happened, and a poll must return its findings.

        Workers are not guaranteed to be identical, so one without the binary
        has to be able to poll a scan another worker uploaded. It also records
        the provenance, which is only known from the stored document.
        """
        from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

        sbom, path, server = scannable
        SbomDependencyTrackProjectVersion.objects.create(
            sbom=sbom, dt_server=server, dt_project_version="1.0", dt_project_version_uuid=uuid.uuid4()
        )
        captured: dict[str, Any] = {}

        def fake_poll(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        with (
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=True),
            patch.object(DependencyTrackPlugin, "_select_dt_server", return_value=server),
            patch.object(DependencyTrackPlugin, "_resolve_release_context", return_value=[]),
            patch("sbomify.apps.plugins.builtins.dependency_track.convert_sbom") as convert,
            patch.object(DependencyTrackPlugin, "_poll_results", side_effect=fake_poll),
        ):
            plugin.assess(str(sbom.id), path)

        convert.assert_not_called()
        assert captured["converted_from"] == "SPDX-2.3"

    def test_a_document_no_converter_reads_is_a_skip(self, plugin: DependencyTrackPlugin, scannable) -> None:
        convert = patch(
            "sbomify.apps.plugins.builtins.dependency_track.convert_sbom",
            side_effect=ConversionFailed("no SPDX document found"),
        )
        _, result = self._assess_capturing_upload(plugin, scannable, convert)

        assert result["metadata"].get("skipped") is True
        assert result["findings"][0]["id"] == "dependency-track:unsupported-format"
        assert "no SPDX document found" in result["metadata"]["conversion_error"]
        assert result["metadata"]["unsupported_input"] is True


@pytest.mark.django_db
class TestWhatIsNotConverted:
    def test_cyclonedx_reaches_the_upload_unconverted(self, plugin: DependencyTrackPlugin, tmp_path) -> None:
        """Driven all the way to the upload, so this says more than "not yet"."""
        sbom, path, server = _records(tmp_path, CYCLONEDX, "cyclonedx", "dtcdxteam", "sbom.cdx.json")
        captured: dict[str, Any] = {}

        def capture(**kwargs: Any) -> None:
            captured["bytes"] = kwargs["sbom_bytes"]
            raise RuntimeError("stop after the upload was handed its bytes")

        with (
            patch("sbomify.apps.plugins.builtins.dependency_track.convert_sbom") as convert,
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=True),
            patch.object(DependencyTrackPlugin, "_select_dt_server", return_value=server),
            patch.object(DependencyTrackPlugin, "_resolve_release_context", return_value=[]),
            patch.object(DependencyTrackPlugin, "_upload_new_sbom_version", side_effect=capture),
        ):
            plugin.assess(str(sbom.id), path)

        convert.assert_not_called()
        assert captured["bytes"] == CYCLONEDX.encode()

    def test_conversion_waits_for_the_upload(self, plugin: DependencyTrackPlugin, tmp_path) -> None:
        """The gate runs on every poll, so it must not convert.

        The run stops after the lookup, on the workspace having Dependency
        Track switched off, which is past the gate and short of the upload.
        """
        sbom, path, _ = _records(tmp_path, SPDX_2_3, "spdx", "dtgateteam", "sbom.json")

        with (
            patch("sbomify.apps.plugins.builtins.dependency_track.convert_sbom") as convert,
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=False),
        ):
            plugin.assess(str(sbom.id), path)

        convert.assert_not_called()

    def test_a_json_array_is_a_skip_rather_than_a_crash(self, plugin: DependencyTrackPlugin, tmp_path) -> None:
        """Valid JSON that is not an object must not raise on the way to the skip."""
        path = tmp_path / "sbom.json"
        path.write_text("[1, 2, 3]")

        result = _as_dict(plugin.assess("sbom-1", path))

        assert result["metadata"].get("skipped") is True
        assert result["findings"][0]["id"] == "dependency-track:unsupported-format"
