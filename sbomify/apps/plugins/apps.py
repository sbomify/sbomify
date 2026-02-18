"""Django app configuration for the plugins framework."""

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class PluginsConfig(AppConfig):
    """Configuration for the plugins app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.plugins"
    label = "plugins"

    def ready(self) -> None:
        """Connect to post_migrate signal to register built-in plugins."""
        from django.db.models.signals import post_migrate

        post_migrate.connect(self._on_post_migrate, sender=self)

        # Import signals to register them
        from . import signals  # noqa: F401

    def _on_post_migrate(self, **kwargs) -> None:
        """Register built-in plugins after migrations complete."""
        self._register_builtin_plugins()

    def _register_builtin_plugins(self) -> None:
        """Register all built-in plugins."""
        from django.db.utils import OperationalError, ProgrammingError

        from .models import RegisteredPlugin

        try:
            # NTIA Minimum Elements 2021 Plugin
            RegisteredPlugin.objects.update_or_create(
                name="ntia-minimum-elements-2021",
                defaults={
                    "display_name": "NTIA Minimum Elements (2021)",
                    "description": (
                        "Validates SBOMs against the NTIA Minimum Elements for a Software Bill "
                        "of Materials as defined in the July 2021 report. Checks for: Supplier Name, "
                        "Component Name, Version, Unique Identifiers, Dependency Relationship, "
                        "SBOM Author, and Timestamp."
                    ),
                    "category": "compliance",
                    "version": "0.1.0",
                    "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
                    "is_enabled": True,
                    "is_beta": True,
                    "default_config": {},
                },
            )

            # FDA Medical Device Cybersecurity 2025 Plugin
            RegisteredPlugin.objects.update_or_create(
                name="fda-medical-device-2025",
                defaults={
                    "display_name": "FDA Medical Device Cybersecurity (2025)",
                    "description": (
                        "Validates SBOMs against FDA guidance 'Cybersecurity in Medical Devices: "
                        "Quality System Considerations and Content of Premarket Submissions' (June 2025). "
                        "Checks for all NTIA minimum elements plus CLE (Component Lifecycle Enumeration) "
                        "data including software support status and end-of-support dates for each component."
                    ),
                    "category": "compliance",
                    "version": "0.1.0",
                    "plugin_class_path": (
                        "sbomify.apps.plugins.builtins.fda_medical_device_cybersecurity.FDAMedicalDevicePlugin"
                    ),
                    "is_enabled": True,
                    "is_beta": True,
                    "default_config": {},
                },
            )

            # BSI TR-03183-2 v2.1 SBOM Compliance Plugin (EU Cyber Resilience Act)
            RegisteredPlugin.objects.update_or_create(
                name="bsi-tr03183-v2.1-compliance",
                defaults={
                    "display_name": "BSI TR-03183-2 v2.1 (EU CRA SBOM)",
                    "description": (
                        "Validates SBOMs against BSI Technical Guideline TR-03183-2 v2.1.0 - the "
                        "authoritative technical standard for EU Cyber Resilience Act SBOM compliance. "
                        "Requires CycloneDX 1.6+ or SPDX 3.0.1+. Checks for: SBOM Creator, Timestamp, "
                        "Component Creator, Component Name/Version, Filename, Dependencies with Completeness, "
                        "Distribution Licences (SPDX), SHA-512 Hash, Executable/Archive/Structured Properties. "
                        "For digital signature requirements, use in combination with attestation plugins."
                    ),
                    "category": "compliance",
                    "version": "1.0.0",
                    "plugin_class_path": "sbomify.apps.plugins.builtins.bsi.BSICompliancePlugin",
                    "is_enabled": True,
                    "is_beta": True,
                    "default_config": {},
                    "dependencies": {
                        "requires_one_of": [
                            {"type": "category", "value": "attestation"},
                        ],
                    },
                },
            )

            # GitHub Attestation Plugin
            RegisteredPlugin.objects.update_or_create(
                name="github-attestation",
                defaults={
                    "display_name": "GitHub Attestation",
                    "description": (
                        "Verifies SBOM attestations using GitHub's Sigstore integration. "
                        "Extracts VCS information from the SBOM's externalReferences and runs "
                        "cosign verify-attestation to verify that the associated artifact has "
                        "a valid GitHub attestation with SLSA provenance."
                    ),
                    "category": "attestation",
                    "version": "1.0.0",
                    "plugin_class_path": ("sbomify.apps.plugins.builtins.github_attestation.GitHubAttestationPlugin"),
                    "is_enabled": True,
                    "is_beta": True,
                    "default_config": {
                        "certificate_oidc_issuer": "https://token.actions.githubusercontent.com",
                        "attestation_type": "https://slsa.dev/provenance/v1",
                        "timeout": 60,
                    },
                },
            )

            # OSV Vulnerability Scanner Plugin
            RegisteredPlugin.objects.update_or_create(
                name="osv",
                defaults={
                    "display_name": "OSV Vulnerability Scanner",
                    "description": (
                        "Scans SBOMs for known vulnerabilities using the OSV (Open Source "
                        "Vulnerabilities) database via the osv-scanner binary. Supports both "
                        "CycloneDX and SPDX formats. Returns vulnerability findings with "
                        "severity levels, CVSS scores, references, and affected component details."
                    ),
                    "category": "security",
                    "version": "1.0.0",
                    "plugin_class_path": "sbomify.apps.plugins.builtins.osv.OSVPlugin",
                    "is_enabled": True,
                    "is_beta": True,
                    "default_config": {
                        "timeout": 300,
                        "scanner_path": "/usr/local/bin/osv-scanner",
                    },
                },
            )
        except (OperationalError, ProgrammingError) as e:
            # Table doesn't exist yet (e.g., during initial migrations)
            logger.debug("Could not register built-in plugins (table may not exist yet): %s", e)
