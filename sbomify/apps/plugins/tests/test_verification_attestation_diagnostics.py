"""A 404 from the attestations API has to say what it was looking for.

Over 48 hours of production the GitHub-attestation check succeeded zero times
out of 78 lookups, across four separate repositories. Every one ended the same
way: four retries over ~34 minutes, then a run finalised with

    No attestation found yet for this SBOM (digest: sha256:<hex>)

That message cannot be acted on. GitHub returns a bare 404 whether the
attestation has not been published yet or the repository attests a different
subject entirely, and the retry ladder only helps with the first. Attesting the
container image rather than the SBOM, or attesting a copy of the document
written before a step rewrote it, produces a digest that will never match no
matter how long we wait — and nothing in the output let an operator tell that
apart from a slow publish.

The lookup key is the SHA-256 of the SBOM exactly as sbomify stored it. Saying
so, and saying which repository was searched, is what turns the failure into
something a user can compare against ``gh attestation list``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.plugins.builtins.verification import (
    AttestationNotYetAvailableError,
    SBOMVerificationPlugin,
)
from sbomify.apps.plugins.sdk.base import SBOMContext

ORG = "example-org"
REPO = "example-repo"


def _cyclonedx_with_vcs(tmp_path: Path) -> tuple[Path, str]:
    import hashlib

    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "widget",
                "externalReferences": [
                    {"type": "vcs", "url": f"https://github.com/{ORG}/{REPO}"},
                ],
            }
        },
    }
    raw = json.dumps(doc).encode()
    path = tmp_path / "sbom.json"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _response(status: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {"message": "Not Found"}
    response.text = "Not Found"
    return response


@pytest.fixture
def sbom(tmp_path: Path) -> tuple[Path, str]:
    return _cyclonedx_with_vcs(tmp_path)


class TestTheNotFoundMessage:
    """This text becomes the run's error once the retry budget is spent, so it
    is the only thing most users will ever see about the failure."""

    def _raise_404(self, sbom: tuple[Path, str]) -> AttestationNotYetAvailableError:
        sbom_file, sha256 = sbom
        plugin = SBOMVerificationPlugin()
        session = MagicMock()
        session.get.return_value = _response(404)

        with (
            patch("sbomify.apps.plugins.builtins.verification.get_http_session", return_value=session),
            patch.object(plugin, "_fetch_blob", return_value=None),
            pytest.raises(AttestationNotYetAvailableError) as excinfo,
        ):
            plugin.assess("sbom-1", sbom_file, context=SBOMContext(sha256_hash=sha256))
        return excinfo.value

    def test_it_names_the_digest_that_was_searched_for(self, sbom) -> None:
        _, sha256 = sbom

        assert f"sha256:{sha256}" in str(self._raise_404(sbom))

    def test_it_says_what_the_digest_is_of(self, sbom) -> None:
        """Without this the digest is an opaque token. With it, an operator can
        compare it against what their workflow actually attested."""
        message = str(self._raise_404(sbom))

        assert "as sbomify stored it" in message

    def test_it_names_the_repository_searched(self, sbom) -> None:
        """Which repo was searched is derived from the SBOM's VCS reference, not
        chosen by the user, so it is worth stating outright."""
        assert f"{ORG}/{REPO}" in str(self._raise_404(sbom))

    def test_it_names_the_failure_that_retrying_cannot_fix(self, sbom) -> None:
        """The retry ladder only helps a slow publish. A mismatched subject is
        permanent, and the message has to admit that possibility or the user
        waits for something that will never arrive."""
        assert "different subject" in str(self._raise_404(sbom))

    def test_it_does_not_assert_the_attestation_is_absent(self, sbom) -> None:
        """GitHub answers 404 for a private or nonexistent repo too, because
        this lookup is unauthenticated. Asserting the digest was searched for
        and not found sent operators to rewrite a correct attest step when the
        real cause was that sbomify cannot see the repository at all."""
        message = str(self._raise_404(sbom))

        assert "private" in message
        assert "unauthenticated" in message

    def test_it_still_admits_the_attestation_may_simply_be_late(self, sbom) -> None:
        """The reason this is a retryable error in the first place."""
        assert "not been published yet" in str(self._raise_404(sbom))


class TestTheFindingOnOtherFailures:
    """Non-404 download failures take the warning path instead, and need the
    same diagnosis."""

    def _finding(self, sbom: tuple[Path, str]):
        sbom_file, sha256 = sbom
        plugin = SBOMVerificationPlugin()
        session = MagicMock()
        session.get.return_value = _response(500)

        with (
            patch("sbomify.apps.plugins.builtins.verification.get_http_session", return_value=session),
            patch.object(plugin, "_fetch_blob", return_value=None),
        ):
            result = plugin.assess("sbom-1", sbom_file, context=SBOMContext(sha256_hash=sha256))
        return next(f for f in result.findings if f.id == "verification:github-attestation")

    def test_the_digest_is_in_the_description(self, sbom) -> None:
        _, sha256 = sbom

        assert f"sha256:{sha256}" in self._finding(sbom).description

    def test_the_digest_is_machine_readable_in_metadata(self, sbom) -> None:
        """An operator comparing against ``gh attestation list`` should not have
        to scrape it out of prose."""
        _, sha256 = sbom

        assert self._finding(sbom).metadata["subject_digest"] == f"sha256:{sha256}"

    def test_the_underlying_error_is_still_reported(self, sbom) -> None:
        """The added diagnosis must not displace what GitHub actually said."""
        assert "500" in self._finding(sbom).metadata["error"]

    def test_it_does_not_blame_the_workflow_for_a_server_error(self, sbom) -> None:
        """This branch fires for every failed download — timeouts, 403 rate
        limits, 5xx, an unparseable body, even a local write error. Naming a
        subject-digest mismatch as the cause told operators whose attestation
        was fine to go and rewrite a correct workflow."""
        description = self._finding(sbom).description

        assert "500" in description
        assert description.index("GitHub's response") < description.index("If the attestation exists")

    def test_it_keeps_the_advice_for_repos_with_no_attest_step(self, sbom) -> None:
        """The one instruction that clears this finding for a repo that never
        set attestation up. Rewriting the text around a digest mismatch had
        dropped it, leaving those users with advice about a step they do not
        have."""
        assert "attest-build-provenance" in self._finding(sbom).description


def _cyclonedx_with_dependency_vcs(tmp_path: Path) -> tuple[Path, str]:
    """An SBOM whose own subject carries no VCS reference, so the lookup falls
    through to a dependency's repository."""
    import hashlib

    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "widget"}},
        "components": [
            {
                "type": "library",
                "name": "requests",
                "externalReferences": [{"type": "vcs", "url": "https://github.com/psf/requests"}],
            }
        ],
    }
    raw = json.dumps(doc).encode()
    path = tmp_path / "sbom.json"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


class TestItSaysWhereTheRepositoryCameFrom:
    """``_extract_vcs_info`` falls back to the first component carrying a VCS
    reference, which for a Python SBOM is typically an upstream OSS project.
    Naming it unqualified told the reader to go and fix a workflow in a
    repository they do not own."""

    def _finding_for(self, sbom_file: Path, sha256: str):
        plugin = SBOMVerificationPlugin()
        session = MagicMock()
        session.get.return_value = _response(500)

        with (
            patch("sbomify.apps.plugins.builtins.verification.get_http_session", return_value=session),
            patch.object(plugin, "_fetch_blob", return_value=None),
        ):
            result = plugin.assess("sbom-1", sbom_file, context=SBOMContext(sha256_hash=sha256))
        return next(f for f in result.findings if f.id == "verification:github-attestation")

    def test_a_dependency_repo_is_qualified(self, tmp_path: Path) -> None:
        finding = self._finding_for(*_cyclonedx_with_dependency_vcs(tmp_path))

        assert "psf/requests" in finding.description
        assert "from a package reference" in finding.description
        assert finding.metadata["vcs_source"] == "component"

    def test_the_documents_own_repo_is_not_qualified(self, sbom) -> None:
        """The common case must stay direct — hedging it would make every
        message read as uncertain."""
        finding = self._finding_for(*sbom)

        assert f"{ORG}/{REPO}" in finding.description
        assert "from a package reference" not in finding.description
        assert finding.metadata["vcs_source"] == "document"


class TestTheRetryMessageIsQualifiedToo:
    """The 404 path is the one users actually reach.

    It becomes the run's error after the retry budget is spent, so leaving it
    unqualified meant the dominant message still told a reader to go and fix a
    workflow in a dependency's repository — the exact harm the qualifier was
    added for, on the path that matters most.
    """

    def _raise_404_for(self, sbom_file: Path, sha256: str) -> str:
        plugin = SBOMVerificationPlugin()
        session = MagicMock()
        session.get.return_value = _response(404)

        with (
            patch("sbomify.apps.plugins.builtins.verification.get_http_session", return_value=session),
            patch.object(plugin, "_fetch_blob", return_value=None),
            pytest.raises(AttestationNotYetAvailableError) as excinfo,
        ):
            plugin.assess("sbom-1", sbom_file, context=SBOMContext(sha256_hash=sha256))
        return str(excinfo.value)

    def test_a_dependency_repo_is_qualified(self, tmp_path: Path) -> None:
        message = self._raise_404_for(*_cyclonedx_with_dependency_vcs(tmp_path))

        assert "psf/requests" in message
        assert "from a package reference" in message

    def test_the_documents_own_repo_is_not(self, sbom) -> None:
        message = self._raise_404_for(*sbom)

        assert f"{ORG}/{REPO}" in message
        assert "from a package reference" not in message


class TestEveryFormatReportsItsSource:
    """A handler that forgets to tag its result must not be read as the
    document's own subject, which is the permissive answer."""

    def test_spdx_is_package_derived(self, tmp_path: Path) -> None:
        doc = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "packages": [{"name": "widget", "downloadLocation": "git+https://github.com/example-org/example-repo"}],
        }
        path = tmp_path / "s.spdx.json"
        path.write_text(json.dumps(doc))

        info = SBOMVerificationPlugin()._extract_vcs_info(json.loads(path.read_text()))

        assert info is not None
        assert info["source"] == "package"

    def test_a_cyclonedx_document_subject_is_not(self, tmp_path: Path) -> None:
        _, _sha = _cyclonedx_with_vcs(tmp_path)
        doc = json.loads((tmp_path / "sbom.json").read_text())

        info = SBOMVerificationPlugin()._extract_vcs_info(doc)

        assert info is not None
        assert info["source"] == "document"
