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
from typing import Any

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
