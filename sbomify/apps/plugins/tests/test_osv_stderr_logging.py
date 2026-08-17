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


class TestTruncationKeepsBothEnds:
    """Keeping only the tail was the first attempt, and it was wrong for the
    case that matters most: a Go panic puts its message on line one and then
    ten kilobytes of goroutine stack after it. This helper is the only route
    stderr takes to the logs, so whatever it drops is written nowhere."""

    def test_the_end_is_kept(self) -> None:
        """A scanner that dies part way through usually says why just before
        it stops."""
        noise = "warning: skipping unrecognised package\n" * 500
        collapsed = _collapse_for_log(noise + "Error: the thing that actually broke\n")

        assert "the thing that actually broke" in collapsed

    def test_the_beginning_is_kept_too(self) -> None:
        """The panic case. Tail-only truncation discarded this line and kept
        anonymous stack frames."""
        panic = "panic: runtime error: invalid memory address\n" + "\tgithub.com/google/osv-scanner/x.go:42\n" * 500
        collapsed = _collapse_for_log(panic)

        assert "panic: runtime error: invalid memory address" in collapsed

    def test_the_result_is_bounded(self) -> None:
        collapsed = _collapse_for_log("x" * 100_000)

        assert len(collapsed) <= _STDERR_LOG_LIMIT + 60  # + the omission marker

    def test_truncation_is_visible_and_says_how_much(self) -> None:
        collapsed = _collapse_for_log("x" * 100_000)

        assert "chars omitted" in collapsed

    def test_output_within_the_limit_is_untouched(self) -> None:
        assert "omitted" not in _collapse_for_log("Error: short and complete")


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
        """The line naming the exit code, whatever level it is emitted at.

        It moved from warning to error when an aborted scan stopped being
        advisory and started abandoning the run; this reads both so the
        assertions below are about the message rather than the level.
        """
        failed = subprocess.CompletedProcess(args=[], returncode=127, stdout="", stderr=REAL_STDERR)

        with (
            patch("subprocess.run", return_value=failed),
            patch.object(osv_module.logger, "warning") as warning,
            patch.object(osv_module.logger, "error") as error,
        ):
            OSVPlugin().assess("test-sbom", sbom_file)

        calls = list(warning.call_args_list) + list(error.call_args_list)
        return next(call.args[0] for call in calls if "Scanner returned code" in call.args[0])

    def test_the_logged_warning_carries_the_cause(self, sbom_file: Path) -> None:
        assert "permission denied" in self._scanner_warning(sbom_file)

    def test_the_logged_warning_is_a_single_line(self, sbom_file: Path) -> None:
        """The property the whole change turns on."""
        assert "\n" not in self._scanner_warning(sbom_file)

    def test_the_exit_code_is_still_named(self, sbom_file: Path) -> None:
        """It was the one useful thing the old line carried, and it stays."""
        assert "127" in self._scanner_warning(sbom_file)


class TestTheTimeoutPathAlsoReportsWhy:
    """The same defect on the other branch: the exit condition was preserved
    and the reason discarded. TimeoutExpired carries whatever the scanner wrote
    before it was killed, which is the only account of where it stalled."""

    @pytest.fixture
    def sbom_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "scan.cdx.json"
        path.write_text('{"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}')
        return path

    def _timeout_log(self, sbom_file: Path, stderr) -> str:
        timed_out = subprocess.TimeoutExpired(cmd=["osv-scanner"], timeout=300, stderr=stderr)

        with (
            patch("subprocess.run", side_effect=timed_out),
            patch.object(osv_module.logger, "error") as error,
        ):
            OSVPlugin().assess("test-sbom", sbom_file)

        return next(call.args[0] for call in error.call_args_list if "timed out" in call.args[0])

    def test_the_partial_output_reaches_the_log(self, sbom_file: Path) -> None:
        log = self._timeout_log(sbom_file, "Resolving npm registry for lodash\nstill waiting\n")

        assert "Resolving npm registry for lodash" in log

    def test_it_is_still_a_single_line(self, sbom_file: Path) -> None:
        log = self._timeout_log(sbom_file, "one\ntwo\nthree\n")

        assert "\n" not in log

    def test_bytes_stderr_is_decoded(self, sbom_file: Path) -> None:
        """subprocess hands back bytes when the call was not made in text mode,
        and a partial read can be invalid UTF-8."""
        log = self._timeout_log(sbom_file, b"Resolving \xff\xfe registry\n")

        assert "Resolving" in log

    def test_no_output_says_so_rather_than_trailing_a_colon(self, sbom_file: Path) -> None:
        assert self._timeout_log(sbom_file, None).endswith("with no output")
