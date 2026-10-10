"""Django app configuration for the plugins framework."""

import logging
from typing import Any

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

    def _on_post_migrate(self, **kwargs: Any) -> None:
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

        # Name, category, version and class path come from the class itself: the
        # registry's version is what a stored run is compared against to tell
        # whether its result is out of date.
        from .builtins.bsi import BSICompliancePlugin
        from .builtins.bsi_tr02102 import BsiTr02102Plugin
        from .builtins.cert_lifecycle import CertificateLifecyclePlugin
        from .builtins.cisa_2025 import CISA2025MinimumElementsPlugin
        from .builtins.cisa_2026 import CISAMinimumElementsPlugin
        from .builtins.cnsa2 import Cnsa2Plugin
        from .builtins.dependency_track import DependencyTrackPlugin
        from .builtins.fda_medical_device_cybersecurity import FDAMedicalDevicePlugin
        from .builtins.ntia import NTIAMinimumElementsPlugin
        from .builtins.openchain_telco import OpenChainTelcoPlugin
        from .builtins.osv import OSVPlugin
        from .builtins.pqc import PqcReadinessPlugin
        from .builtins.sp800_131a import Sp800131aPlugin
        from .builtins.verification import SBOMVerificationPlugin
        from .models import RegisteredPlugin
        from .sdk.base import AssessmentPlugin

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

        # (class, display name, description, registry fields beyond the defaults)
        builtins: list[tuple[type[AssessmentPlugin], str, str, dict[str, Any]]] = [
            (
                NTIAMinimumElementsPlugin,
                "NTIA Minimum Elements (2021)",
                (
                    "Validates SBOMs against the NTIA Minimum Elements for a Software Bill "
                    "of Materials as defined in the July 2021 report. Checks for: Supplier Name, "
                    "Component Name, Version, Unique Identifiers, Dependency Relationship, "
                    "SBOM Author, and Timestamp."
                ),
                {},
            ),
            (
                CISAMinimumElementsPlugin,
                "CISA Minimum Elements (2026)",
                (
                    "Scores SBOMs against the 2026 Minimum Elements for a Software Bill of "
                    "Materials, published by CISA with the NSA, the FBI and fifteen "
                    "international partners, which replaced the 2021 NTIA elements. Checks "
                    "the seventeen data fields: nine about the document, including its "
                    "author, signature, format, generation context, tool and version, and "
                    "eight about each component, including producer, identifiers, hash "
                    "value and algorithm, license and dependencies. Where the standard "
                    "allows an author to state that a value is unknown, saying so reads as "
                    "a warning rather than a miss."
                ),
                {},
            ),
            # Superseded by the 2026 elements above, and kept because a contract or
            # a regulation can name this version of the standard.
            (
                CISA2025MinimumElementsPlugin,
                "CISA Minimum Elements (2025 Draft)",
                (
                    "Scores SBOMs against the August 2025 public comment draft of the CISA "
                    "Minimum Elements, which the 2026 elements have since replaced. Checks "
                    "the eleven data fields: SBOM author, software producer, component name "
                    "and version, software identifiers, hash, license, dependencies, tool "
                    "name, timestamp and generation context. Use this where an agreement "
                    "asks for the 2025 elements by name; otherwise use the 2026 plugin."
                ),
                {},
            ),
            (
                OpenChainTelcoPlugin,
                "OpenChain Telco SBOM Guide v1.1",
                (
                    "Checks SBOMs against the OpenChain Telco SBOM Guide v1.1, which telco "
                    "and regulated buyers ask for by name. The Guide mandates SPDX 2.2 or 2.3, "
                    "so a CycloneDX document cannot conform. Covers the required document and "
                    "package elements, the recommended package hash and PURL, the DESCRIBES and "
                    "CONTAINS relationships, and the build information including the CISA SBOM Type."
                ),
                {},
            ),
            (
                FDAMedicalDevicePlugin,
                "FDA Medical Device Cybersecurity (2025)",
                (
                    "Validates SBOMs against FDA guidance 'Cybersecurity in Medical Devices: "
                    "Quality System Considerations and Content of Premarket Submissions' (June 2025). "
                    "Checks for all NTIA minimum elements plus CLE (Component Lifecycle Enumeration) "
                    "data including software support status and end-of-support dates for each component."
                ),
                {},
            ),
            # EU Cyber Resilience Act
            (
                BSICompliancePlugin,
                "BSI TR-03183-2 v2.1 (EU CRA SBOM)",
                (
                    "Validates SBOMs against BSI Technical Guideline TR-03183-2 v2.1.0 - the "
                    "authoritative technical standard for EU Cyber Resilience Act SBOM compliance. "
                    "Requires CycloneDX 1.6+ or SPDX 3.0.1+. Checks for: SBOM Creator, Timestamp, "
                    "Component Creator, Component Name/Version, Filename, Dependencies with Completeness, "
                    "Distribution Licenses (SPDX), SHA-512 Hash, Executable/Archive/Structured Properties. "
                    "For digital signature requirements, use in combination with attestation plugins."
                ),
                {
                    "dependencies": {
                        "requires_one_of": [
                            {"type": "category", "value": "attestation"},
                        ],
                    },
                },
            ),
            # Unified attestation check covering both sbomify-stored
            # signatures/provenance AND GitHub-published Sigstore attestations
            # (formerly the separate ``github-attestation`` plugin).
            (
                SBOMVerificationPlugin,
                "SBOM Verification",
                (
                    "Unified SBOM attestation verification. Recomputes SHA-256 digest, "
                    "validates Cosign/Sigstore bundle signatures, confirms provenance "
                    "subject digests match the SBOM hash, and when the SBOM declares a "
                    "GitHub VCS link, fetches the GitHub-published attestation bundle and "
                    "verifies it via cosign. Passes when at least one cryptographic source "
                    "verifies the SBOM."
                ),
                {
                    "default_config": {
                        "certificate_oidc_issuer": "https://token.actions.githubusercontent.com",
                        "timeout": 60,
                    },
                },
            ),
            (
                OSVPlugin,
                "OSV Vulnerability Scanner",
                (
                    "Scans SBOMs for known vulnerabilities using the OSV (Open Source "
                    "Vulnerabilities) database via the osv-scanner binary. Supports both "
                    "CycloneDX and SPDX formats. Returns vulnerability findings with "
                    "severity levels, CVSS scores, references, and affected component details."
                ),
                {
                    "default_config": {
                        "timeout": OSVPlugin.DEFAULT_TIMEOUT,
                        "scanner_path": OSVPlugin.DEFAULT_SCANNER_PATH,
                    },
                },
            ),
            (
                DependencyTrackPlugin,
                "Dependency Track",
                (
                    "Scans CycloneDX SBOMs for vulnerabilities using Dependency Track. "
                    "Uploads SBOMs to a DT server for comprehensive vulnerability analysis "
                    "including CVSS scores, component-level findings, and continuous monitoring. "
                    "Available for Business and Enterprise plans only. "
                    "Does not support SPDX format."
                ),
                {
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
            ),
            # Post-quantum classification of CBOM crypto assets
            (
                PqcReadinessPlugin,
                "Post-Quantum Readiness",
                (
                    "Classifies the cryptographic assets in a CycloneDX CBOM for post-quantum "
                    "readiness. Each algorithm is graded quantum-safe, quantum-vulnerable, or "
                    "needs-review against NIST guidance (FIPS 203/204/205, NIST IR 8547, NSA "
                    "CNSA 2.0). Applies only to CBOM artifacts (bom_type 'cbom')."
                ),
                {},
            ),
            # Legacy-algorithm compliance for crypto assets
            (
                Sp800131aPlugin,
                "Legacy Algorithm Transitions (SP 800-131A)",
                (
                    "Checks the cryptographic assets in a CycloneDX document against the NIST "
                    "SP 800-131A transition schedule. Disallowed algorithms (DES, RC4, MD5, "
                    "sub-2048-bit RSA, DSA and SHA-1 signature generation) fail; deprecated "
                    "ones (SHA-1, SHA-224, 112-bit strength) warn with their 2030 sunset."
                ),
                {},
            ),
            # Crypto mechanisms and key lengths
            (
                BsiTr02102Plugin,
                "Crypto Mechanisms (BSI TR-02102)",
                (
                    "Grades cryptographic assets against BSI TR-02102 recommendations: 3000-bit "
                    "floor for RSA/DH/DSA, 250-bit floor for elliptic curves, block-cipher mode "
                    "checks, and the TR-02102-2 TLS version ladder. Complements the BSI TR-03183 "
                    "document check."
                ),
                {},
            ),
            # Expiry and validity-window findings
            (
                CertificateLifecyclePlugin,
                "Certificate Lifecycle",
                (
                    "Per-certificate findings for the certificates declared in a CycloneDX "
                    "document: expired certificates fail, certificates inside the 90-day renewal "
                    "window or beyond the 398-day CA/Browser Forum validity ceiling warn."
                ),
                {},
            ),
            # NSS algorithm-suite compliance
            (
                Cnsa2Plugin,
                "CNSA 2.0 Compliance",
                (
                    "Grades cryptographic assets against the NSA CNSA 2.0 suite (AES-256, "
                    "SHA-384/512, ML-KEM-1024, ML-DSA-87, LMS/XMSS). CNSA 1.0 holdovers warn "
                    "with the transition deadline; algorithms outside the suite fail. Intended "
                    "for National Security System suppliers."
                ),
                {},
            ),
        ]

        registered_builtin_names: set[str] = set()
        for plugin_class, display_name, description, extra in builtins:
            metadata = plugin_class().get_metadata()
            registered_builtin_names.add(metadata.name)
            defaults: dict[str, Any] = {
                "display_name": display_name,
                "description": description,
                "category": metadata.category.value,
                "version": metadata.version,
                "plugin_class_path": f"{plugin_class.__module__}.{plugin_class.__qualname__}",
                "is_builtin": True,
                **extra,
            }
            # The plugins admin lets an operator disable a plugin, mark it stable and
            # tune its default config, so a deploy only seeds those on a new row.
            seed = {"is_enabled": True, "is_beta": True, "default_config": defaults.pop("default_config", {})}
            try:
                with transaction.atomic():
                    RegisteredPlugin.objects.update_or_create(
                        name=metadata.name, defaults=defaults, create_defaults={**defaults, **seed}
                    )
            except OperationalError as e:
                logger.debug("Could not register plugin '%s' (table/column may not exist yet): %s", metadata.name, e)
            except ProgrammingError as e:
                if _is_missing_schema_error(e):
                    logger.debug(
                        "Could not register plugin '%s' (table/column may not exist yet): %s", metadata.name, e
                    )
                else:
                    logger.exception("Unexpected error while registering plugin '%s'", metadata.name)
                    raise

        # Reconcile: disable builtin plugins no longer in codebase
        if not registered_builtin_names:
            return
        try:
            with transaction.atomic():
                count = (
                    RegisteredPlugin.objects.filter(is_builtin=True)
                    .exclude(name__in=registered_builtin_names)
                    .update(is_enabled=False)
                )
                if count:
                    logger.info("Disabled %d orphaned builtin plugin(s)", count)
        except OperationalError as e:
            logger.debug("Could not reconcile builtin plugins (table may not exist yet): %s", e)
        except ProgrammingError as e:
            if _is_missing_schema_error(e):
                logger.debug("Could not reconcile builtin plugins (table may not exist yet): %s", e)
            else:
                logger.exception("Unexpected error during builtin plugin reconciliation")
                raise
