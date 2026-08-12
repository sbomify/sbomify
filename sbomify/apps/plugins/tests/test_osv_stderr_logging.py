"""The reason a scan failed was being dropped from the line reporting it.

The log pipeline splits records on newlines, so a multi-line stderr arrives as
one line per line and only the first stays attached to the message naming it.
osv-scanner opens with a progress line, so every failed scan in staging came
through as:

    [OSV] Scanner returned code 127: Starting filesystem walk for root: /

The exit code survived. The reason for it did not — and a filesystem-walk
progress note is actively misleading about what went wrong, since it reads
like the scanner was told to scan the root directory.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sbomify.apps.plugins.builtins import osv as osv_module
from sbomify.apps.plugins.builtins.osv import _STDERR_LOG_LIMIT, OSVPlugin, _collapse_for_log

# Shaped like what the scanner actually writes: progress first, cause last.
REAL_STDERR = (
    "Starting filesystem walk for root: /\n"
    "Scanned /tmp/tmpabc123.cdx.json file\n"
    "\n"
    "Error: failed to open lockfile: permission denied\n"
)


class TestCollapsing:
    def test_every_line_survives(self) -> None:
        """The defect in one assertion: the cause has to reach the log line."""
        collapsed = _collapse_for_log(REAL_STDERR)

        assert "permission denied" in collapsed

    def test_it_is_one_line(self) -> None:
        """Anything with a newline in it gets split apart again downstream."""
        assert "\n" not in _collapse_for_log(REAL_STDERR)

    def test_the_lines_stay_distinguishable(self) -> None:
        """Concatenating without a separator would run the last word of one
        line into the first of the next."""
        assert "Starting filesystem walk for root: / | " in _collapse_for_log(REAL_STDERR)

    def test_blank_lines_are_dropped(self) -> None:
        assert " |  | " not in _collapse_for_log(REAL_STDERR)

    @pytest.mark.parametrize("empty", ["", "   ", "\n\n"])
    def test_nothing_in_nothing_out(self, empty: str) -> None:
        assert _collapse_for_log(empty) == ""


class TestTruncationKeepsTheTail:
    """A scanner that dies has usually said why in its last few lines. Keeping
    the head would reproduce the original defect at a larger size."""

    def test_the_end_is_what_is_kept(self) -> None:
        noise = "warning: skipping unrecognised package\n" * 500
        collapsed = _collapse_for_log(noise + "Error: the thing that actually broke\n")

        assert "the thing that actually broke" in collapsed

    def test_the_result_is_bounded(self) -> None:
        collapsed = _collapse_for_log("x" * 100_000)

        assert len(collapsed) <= _STDERR_LOG_LIMIT + 3  # + the ellipsis marker

    def test_truncation_is_visible(self) -> None:
        assert _collapse_for_log("x" * 100_000).startswith("...")

    def test_output_within_the_limit_is_untouched(self) -> None:
        assert not _collapse_for_log("Error: short and complete").startswith("...")


class TestTheWarningItProduces:
    """End to end, at the level an operator reads.

    Asserted against the logger call rather than ``caplog``: the ``sbomify``
    logger sets ``propagate = False``, so records never reach the root handler
    caplog installs and every assertion on them would vacuously pass.
    """

    @pytest.fixture
    def sbom_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "scan.cdx.json"
        path.write_text('{"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}')
        return path

    def _scanner_warning(self, sbom_file: Path) -> str:
        failed = subprocess.CompletedProcess(args=[], returncode=127, stdout="", stderr=REAL_STDERR)

        with (
            patch("subprocess.run", return_value=failed),
            patch.object(osv_module.logger, "warning") as warning,
        ):
            OSVPlugin().assess("test-sbom", sbom_file)

        return next(call.args[0] for call in warning.call_args_list if "Scanner returned code" in call.args[0])

    def test_the_logged_warning_carries_the_cause(self, sbom_file: Path) -> None:
        assert "permission denied" in self._scanner_warning(sbom_file)

    def test_the_logged_warning_is_a_single_line(self, sbom_file: Path) -> None:
        """The property the whole change turns on."""
        assert "\n" not in self._scanner_warning(sbom_file)

    def test_the_exit_code_is_still_named(self, sbom_file: Path) -> None:
        """It was the one useful thing the old line carried, and it stays."""
        assert "127" in self._scanner_warning(sbom_file)
