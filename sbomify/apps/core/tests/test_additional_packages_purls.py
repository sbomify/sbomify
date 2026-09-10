"""The Go PURLs baked into the image SBOM must name the right module.

``bin/generate_additional_packages.sh`` emits the PURLs for the two Go binaries
the image ships (osv-scanner, cosign). CI writes them to the file that
``sbomify-action`` reads as ``ADDITIONAL_PACKAGES_FILE``, so whatever this
script prints ends up in the published SBOM for the container.

A Go module path carries its major version from v2 onward, so cosign v3.1.3 is
``github.com/sigstore/cosign/v3``. Dropping the suffix does not merely mislabel
the package: it names the *abandoned v1 module*, whose advisory entries are
open-ended ("introduced 0", no fixed version) and therefore match every version
that has ever existed. The bare path against v3.1.3 made scanners report all six
historical cosign CVEs against a binary that fixed the last of them in 3.0.6.

The failure is silent (a well-formed PURL, just the wrong one) and only surfaces
weeks later as phantom advisories, which is why it is pinned down here.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "bin" / "generate_additional_packages.sh"

# pkg:golang/<module path>@<version>
PURL_RE = re.compile(r"^pkg:golang/(?P<module>[^@]+)@(?P<version>v\d[\w.\-+]*)$")


def _run_script() -> list[str]:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"script failed: {result.stderr}"
    return [line for line in result.stdout.splitlines() if line.strip()]


def _module_path(base: str, version: str) -> str:
    """Call the script's own ``go_module_path`` helper by sourcing it."""
    result = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; go_module_path "{base}" "{version}"'],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"helper failed: {result.stderr}"
    return result.stdout.strip()


class TestGoModulePath:
    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("v0.9.1", "example.com/mod"),
            ("v1.13.6", "example.com/mod"),
            ("v2.3.8", "example.com/mod/v2"),
            ("v3.1.3", "example.com/mod/v3"),
            ("v10.0.0", "example.com/mod/v10"),
        ],
    )
    def test_major_version_suffix(self, version: str, expected: str) -> None:
        assert _module_path("example.com/mod", version) == expected

    @pytest.mark.parametrize("version", ["", "notaversion", "vX.Y.Z"])
    def test_unparseable_version_falls_back_to_bare_path(self, version: str) -> None:
        """A bad version must not produce a nonsense ``/vX`` segment."""
        assert _module_path("example.com/mod", version) == "example.com/mod"


class TestEmittedPurls:
    def test_emits_one_purl_per_shipped_binary(self) -> None:
        lines = _run_script()
        assert len(lines) == 2, f"expected 2 PURLs, got {lines}"
        assert all(PURL_RE.match(line) for line in lines), lines

    def test_module_path_matches_version_major(self) -> None:
        """The suffix must agree with the version, whatever the Dockerfile pins.

        Asserting the relationship rather than a literal string keeps this test
        honest across future version bumps: it fails when cosign goes to v4 and
        the emitted path still says /v3.
        """
        for line in _run_script():
            match = PURL_RE.match(line)
            assert match, line
            module, version = match.group("module"), match.group("version")
            major = int(version.lstrip("v").split(".")[0])

            if major >= 2:
                assert module.endswith(f"/v{major}"), (
                    f"{module} is version {version} but does not carry the /v{major} suffix; "
                    "this names the abandoned v1 module and matches every advisory forever"
                )
            else:
                assert not re.search(r"/v\d+$", module), f"{module} at {version} should carry no major suffix"

    def test_covers_both_binaries(self) -> None:
        modules = []
        for line in _run_script():
            match = PURL_RE.match(line)
            assert match, line
            modules.append(match.group("module"))

        assert any("osv-scanner" in m for m in modules), modules
        assert any("cosign" in m for m in modules), modules
