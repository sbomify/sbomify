"""Tests for the GitHub Attestation plugin."""

import json
from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.plugins.builtins.github_attestation import (
    GitHubAttestationError,
    GitHubAttestationPlugin,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory


class TestGitHubAttestationPluginMetadata:
    """Tests for plugin metadata."""

    def test_get_metadata(self):
        """Test plugin returns correct metadata."""
        plugin = GitHubAttestationPlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "github-attestation"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.ATTESTATION

    def test_default_config(self):
        """Test plugin has correct default configuration."""
        plugin = GitHubAttestationPlugin()

        assert plugin.certificate_oidc_issuer == "https://token.actions.githubusercontent.com"
        assert plugin.timeout == 60

    def test_custom_config(self):
        """Test plugin accepts custom configuration."""
        custom_config = {
            "certificate_oidc_issuer": "https://custom.issuer.com",
            "certificate_identity_regexp": "^https://github.com/custom/.*",
            "timeout": 120,
        }
        plugin = GitHubAttestationPlugin(config=custom_config)

        assert plugin.certificate_oidc_issuer == "https://custom.issuer.com"
        assert plugin.timeout == 120


class TestVCSInfoExtraction:
    """Tests for VCS information extraction from SBOMs."""

    def test_extract_vcs_from_metadata_component(self):
        """Test extracting VCS info from metadata.component.externalReferences."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "externalReferences": [{"type": "vcs", "url": "https://github.com/sbomify/sbomify"}],
                }
            },
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is not None
        assert result["org"] == "sbomify"
        assert result["repo"] == "sbomify"

    def test_extract_vcs_from_top_level(self):
        """Test extracting VCS info from top-level externalReferences."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "externalReferences": [{"type": "vcs", "url": "https://github.com/myorg/myrepo"}],
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is not None
        assert result["org"] == "myorg"
        assert result["repo"] == "myrepo"

    def test_extract_vcs_from_components(self):
        """Test extracting VCS info from components array."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "components": [
                {
                    "name": "dependency",
                    "externalReferences": [{"type": "vcs", "url": "https://github.com/dep-org/dep-repo"}],
                }
            ],
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is not None
        assert result["org"] == "dep-org"
        assert result["repo"] == "dep-repo"

    def test_extract_vcs_no_github_url(self):
        """Test returns None when no GitHub URL is found."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "externalReferences": [{"type": "vcs", "url": "https://gitlab.com/org/repo"}],
                }
            },
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is None

    def test_extract_vcs_no_external_references(self):
        """Test returns None when no externalReferences exist."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {"component": {"name": "test-app"}},
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is None

    def test_extract_vcs_with_git_reference_type(self):
        """Test extracting VCS info when external reference type is 'git'."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "externalReferences": [{"type": "git", "url": "https://github.com/test-org/test-repo"}],
                }
            },
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is not None
        assert result["org"] == "test-org"
        assert result["repo"] == "test-repo"


class TestSPDXVCSInfoExtraction:
    """Tests for VCS info extraction from SPDX format."""

    def test_extract_vcs_from_download_location(self):
        """Test extracting VCS info from SPDX downloadLocation."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "packages": [
                {
                    "name": "test-app",
                    "downloadLocation": "git+https://github.com/sbomify/sbomify@abc123def456",
                }
            ],
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is not None
        assert result["org"] == "sbomify"
        assert result["repo"] == "sbomify"

    def test_extract_vcs_from_external_refs(self):
        """Test extracting VCS info from SPDX externalRefs."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "test-app",
                    "downloadLocation": "NOASSERTION",
                    "externalRefs": [
                        {
                            "referenceCategory": "OTHER",
                            "referenceType": "vcs",
                            "referenceLocator": "https://github.com/test-org/test-repo",
                        }
                    ],
                }
            ],
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is not None
        assert result["org"] == "test-org"
        assert result["repo"] == "test-repo"

    def test_spdx_no_packages(self):
        """Test returns None when SPDX has no packages."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [],
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is None

    def test_spdx_no_github_url(self):
        """Test returns None when SPDX has no GitHub URL."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "test-app",
                    "downloadLocation": "git+https://gitlab.com/org/repo@abc123",
                }
            ],
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is None


class TestGitHubURLParsing:
    """Tests for GitHub URL parsing."""

    def test_parse_https_url(self):
        """Test parsing standard HTTPS GitHub URL."""
        plugin = GitHubAttestationPlugin()

        result = plugin._parse_github_url("https://github.com/sbomify/sbomify")

        assert result == {"org": "sbomify", "repo": "sbomify"}

    def test_parse_https_url_with_git_extension(self):
        """Test parsing HTTPS URL with .git extension."""
        plugin = GitHubAttestationPlugin()

        result = plugin._parse_github_url("https://github.com/org/repo.git")

        assert result == {"org": "org", "repo": "repo"}

    def test_parse_ssh_url(self):
        """Test parsing SSH GitHub URL."""
        plugin = GitHubAttestationPlugin()

        result = plugin._parse_github_url("git@github.com:sbomify/sbomify.git")

        assert result == {"org": "sbomify", "repo": "sbomify"}

    def test_parse_url_with_extra_path(self):
        """Test parsing URL with extra path segments."""
        plugin = GitHubAttestationPlugin()

        result = plugin._parse_github_url("https://github.com/org/repo/tree/main/src")

        assert result == {"org": "org", "repo": "repo"}

    def test_parse_non_github_url(self):
        """Test returns None for non-GitHub URL."""
        plugin = GitHubAttestationPlugin()

        result = plugin._parse_github_url("https://gitlab.com/org/repo")

        assert result is None

    def test_parse_invalid_url(self):
        """Test returns None for invalid URL."""
        plugin = GitHubAttestationPlugin()

        result = plugin._parse_github_url("not-a-url")

        assert result is None


class TestFileDigestCalculation:
    """Tests for _calculate_file_digest method."""

    def test_calculate_digest_simple_content(self, tmp_path):
        """Test SHA256 digest calculation for simple content."""
        import hashlib

        plugin = GitHubAttestationPlugin()
        test_file = tmp_path / "test.txt"
        content = b"Hello, World!"
        test_file.write_bytes(content)

        result = plugin._calculate_file_digest(test_file)

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_calculate_digest_json_content(self, tmp_path):
        """Test SHA256 digest calculation for JSON content."""
        import hashlib

        plugin = GitHubAttestationPlugin()
        test_file = tmp_path / "sbom.json"
        content = b'{"bomFormat": "CycloneDX", "specVersion": "1.4"}'
        test_file.write_bytes(content)

        result = plugin._calculate_file_digest(test_file)

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_calculate_digest_empty_file(self, tmp_path):
        """Test SHA256 digest calculation for empty file."""
        import hashlib

        plugin = GitHubAttestationPlugin()
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        result = plugin._calculate_file_digest(test_file)

        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected

    def test_calculate_digest_large_file(self, tmp_path):
        """Test SHA256 digest calculation for file larger than chunk size."""
        import hashlib

        plugin = GitHubAttestationPlugin()
        test_file = tmp_path / "large.bin"
        # Create content larger than SBOM_FILE_READ_CHUNK_SIZE (8192 bytes)
        content = b"x" * 20000
        test_file.write_bytes(content)

        result = plugin._calculate_file_digest(test_file)

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_calculate_digest_deterministic(self, tmp_path):
        """Test that digest calculation is deterministic."""
        plugin = GitHubAttestationPlugin()
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"consistent content")

        result1 = plugin._calculate_file_digest(test_file)
        result2 = plugin._calculate_file_digest(test_file)

        assert result1 == result2

    def test_calculate_digest_different_content_different_hash(self, tmp_path):
        """Test that different content produces different digests."""
        plugin = GitHubAttestationPlugin()
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_bytes(b"content one")
        file2.write_bytes(b"content two")

        digest1 = plugin._calculate_file_digest(file1)
        digest2 = plugin._calculate_file_digest(file2)

        assert digest1 != digest2


class TestAttestationBundleDownload:
    """Tests for attestation bundle download from GitHub API."""

    @patch("sbomify.apps.plugins.builtins.github_attestation.get_http_session")
    def test_bundle_download_success(self, mock_get_session, tmp_path):
        """Test successful attestation bundle download."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "attestations": [
                {
                    "bundle": {
                        "mediaType": "application/vnd.dev.sigstore.bundle+json",
                        "verificationMaterial": {},
                        "dsseEnvelope": {},
                    }
                }
            ]
        }
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_text('{"test": "data"}')

        result = plugin._download_attestation_bundle(
            sbom_path=sbom_path,
            github_org="sbomify",
            github_repo="sbomify",
        )

        assert result["success"] is True
        assert "bundle_path" in result

        # Verify API was called with correct URL pattern
        mock_session.get.assert_called_once()
        call_url = mock_session.get.call_args[0][0]
        assert "api.github.com/repos/sbomify/sbomify/attestations/sha256:" in call_url

    @patch("sbomify.apps.plugins.builtins.github_attestation.get_http_session")
    def test_bundle_download_not_found(self, mock_get_session, tmp_path):
        """Test when no attestation is found."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_text('{"test": "data"}')

        result = plugin._download_attestation_bundle(
            sbom_path=sbom_path,
            github_org="org",
            github_repo="repo",
        )

        assert result["success"] is False
        assert "No attestation found" in result["error"]

    @patch("sbomify.apps.plugins.builtins.github_attestation.get_http_session")
    def test_bundle_download_api_error(self, mock_get_session, tmp_path):
        """Test GitHub API error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_text('{"test": "data"}')

        result = plugin._download_attestation_bundle(
            sbom_path=sbom_path,
            github_org="org",
            github_repo="repo",
        )

        assert result["success"] is False
        assert "GitHub API error" in result["error"]

    @patch("sbomify.apps.plugins.builtins.github_attestation.get_http_session")
    def test_bundle_download_timeout(self, mock_get_session, tmp_path):
        """Test attestation bundle download timeout."""
        import requests

        mock_session = MagicMock()
        mock_session.get.side_effect = requests.Timeout()
        mock_get_session.return_value = mock_session

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_text('{"test": "data"}')

        result = plugin._download_attestation_bundle(
            sbom_path=sbom_path,
            github_org="org",
            github_repo="repo",
        )

        assert result["success"] is False
        assert "timed out" in result["error"].lower()


class TestCosignVerification:
    """Tests for cosign attestation verification."""

    @patch("shutil.which")
    def test_cosign_not_found(self, mock_which):
        """Test error when cosign is not installed."""
        mock_which.return_value = None
        plugin = GitHubAttestationPlugin()

        with pytest.raises(GitHubAttestationError) as exc_info:
            plugin._verify_attestation(
                sbom_path=Path("/tmp/sbom.json"),
                bundle_path=Path("/tmp/bundle.jsonl"),
                certificate_identity_regexp="^https://github.com/org/.*",
            )

        assert "cosign binary not found" in str(exc_info.value)

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_verification_success(self, mock_run, mock_which):
        """Test successful attestation verification."""
        mock_which.return_value = "/usr/local/bin/cosign"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Verification successful",
            stderr="",
        )
        plugin = GitHubAttestationPlugin()

        result = plugin._verify_attestation(
            sbom_path=Path("/tmp/sbom.json"),
            bundle_path=Path("/tmp/bundle.jsonl"),
            certificate_identity_regexp="^https://github.com/org/.*",
        )

        assert result["verified"] is True
        assert "successfully" in result["message"].lower()

        # Verify cosign was called with correct arguments
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "verify-blob-attestation" in call_args
        assert "--bundle" in call_args
        assert "/tmp/bundle.jsonl" in call_args
        assert "/tmp/sbom.json" in call_args

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_verification_failure(self, mock_run, mock_which):
        """Test failed attestation verification."""
        mock_which.return_value = "/usr/local/bin/cosign"
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="no matching attestations",
        )
        plugin = GitHubAttestationPlugin()

        result = plugin._verify_attestation(
            sbom_path=Path("/tmp/sbom.json"),
            bundle_path=Path("/tmp/bundle.jsonl"),
            certificate_identity_regexp="^https://github.com/org/.*",
        )

        assert result["verified"] is False
        assert "no matching attestations" in result["message"]

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_verification_timeout(self, mock_run, mock_which):
        """Test handling of cosign timeout."""
        mock_which.return_value = "/usr/local/bin/cosign"
        mock_run.side_effect = TimeoutExpired(cmd="cosign", timeout=60)
        plugin = GitHubAttestationPlugin()

        result = plugin._verify_attestation(
            sbom_path=Path("/tmp/sbom.json"),
            bundle_path=Path("/tmp/bundle.jsonl"),
            certificate_identity_regexp="^https://github.com/org/.*",
        )

        assert result["verified"] is False
        assert "timed out" in result["message"].lower()


class TestAssessMethod:
    """Tests for the main assess() method."""

    def test_assess_no_vcs_info(self, tmp_path):
        """Test assessment when SBOM has no VCS information."""
        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {"component": {"name": "test-app"}},
        }
        sbom_path.write_text(json.dumps(sbom_data))

        result = plugin.assess("sbom123", sbom_path)

        assert result.plugin_name == "github-attestation"
        assert result.category == "attestation"
        assert result.summary.warning_count == 1
        assert result.findings[0].id == "github-attestation:no-vcs"

    @patch("sbomify.apps.plugins.builtins.github_attestation.get_http_session")
    def test_assess_no_attestation_found(self, mock_get_session, tmp_path):
        """Test assessment when no attestation is found on GitHub."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "externalReferences": [{"type": "vcs", "url": "https://github.com/org/repo"}],
                }
            },
        }
        sbom_path.write_text(json.dumps(sbom_data))

        result = plugin.assess("sbom123", sbom_path)

        assert result.summary.fail_count == 1
        assert result.findings[0].id == "github-attestation:no-attestation"

    @patch("shutil.which")
    @patch("subprocess.run")
    @patch("sbomify.apps.plugins.builtins.github_attestation.get_http_session")
    def test_assess_verification_pass(self, mock_get_session, mock_run, mock_which, tmp_path):
        """Test full assessment with passing verification."""
        # Mock GitHub API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"attestations": [{"bundle": {"test": "bundle"}}]}
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        # Mock cosign
        mock_which.return_value = "/usr/local/bin/cosign"
        mock_run.return_value = MagicMock(returncode=0, stdout="Verified", stderr="")

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "externalReferences": [{"type": "vcs", "url": "https://github.com/sbomify/sbomify"}],
                }
            },
        }
        sbom_path.write_text(json.dumps(sbom_data))

        result = plugin.assess("sbom123", sbom_path)

        assert result.summary.pass_count == 1
        assert result.summary.fail_count == 0
        assert result.findings[0].id == "github-attestation:verified"
        assert result.findings[0].status == "pass"

    @patch("shutil.which")
    @patch("subprocess.run")
    @patch("sbomify.apps.plugins.builtins.github_attestation.get_http_session")
    def test_assess_verification_fail(self, mock_get_session, mock_run, mock_which, tmp_path):
        """Test full assessment with failing verification."""
        # Mock GitHub API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"attestations": [{"bundle": {"test": "bundle"}}]}
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        # Mock cosign failure
        mock_which.return_value = "/usr/local/bin/cosign"
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="signature mismatch")

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "externalReferences": [{"type": "vcs", "url": "https://github.com/sbomify/sbomify"}],
                }
            },
        }
        sbom_path.write_text(json.dumps(sbom_data))

        result = plugin.assess("sbom123", sbom_path)

        assert result.summary.pass_count == 0
        assert result.summary.fail_count == 1
        assert result.findings[0].id == "github-attestation:failed"
        assert result.findings[0].status == "fail"

    def test_assess_invalid_json(self, tmp_path):
        """Test assessment with invalid JSON SBOM."""
        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_path.write_text("not valid json")

        result = plugin.assess("sbom123", sbom_path)

        assert result.summary.error_count == 1
        assert result.findings[0].id == "github-attestation:error"


class TestResultCreation:
    """Tests for result creation methods."""

    def test_create_result_pass(self, tmp_path):
        """Test creating pass result."""
        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"

        result = plugin._create_result(
            sbom_id="sbom123",
            verification_result={
                "verified": True,
                "message": "Success",
                "details": {},
            },
            github_org="org",
            github_repo="repo",
            sbom_path=sbom_path,
        )

        assert result.summary.pass_count == 1
        assert result.findings[0].status == "pass"
        assert result.findings[0].metadata["github_org"] == "org"
        assert result.findings[0].metadata["sbom_file"] == str(sbom_path)

    def test_create_result_fail(self, tmp_path):
        """Test creating fail result."""
        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"

        result = plugin._create_result(
            sbom_id="sbom123",
            verification_result={
                "verified": False,
                "message": "Verification failed",
                "details": {"error": "no attestation"},
            },
            github_org="org",
            github_repo="repo",
            sbom_path=sbom_path,
        )

        assert result.summary.fail_count == 1
        assert result.findings[0].status == "fail"
        assert result.findings[0].severity == "high"

    def test_create_result_error(self):
        """Test creating error result."""
        plugin = GitHubAttestationPlugin()

        result = plugin._create_result_error("sbom123", "Something went wrong")

        assert result.summary.error_count == 1
        assert result.findings[0].id == "github-attestation:error"
        assert "Something went wrong" in result.findings[0].description

    def test_create_result_no_attestation(self):
        """Test creating no attestation result."""
        plugin = GitHubAttestationPlugin()

        result = plugin._create_result_no_attestation(
            sbom_id="sbom123",
            github_org="org",
            github_repo="repo",
            error="no attestations found",
        )

        assert result.summary.fail_count == 1
        assert result.findings[0].id == "github-attestation:no-attestation"
        assert "no attestations found" in result.findings[0].description


@pytest.mark.django_db
class TestPluginIntegration:
    """Integration tests for the plugin with the framework."""

    def test_registered_plugin_loads_correctly(self, db):
        """Test that the plugin can be loaded via the orchestrator."""
        from sbomify.apps.plugins.models import RegisteredPlugin
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator

        # Register the plugin (use update_or_create since apps.py may have already registered it)
        RegisteredPlugin.objects.update_or_create(
            name="github-attestation",
            defaults={
                "display_name": "GitHub Attestation",
                "description": "Verifies GitHub attestations",
                "category": "attestation",
                "version": "1.0.0",
                "plugin_class_path": "sbomify.apps.plugins.builtins.github_attestation.GitHubAttestationPlugin",
                "is_enabled": True,
            },
        )

        # Load via orchestrator
        orchestrator = PluginOrchestrator()
        plugin = orchestrator.get_plugin_instance("github-attestation")

        assert isinstance(plugin, GitHubAttestationPlugin)
        assert plugin.get_metadata().name == "github-attestation"
