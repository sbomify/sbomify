"""A scanner-readable copy of an SBOM, derived for one scan and thrown away.

The stored artifact is never modified (ADR-004), and the scanners do not read
every format sbomify accepts: osv-scanner has no SPDX 3 reader, and Dependency
Track takes CycloneDX only. Telling the uploader to convert the document by
hand is the workaround this module exists to stop shipping, so the scan path
derives a copy in a format the scanner knows, scans that, and reports the
findings against the original.

The conversion is lossy by construction, and that is survivable because of
what the scanners actually read. They match on package identity, so a copy
carrying the packages and their purls is enough for the scan; the profile data
a converter drops, SPDX 3 security statements among it, is read from the
stored original instead.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, input is a temp file we wrote
import tempfile
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: Target formats, spelled the way the converter names them on its command line.
#: The CycloneDX target is pinned to 1.6: the converter emits 1.7 by default and
#: Dependency Track is the consumer.
SPDX_2_3_JSON = "spdx-json"
CYCLONEDX_1_6_JSON = "cyclonedx-json@1.6"

DEFAULT_TIMEOUT_SECONDS = 120


class ConversionUnavailable(RuntimeError):
    """No converter is installed, so the caller keeps whatever it did before."""


class ConversionFailed(RuntimeError):
    """The converter ran and would not read the document."""


def converter_path() -> str | None:
    """The converter binary, or ``None`` when it is not installed.

    Separated from :func:`convert_sbom` so a caller can decide what to do about
    a missing converter before it has a document in hand.
    """
    configured = getattr(settings, "SBOM_CONVERTER_PATH", "") or "syft"
    if found := shutil.which(configured):
        return found
    candidate = Path(configured)
    return str(candidate) if candidate.is_file() else None


def convert_sbom(data: bytes, target_format: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    """Return ``data`` re-encoded as ``target_format``.

    Raises :class:`ConversionUnavailable` when no converter is installed and
    :class:`ConversionFailed` when one is but will not read this document.
    Callers distinguish the two: the first is a deployment that cannot convert
    and should degrade to its old behaviour, the second is a document nothing
    can do anything with.
    """
    binary = converter_path()
    if binary is None:
        raise ConversionUnavailable("no SBOM converter is installed")

    with tempfile.TemporaryDirectory(prefix="sbom-convert-") as workdir:
        # Written to a file rather than piped: the converter reads stdin only
        # when told to, and a real path keeps its error messages legible.
        source = Path(workdir) / "source.json"
        source.write_bytes(data)
        argv = [binary, "convert", str(source), "-o", target_format]
        try:
            # Audited, which is what the rule asks for: argv is a fixed list run
            # with shell=False, so nothing in it is interpreted as a command.
            # The binary is an operator setting rather than anything a request
            # supplies, the source is a path this function just created, and
            # the format is one of the module constants above.
            completed = subprocess.run(  # nosec B603  # nosemgrep
                argv,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionFailed(f"conversion timed out after {timeout}s") from exc
        except OSError as exc:
            raise ConversionUnavailable(f"converter could not be run: {exc}") from exc

    stdout = completed.stdout or b""
    # The converter reports a document it cannot read on stderr and still exits
    # 0, so the body is the reliable failure signal rather than the return code.
    # Parsed rather than sniffed: output that merely starts like JSON can still
    # be truncated, and handing that to a scanner turns a conversion failure
    # into what looks like a scanner fault.
    if completed.returncode == 0 and stdout.strip():
        try:
            json.loads(stdout)
        except ValueError as exc:
            raise ConversionFailed(f"converter produced no usable document: {exc}") from exc
        return stdout
    detail = (completed.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    raise ConversionFailed(detail[-1] if detail else f"converter exited {completed.returncode}")
