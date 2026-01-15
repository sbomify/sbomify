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

        assert (
            plugin.certificate_oidc_issuer == "https://token.actions.githubusercontent.com"
        )
        assert plugin.attestation_type == "https://slsa.dev/provenance/v1"

    def test_custom_config(self):
        """Test plugin accepts custom configuration."""
        custom_config = {
            "certificate_oidc_issuer": "https://custom.issuer.com",
            "attestation_type": "https://custom.type/v1",
            "certificate_identity_regexp": "^https://github.com/custom/.*",
        }
        plugin = GitHubAttestationPlugin(config=custom_config)

        assert plugin.certificate_oidc_issuer == "https://custom.issuer.com"
        assert plugin.attestation_type == "https://custom.type/v1"


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
                    "externalReferences": [
                        {"type": "vcs", "url": "https://github.com/sbomify/sbomify"}
                    ],
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
            "externalReferences": [
                {"type": "vcs", "url": "https://github.com/myorg/myrepo"}
            ],
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
                    "externalReferences": [
                        {"type": "vcs", "url": "https://github.com/dep-org/dep-repo"}
                    ],
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
                    "externalReferences": [
                        {"type": "vcs", "url": "https://gitlab.com/org/repo"}
                    ],
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

    def test_extract_vcs_with_pedigree_commit(self):
        """Test extracting commit SHA from CycloneDX pedigree."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "externalReferences": [
                        {"type": "vcs", "url": "https://github.com/test-org/test-repo"}
                    ],
                    "pedigree": {
                        "commits": [
                            {"uid": "abc123def456789", "url": "https://github.com/test-org/test-repo/commit/abc123def456789"}
                        ]
                    },
                }
            },
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is not None
        assert result["org"] == "test-org"
        assert result["repo"] == "test-repo"
        assert result["commit_sha"] == "abc123def456789"


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
        assert result["commit_sha"] == "abc123def456"

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
                            "comment": "Source repository (commit: abc1234)",
                        }
                    ],
                }
            ],
        }

        result = plugin._extract_vcs_info(sbom_data)

        assert result is not None
        assert result["org"] == "test-org"
        assert result["repo"] == "test-repo"
        assert result["commit_sha"] == "abc1234"

    def test_extract_vcs_from_source_info(self):
        """Test extracting commit SHA from SPDX sourceInfo."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "test-app",
                    "downloadLocation": "NOASSERTION",
                    "sourceInfo": "Built from commit abc123def on main",
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
        assert result["commit_sha"] == "abc123def"

    def test_extract_vcs_from_creator_comment(self):
        """Test extracting commit SHA from SPDX creatorComment."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "creationInfo": {
                "creatorComment": "Built from https://github.com/test-org/test-repo at abc1234",
            },
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
        assert result["commit_sha"] == "abc1234"

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

        result = plugin._parse_github_url(
            "https://github.com/org/repo/tree/main/src"
        )

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


class TestAttestationTargetExtraction:
    """Tests for attestation target extraction."""

    def test_extract_oci_purl(self):
        """Test extracting attestation target from OCI purl."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "metadata": {
                "component": {
                    "name": "my-image",
                    "purl": "pkg:oci/my-image@sha256:abc123def456",
                }
            }
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result == "my-image@sha256:abc123def456"

    def test_extract_docker_purl(self):
        """Test extracting attestation target from Docker purl."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "metadata": {
                "component": {
                    "name": "my-image",
                    "purl": "pkg:docker/library/nginx@sha256:abc123",
                }
            }
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result == "library/nginx@sha256:abc123"

    def test_extract_from_distribution_url(self):
        """Test extracting from distribution external reference."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "metadata": {
                "component": {
                    "name": "my-image",
                    "externalReferences": [
                        {
                            "type": "distribution",
                            "url": "ghcr.io/sbomify/sbomify@sha256:abc123",
                        }
                    ],
                }
            }
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result == "ghcr.io/sbomify/sbomify@sha256:abc123"

    def test_extract_from_hash_and_name(self):
        """Test extracting from component name and hash."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "metadata": {
                "component": {
                    "name": "ghcr.io/org/image",
                    "hashes": [{"alg": "SHA-256", "content": "abc123def456"}],
                }
            }
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result == "ghcr.io/org/image@sha256:abc123def456"

    def test_extract_no_target_found(self):
        """Test returns None when no attestation target is found."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "metadata": {
                "component": {
                    "name": "simple-library",
                    "version": "1.0.0",
                }
            }
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result is None


class TestSPDXAttestationTargetExtraction:
    """Tests for attestation target extraction from SPDX format."""

    def test_extract_target_from_purl_external_ref(self):
        """Test extracting attestation target from SPDX externalRefs purl."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "test-app",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:oci/ghcr.io/sbomify/sbomify@sha256:abc123",
                        }
                    ],
                }
            ],
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result == "ghcr.io/sbomify/sbomify@sha256:abc123"

    def test_extract_target_from_download_location(self):
        """Test extracting attestation target from SPDX downloadLocation."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "test-app",
                    "downloadLocation": "ghcr.io/org/image@sha256:abc123def456",
                }
            ],
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result == "ghcr.io/org/image@sha256:abc123def456"

    def test_extract_target_from_package_name_with_checksum(self):
        """Test extracting attestation target from package name and checksum."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "ghcr.io/org/image",
                    "downloadLocation": "NOASSERTION",
                    "checksums": [
                        {"algorithm": "SHA256", "checksumValue": "abc123def456"}
                    ],
                }
            ],
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result == "ghcr.io/org/image@sha256:abc123def456"

    def test_extract_target_from_package_name_only(self):
        """Test extracting attestation target from package name when it looks like a container image."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "docker.io/library/nginx",
                    "downloadLocation": "NOASSERTION",
                }
            ],
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result == "docker.io/library/nginx"

    def test_spdx_no_target_found(self):
        """Test returns None when no attestation target in SPDX."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "simple-library",
                    "downloadLocation": "NOASSERTION",
                }
            ],
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result is None

    def test_spdx_ignores_git_download_location(self):
        """Test that git+ download locations are not treated as attestation targets."""
        plugin = GitHubAttestationPlugin()
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "test-app",
                    "downloadLocation": "git+https://github.com/org/repo@abc123",
                }
            ],
        }

        result = plugin._extract_attestation_target(sbom_data)

        assert result is None


class TestContainerImageURLDetection:
    """Tests for container image URL detection."""

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("ghcr.io/org/repo", True),
            ("docker.io/library/nginx", True),
            ("gcr.io/project/image", True),
            ("quay.io/org/image", True),
            ("123456789.dkr.ecr.us-east-1.amazonaws.com/repo", True),
            ("myregistry.azurecr.io/image", True),
            ("https://example.com/file.zip", False),
            ("npm:package@1.0.0", False),
        ],
    )
    def test_is_container_image_url(self, url, expected):
        """Test container image URL detection."""
        plugin = GitHubAttestationPlugin()

        result = plugin._is_container_image_url(url)

        assert result == expected


class TestCosignVerification:
    """Tests for cosign attestation verification."""

    @patch("shutil.which")
    def test_cosign_not_found(self, mock_which):
        """Test error when cosign is not installed."""
        mock_which.return_value = None
        plugin = GitHubAttestationPlugin()

        with pytest.raises(GitHubAttestationError) as exc_info:
            plugin._verify_attestation(
                attestation_target="ghcr.io/org/repo@sha256:abc",
                certificate_identity_regexp="^https://github.com/org/.*",
                github_org="org",
                github_repo="repo",
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
            attestation_target="ghcr.io/org/repo@sha256:abc",
            certificate_identity_regexp="^https://github.com/org/.*",
            github_org="org",
            github_repo="repo",
        )

        assert result["verified"] is True
        assert "successfully" in result["message"].lower()

        # Verify cosign was called with correct arguments
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "verify-attestation" in call_args
        assert "--type" in call_args
        assert "ghcr.io/org/repo@sha256:abc" in call_args

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
            attestation_target="ghcr.io/org/repo@sha256:abc",
            certificate_identity_regexp="^https://github.com/org/.*",
            github_org="org",
            github_repo="repo",
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
            attestation_target="ghcr.io/org/repo@sha256:abc",
            certificate_identity_regexp="^https://github.com/org/.*",
            github_org="org",
            github_repo="repo",
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

    def test_assess_no_attestation_target(self, tmp_path):
        """Test assessment when SBOM has no attestation target."""
        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "externalReferences": [
                        {"type": "vcs", "url": "https://github.com/org/repo"}
                    ],
                }
            },
        }
        sbom_path.write_text(json.dumps(sbom_data))

        result = plugin.assess("sbom123", sbom_path)

        assert result.summary.warning_count == 1
        assert result.findings[0].id == "github-attestation:no-target"

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_assess_verification_pass(self, mock_run, mock_which, tmp_path):
        """Test full assessment with passing verification."""
        mock_which.return_value = "/usr/local/bin/cosign"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Verified",
            stderr="",
        )

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "purl": "pkg:oci/ghcr.io/sbomify/sbomify@sha256:abc123",
                    "externalReferences": [
                        {"type": "vcs", "url": "https://github.com/sbomify/sbomify"}
                    ],
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
    def test_assess_verification_fail(self, mock_run, mock_which, tmp_path):
        """Test full assessment with failing verification."""
        mock_which.return_value = "/usr/local/bin/cosign"
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="attestation not found",
        )

        plugin = GitHubAttestationPlugin()
        sbom_path = tmp_path / "sbom.json"
        sbom_data = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": "test-app",
                    "purl": "pkg:oci/ghcr.io/sbomify/sbomify@sha256:abc123",
                    "externalReferences": [
                        {"type": "vcs", "url": "https://github.com/sbomify/sbomify"}
                    ],
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

    def test_create_result_pass(self):
        """Test creating pass result."""
        plugin = GitHubAttestationPlugin()

        result = plugin._create_result(
            sbom_id="sbom123",
            verification_result={
                "verified": True,
                "message": "Success",
                "details": {},
            },
            github_org="org",
            github_repo="repo",
            attestation_target="ghcr.io/org/repo@sha256:abc",
        )

        assert result.summary.pass_count == 1
        assert result.findings[0].status == "pass"
        assert result.findings[0].metadata["github_org"] == "org"

    def test_create_result_fail(self):
        """Test creating fail result."""
        plugin = GitHubAttestationPlugin()

        result = plugin._create_result(
            sbom_id="sbom123",
            verification_result={
                "verified": False,
                "message": "Verification failed",
                "details": {"error": "no attestation"},
            },
            github_org="org",
            github_repo="repo",
            attestation_target="ghcr.io/org/repo@sha256:abc",
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
