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
        """Register all built-in plugins.

        Each plugin is registered in its own atomic block so that a failure in
        one (e.g. a missing column before a migration is applied) does not
        prevent the remaining plugins from being registered.
        """
        from django.db import transaction
        from django.db.utils import OperationalError, ProgrammingError

        from .models import RegisteredPlugin

        def _is_missing_schema_error(exc: BaseException) -> bool:
            """Detect 'missing table/column' errors to avoid masking real bugs."""
            message = str(exc).lower()
            missing_indicators = (
                "no such table",
                "no such column",
                "does not exist",
                "undefined table",
                "undefined column",
            )
            return any(indicator in message for indicator in missing_indicators)

        def _register(name: str, defaults: dict) -> None:
            try:
                with transaction.atomic():
                    RegisteredPlugin.objects.update_or_create(name=name, defaults=defaults)
            except OperationalError as e:
                logger.debug("Could not register plugin '%s' (table/column may not exist yet): %s", name, e)
            except ProgrammingError as e:
                if _is_missing_schema_error(e):
                    logger.debug("Could not register plugin '%s' (table/column may not exist yet): %s", name, e)
                else:
                    logger.exception("Unexpected error while registering plugin '%s'", name)
                    raise

        # NTIA Minimum Elements 2021 Plugin
        _register(
            "ntia-minimum-elements-2021",
            {
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
        _register(
            "fda-medical-device-2025",
            {
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
        _register(
            "bsi-tr03183-v2.1-compliance",
            {
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
        _register(
            "github-attestation",
            {
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
        from .builtins.osv import OSVPlugin

        _register(
            "osv",
            {
                "display_name": "OSV Vulnerability Scanner",
                "description": (
                    "Scans SBOMs for known vulnerabilities using the OSV (Open Source "
                    "Vulnerabilities) database via the osv-scanner binary. Supports both "
                    "CycloneDX and SPDX formats. Returns vulnerability findings with "
                    "severity levels, CVSS scores, references, and affected component details."
                ),
                "category": "security",
                "version": OSVPlugin.VERSION,
                "plugin_class_path": "sbomify.apps.plugins.builtins.osv.OSVPlugin",
                "is_enabled": True,
                "is_beta": True,
                "default_config": {
                    "timeout": OSVPlugin.DEFAULT_TIMEOUT,
                    "scanner_path": OSVPlugin.DEFAULT_SCANNER_PATH,
                },
            },
        )

        # Dependency Track Vulnerability Scanner Plugin
        from .builtins.dependency_track import DependencyTrackPlugin

        _register(
            "dependency-track",
            {
                "display_name": "Dependency Track",
                "description": (
                    "Scans CycloneDX SBOMs for vulnerabilities using Dependency Track. "
                    "Uploads SBOMs to a DT server for comprehensive vulnerability analysis "
                    "including CVSS scores, component-level findings, and continuous monitoring. "
                    "Available for Business and Enterprise plans only. "
                    "Does not support SPDX format."
                ),
                "category": "security",
                "version": DependencyTrackPlugin.VERSION,
                "plugin_class_path": ("sbomify.apps.plugins.builtins.dependency_track.DependencyTrackPlugin"),
                "is_enabled": True,
                "is_beta": True,
                "default_config": {},
                "config_schema": [
                    {
                        "key": "dt_server_id",
                        "label": "Dependency Track Server",
                        "type": "select",
                        "required": False,
                        "help_text": "Select a Dependency Track server. Leave blank to use the default.",
                        "choices_source": "dt_servers",
                        "hide_if_no_choices": True,
                    },
                ],
            },
        )
