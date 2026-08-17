"""Dependency Track refusing a CycloneDX version is a gap, not a fault.

From staging:

    [DT] Failed to upload SBOM ZWiImVwsDLlZ to DT: Dependency Track error (400):
    The uploaded BOM is invalid: Unrecognized specVersion 1.7

The format gate only checks ``bomFormat``, so a CycloneDX 1.7 document passes
it, gets uploaded, and is rejected by a server that only knows up to 1.6. Every
scan of that artifact then logged an ERROR and stored a ``dependency-track:error``
marker carrying ``severity="high"`` — which is the row Viktor reported seeing on
the component page.

The plugin already treats "DT cannot process this" as skipped rather than failed
for SPDX. A spec version the server has not caught up to is the same situation.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any
from unittest.mock import patch

import pytest

from sbomify.apps.plugins.builtins.dependency_track import (
    DependencyTrackPlugin,
    _is_unsupported_spec_version,
)

# The message Dependency Track actually returned, from the staging log.
REAL_REJECTION = Exception(
    "Dependency Track error (400): The uploaded BOM is invalid: Unrecognized specVersion 1.7"
)


def _as_dict(result: Any) -> dict[str, Any]:
    return result.model_dump() if hasattr(result, "model_dump") else dataclasses.asdict(result)


class TestRecognisingTheRejection:
    def test_the_real_message_is_recognised(self) -> None:
        assert _is_unsupported_spec_version(REAL_REJECTION) is True

    @pytest.mark.parametrize(
        "message",
        [
            "Dependency Track error (400): The uploaded BOM is invalid: Unsupported specVersion 2.0",
            "unrecognized specversion 1.9",
        ],
    )
    def test_wording_variants_are_recognised(self, message: str) -> None:
        assert _is_unsupported_spec_version(Exception(message)) is True

    @pytest.mark.parametrize(
        "message",
        [
            # A genuinely broken document, which must keep its error result.
            "Dependency Track error (400): The uploaded BOM is invalid: Unexpected end of input",
            "Dependency Track error (401): Unauthorized",
            "Connection refused",
            "Dependency Track error (500): Internal Server Error",
        ],
    )
    def test_other_failures_are_not_swallowed(self, message: str) -> None:
        """The narrowness is the point. Reading a corrupt BOM or a dead server as
        "not applicable" would hide the thing worth knowing."""
        assert _is_unsupported_spec_version(Exception(message)) is False


class TestTheResultItProduces:
    @pytest.fixture
    def result(self) -> dict[str, Any]:
        plugin = DependencyTrackPlugin()
        return _as_dict(
            plugin._create_skipped_result(
                finding_id="dependency-track:unsupported-spec-version",
                title="Spec Version Not Supported",
                description="This Dependency Track server does not accept this CycloneDX spec version.",
            )
        )

    def test_it_is_skipped_not_errored(self, result: dict[str, Any]) -> None:
        assert result["metadata"]["skipped"] is True
        assert result["summary"]["error_count"] == 0

    def test_it_carries_no_severity(self, result: dict[str, Any]) -> None:
        """The error result it replaces carried ``severity="high"``, which is
        what put a HIGH row on the component page."""
        assert result["findings"][0]["severity"] != "high"

    def test_it_is_not_a_vulnerability(self, result: dict[str, Any]) -> None:
        from sbomify.apps.vulnerability_scanning.utils import is_vulnerability

        assert is_vulnerability(result["findings"][0]) is False


@pytest.mark.django_db
class TestItDoesNotRenderAsPassingEither:
    def test_a_skipped_run_earns_no_public_badge(self) -> None:
        """Not an error, but not a clean bill of health — nothing was scanned."""
        from sbomify.apps.plugins.models import AssessmentRun, RunStatus
        from sbomify.apps.plugins.public_assessment_utils import _is_run_passing

        plugin = DependencyTrackPlugin()
        run = AssessmentRun(
            plugin_name="dependency-track",
            category="security",
            status=RunStatus.COMPLETED.value,
            result=_as_dict(
                plugin._create_skipped_result(
                    finding_id="dependency-track:unsupported-spec-version",
                    title="Spec Version Not Supported",
                    description="x",
                )
            ),
        )

        assert _is_run_passing(run) is False


@pytest.mark.django_db
class TestTheWiringInAssess:
    """The branch itself, not just the pieces it is built from.

    ``_is_unsupported_spec_version`` and ``_create_skipped_result`` can both be
    correct while nothing calls them. These drive the real ``assess()`` with the
    upload raising, which is the only way to know the two are connected.
    """

    @pytest.fixture
    def scannable_sbom(self, tmp_path):
        """An SBOM that gets all the way to the upload."""
        from sbomify.apps.core.models import Component, Product
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.teams.models import Team
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        team = Team.objects.create(name="DT Spec Team", key="dtspecteam", billing_plan="business")
        # A real row, not a mock: the plugin queries
        # SbomDependencyTrackProjectVersion by this FK before it uploads, and a
        # MagicMock has no primary key to resolve.
        server = DependencyTrackServer.objects.create(
            name="DT Spec Server",
            url="https://dt-spec.example.com",
            api_key="key",
            health_status="healthy",
            max_concurrent_scans=10,
        )
        component = Component.objects.create(name="DT Spec Component", team=team)
        product = Product.objects.create(name="DT Spec Product", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.7")

        path = tmp_path / "sbom.cdx.json"
        path.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1}))
        return sbom, path, server

    def _assess_with_upload_raising(self, plugin, sbom, path, server, error):
        with (
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=True),
            patch.object(DependencyTrackPlugin, "_select_dt_server", return_value=server),
            patch.object(DependencyTrackPlugin, "_resolve_release_context", return_value=[]),
            patch.object(DependencyTrackPlugin, "_upload_new_sbom_version", side_effect=error),
        ):
            return _as_dict(plugin.assess(str(sbom.id), path))

    def test_the_real_rejection_becomes_a_skip(self, scannable_sbom) -> None:
        sbom, path, server = scannable_sbom

        result = self._assess_with_upload_raising(DependencyTrackPlugin(), sbom, path, server, REAL_REJECTION)

        assert result["metadata"].get("skipped") is True
        assert result["findings"][0]["id"] == "dependency-track:unsupported-spec-version"
        assert result["summary"]["error_count"] == 0

    def test_the_rejection_carries_the_backoff_marker(self, scannable_sbom) -> None:
        """Asserted here, on the real assess() path, rather than only against
        the helper that builds the result. The scheduled sweep reads this flag
        from the stored run and the two live in different modules — dropping
        ``unsupported_input=True`` from this call site left the whole suite
        green while every stored rejection lost the marker, the backoff matched
        nothing, and the hourly re-upload loop came back."""
        sbom, path, server = scannable_sbom

        result = self._assess_with_upload_raising(DependencyTrackPlugin(), sbom, path, server, REAL_REJECTION)

        assert result["metadata"].get("unsupported_input") is True

    def test_an_upload_failure_does_not_carry_it(self, scannable_sbom) -> None:
        """The marker means "cannot read this input", and nothing else.

        Named for what this actually drives: a 401 from the upload, which
        returns an error result rather than a skip. The point is that a failure
        the scanner might recover from keeps the hourly cadence instead of
        being parked for a day.
        """
        sbom, path, server = scannable_sbom

        result = self._assess_with_upload_raising(
            DependencyTrackPlugin(), sbom, path, server, Exception("Dependency Track error (401): Unauthorized")
        )

        assert result["metadata"].get("unsupported_input") is not True

    def test_any_other_upload_failure_is_still_an_error(self, scannable_sbom) -> None:
        """The half that keeps the change honest: a real failure must not be
        quietly reclassified as "not applicable"."""
        sbom, path, server = scannable_sbom

        result = self._assess_with_upload_raising(
            DependencyTrackPlugin(), sbom, path, server, Exception("Dependency Track error (401): Unauthorized")
        )

        assert result["metadata"].get("skipped") is not True
        assert result["findings"][0]["id"] == "dependency-track:error"
        assert result["summary"]["error_count"] == 1
