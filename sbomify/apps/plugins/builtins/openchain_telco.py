"""OpenChain Telco SBOM Guide v1.1 conformance.

Checks an SBOM against the requirement clauses of the OpenChain Telco SBOM
Guide v1.1, which telco and regulated buyers ask for by name.

One thing worth knowing before reading the checks: **the Guide mandates SPDX**.
Section 3.1 states a conformant document "SHALL adhere to the version 2.2 of the
SPDX Data Format as standardized in ISO/IEC 5962:2021, or to the version 2.3",
and §3.3.2 explains the choice over CycloneDX explicitly. A CycloneDX SBOM
cannot be conformant at all, so it fails 3.1 rather than being assessed
field-by-field against a profile it can never satisfy.

Clause coverage, with the ones that are not machine-checkable from the document
alone called out:

* 3.1  Data Format — SPDX 2.2 or 2.3
* 3.2  Required document-creation and package elements, plus the RECOMMENDED
       checksum/verification code and PURL, and the DESCRIBES/CONTAINS
       relationships
* 3.3  Machine-readable format — JSON is what reaches us; Tag:Value cannot be
       assessed here because ingestion normalises to JSON
* 3.5  Build information — Created, CreatorComment, and the Creator field's
       Organization and Tool lines, plus the CISA SBOM Type keyword
* 3.6-3.13 concern delivery, scope, confidentiality and process. They are
       properties of how an SBOM is supplied rather than of its content, so no
       finding is emitted for them.

Source: https://github.com/OpenChain-Project/Telco-WG/blob/main/OpenChain-Telco-SBOM-Guide_EN.md
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.sdk.base import AssessmentPlugin, SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.logging import getLogger

logger = getLogger(__name__)

# §3.5: the six CISA SBOM types, expected in CreatorComment as "SBOM Type: xxx".
_CISA_SBOM_TYPES = ("design", "source", "build", "analyzed", "deployed", "runtime")

_SUPPORTED_SPDX_VERSIONS = ("SPDX-2.2", "SPDX-2.3")


# Most of §3.2's required document elements are top-level SPDX keys; only
# Creator and Created live under creationInfo. Saying "in the document creation
# information" for all of them sends the reader to the wrong place.
_CREATION_INFO_FIELDS = {"creator", "created"}


def _where_to_fix(slug: str, field: str) -> str:
    if slug in _CREATION_INFO_FIELDS:
        return f"Populate {field} in the document creation information."
    return f"Populate the top-level {field} key."


class OpenChainTelcoPlugin(AssessmentPlugin):
    """OpenChain Telco SBOM Guide v1.1 conformance checks."""

    VERSION = "1.0.0"
    STANDARD_NAME = "OpenChain Telco SBOM Guide"
    STANDARD_VERSION = "1.1"
    STANDARD_URL = "https://github.com/OpenChain-Project/Telco-WG/blob/main/OpenChain-Telco-SBOM-Guide_EN.md"

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="openchain-telco-1.1",
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
            supported_bom_types=["sbom"],
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict[str, Any] | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        logger.info(f"[OPENCHAIN-TELCO] Starting conformance check for SBOM {sbom_id}")

        try:
            sbom_data = json.loads(sbom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return self._create_error_result(f"Invalid JSON format: {e}")
        except Exception as e:
            return self._create_error_result(f"Failed to read SBOM: {e}")

        findings = self._check(sbom_data)

        summary = AssessmentSummary(
            total_findings=len(findings),
            pass_count=sum(1 for f in findings if f.status == "pass"),
            fail_count=sum(1 for f in findings if f.status == "fail"),
            warning_count=sum(1 for f in findings if f.status == "warning"),
            error_count=0,
        )
        logger.info(
            f"[OPENCHAIN-TELCO] Completed for SBOM {sbom_id}: "
            f"{summary.pass_count} pass, {summary.fail_count} fail, {summary.warning_count} warn"
        )

        return AssessmentResult(
            plugin_name="openchain-telco-1.1",
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=findings,
            metadata={
                "standard_name": self.STANDARD_NAME,
                "standard_version": self.STANDARD_VERSION,
                "standard_url": self.STANDARD_URL,
            },
        )

    # ---- clause checks -------------------------------------------------

    def _check(self, sbom: dict[str, Any]) -> list[Finding]:
        spdx_version = sbom.get("spdxVersion") or ""
        findings = [self._data_format(spdx_version)]

        # Everything below reads SPDX field names. Against a non-SPDX document
        # they would all fail for the same single reason, which buries the one
        # finding that matters, so the run stops at 3.1.
        if not str(spdx_version).startswith("SPDX-"):
            return findings

        findings.extend(self._document_creation(sbom))
        findings.extend(self._packages(sbom))
        findings.append(self._relationships(sbom))
        findings.extend(self._build_information(sbom))
        return findings

    def _finding(self, clause: str, slug: str, title: str, status: str, description: str, fix: str = "") -> Finding:
        return Finding(
            id=f"openchain-telco-1.1:{slug}",
            title=f"{clause} {title}",
            description=description,
            status=status,
            severity="info",
            remediation=fix or None,
        )

    def _data_format(self, spdx_version: Any) -> Finding:
        version = str(spdx_version or "")
        if version in _SUPPORTED_SPDX_VERSIONS:
            return self._finding("3.1", "data-format", "Data Format", "pass", f"Document declares {version}.")
        if version.startswith("SPDX-"):
            return self._finding(
                "3.1",
                "data-format",
                "Data Format",
                "fail",
                f"The Guide requires SPDX 2.2 or 2.3; this document declares {version}.",
                "Produce the SBOM as SPDX 2.2 or 2.3.",
            )
        return self._finding(
            "3.1",
            "data-format",
            "Data Format",
            "fail",
            "The Guide requires SPDX 2.2 or 2.3 (§3.1). This document is not SPDX, so it cannot conform.",
            "Produce an SPDX 2.2 or 2.3 document. CycloneDX cannot satisfy this Guide.",
        )

    def _document_creation(self, sbom: dict[str, Any]) -> list[Finding]:
        # A malformed document can carry any JSON type here. Calling .get on a
        # non-dict would raise and lose the assessment entirely, when the point
        # of the check is to report the document as non-conformant.
        raw_creation_info = sbom.get("creationInfo")
        creation_info = raw_creation_info if isinstance(raw_creation_info, dict) else {}
        required = {
            "spdx-version": ("SPDXVersion", sbom.get("spdxVersion")),
            "data-license": ("DataLicense", sbom.get("dataLicense")),
            "spdx-id": ("SPDXID", sbom.get("SPDXID")),
            "document-name": ("DocumentName", sbom.get("name")),
            "document-namespace": ("DocumentNamespace", sbom.get("documentNamespace")),
            "creator": ("Creator", creation_info.get("creators")),
            "created": ("Created", creation_info.get("created")),
        }
        findings = []
        for slug, (field, value) in required.items():
            present = bool(value)
            findings.append(
                self._finding(
                    "3.2",
                    slug,
                    field,
                    "pass" if present else "fail",
                    f"{field} is present." if present else f"{field} is required by §3.2 and is missing.",
                    "" if present else _where_to_fix(slug, field),
                )
            )
        return findings

    def _packages(self, sbom: dict[str, Any]) -> list[Finding]:
        packages = [p for p in (sbom.get("packages") or []) if isinstance(p, dict)]
        if not packages:
            return [
                self._finding(
                    "3.2",
                    "packages",
                    "Package information",
                    "fail",
                    "The document contains no packages, so none of the required package elements can be present.",
                    "Include the packages the SBOM describes.",
                )
            ]

        required = {
            "package-name": ("PackageName", "name"),
            "package-spdx-id": ("SPDXID", "SPDXID"),
            "package-version": ("PackageVersion", "versionInfo"),
            "package-supplier": ("PackageSupplier", "supplier"),
            "package-download-location": ("PackageDownloadLocation", "downloadLocation"),
            "package-license-concluded": ("PackageLicenseConcluded", "licenseConcluded"),
            "package-license-declared": ("PackageLicenseDeclared", "licenseDeclared"),
            "package-copyright": ("PackageCopyrightText", "copyrightText"),
        }
        findings = []
        for slug, (field, key) in required.items():
            missing = [p.get("name") or p.get("SPDXID") or "?" for p in packages if not p.get(key)]
            findings.append(self._coverage_finding("3.2", slug, field, packages, missing, status_when_missing="fail"))

        # §3.2: one of PackageChecksum or PackageVerificationCode is RECOMMENDED.
        no_hash = [
            p.get("name") or "?" for p in packages if not (p.get("checksums") or p.get("packageVerificationCode"))
        ]
        findings.append(
            self._coverage_finding(
                "3.2",
                "package-hash",
                "PackageChecksum or PackageVerificationCode",
                packages,
                no_hash,
                status_when_missing="warning",
                recommended=True,
            )
        )

        # §3.2: a package SHOULD be identified by a PURL, carried in ExternalRef.
        no_purl = [p.get("name") or "?" for p in packages if not self._has_purl(p)]
        findings.append(
            self._coverage_finding(
                "3.2",
                "package-purl",
                "Package URL (PURL)",
                packages,
                no_purl,
                status_when_missing="warning",
                recommended=True,
            )
        )
        return findings

    @staticmethod
    def _has_purl(package: dict[str, Any]) -> bool:
        for ref in package.get("externalRefs") or []:
            if isinstance(ref, dict) and str(ref.get("referenceType", "")).lower() == "purl":
                return True
        return False

    def _coverage_finding(
        self,
        clause: str,
        slug: str,
        field: str,
        packages: list[dict[str, Any]],
        missing: list[str],
        *,
        status_when_missing: str,
        recommended: bool = False,
    ) -> Finding:
        total = len(packages)
        if not missing:
            return self._finding(clause, slug, field, "pass", f"All {total} packages carry {field}.")
        # Name a handful rather than every package: the list is for orienting the
        # reader, and a thousand-package SBOM would otherwise produce a wall.
        sample = ", ".join(missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
        word = "RECOMMENDED" if recommended else "REQUIRED"
        return self._finding(
            clause,
            slug,
            field,
            status_when_missing,
            f"{len(missing)} of {total} packages are missing {field}, which §{clause} marks {word}: {sample}.",
            f"Populate {field} for every package.",
        )

    def _relationships(self, sbom: dict[str, Any]) -> Finding:
        kinds = {
            str(r.get("relationshipType", "")).upper() for r in (sbom.get("relationships") or []) if isinstance(r, dict)
        }
        missing = [k for k in ("DESCRIBES", "CONTAINS") if k not in kinds]
        if not missing:
            return self._finding("3.2", "relationships", "Relationships", "pass", "DESCRIBES and CONTAINS present.")
        return self._finding(
            "3.2",
            "relationships",
            "Relationships",
            "fail",
            f"§3.2 requires at least DESCRIBES and CONTAINS relationships; missing: {', '.join(missing)}.",
            "Emit the relationships describing the document and its contained packages.",
        )

    def _build_information(self, sbom: dict[str, Any]) -> list[Finding]:
        # A malformed document can carry any JSON type here. Calling .get on a
        # non-dict would raise and lose the assessment entirely, when the point
        # of the check is to report the document as non-conformant.
        raw_creation_info = sbom.get("creationInfo")
        creation_info = raw_creation_info if isinstance(raw_creation_info, dict) else {}
        creators = [str(c) for c in (creation_info.get("creators") or [])]
        comment = str(creation_info.get("creatorComment") or "")
        findings = []

        has_org = any(c.strip().lower().startswith("organization:") for c in creators)
        findings.append(
            self._finding(
                "3.5",
                "creator-organization",
                "Creator Organization",
                "pass" if has_org else "fail",
                "Creator includes an Organization line."
                if has_org
                else "§3.5 requires the Creator field to include a line with the Organization keyword.",
                "" if has_org else "Add an 'Organization: <name>' creator entry.",
            )
        )

        tool_lines = [c for c in creators if c.strip().lower().startswith("tool:")]
        # §3.5: the Tool line must carry name and version. The Guide says they
        # SHOULD be hyphen-separated, so a missing version is the failure and
        # the separator is not policed.
        tool_versioned = any(re.search(r"\d", line.split(":", 1)[1]) for line in tool_lines if ":" in line)
        findings.append(
            self._finding(
                "3.5",
                "creator-tool",
                "Creator Tool and version",
                "pass" if tool_versioned else "fail",
                "Creator includes a Tool line carrying a version."
                if tool_versioned
                else "§3.5 requires a Tool line naming the tool and its version.",
                "" if tool_versioned else "Add a 'Tool: <name>-<version>' creator entry.",
            )
        )

        findings.append(
            self._finding(
                "3.5",
                "creator-comment",
                "CreatorComment",
                "pass" if comment else "fail",
                "CreatorComment is present."
                if comment
                else "§3.2 and §3.5 require CreatorComment, which carries the SBOM build information.",
                "" if comment else "Populate CreatorComment.",
            )
        )

        # A bare substring match, deliberately. "SBOM Type: Build" is only the
        # recommended syntax; the Guide then says it requires no particular
        # format, "only ... that at least one of the words 'Design', 'Source',
        # 'Build', 'Analyzed', 'Deployed', 'Runtime' is present, regardless of
        # the case". Demanding the label would fail documents the Guide accepts.
        has_type = any(t in comment.lower() for t in _CISA_SBOM_TYPES)
        findings.append(
            self._finding(
                "3.5",
                "sbom-type",
                "SBOM Type",
                "pass" if has_type else "fail",
                "CreatorComment names a CISA SBOM Type."
                if has_type
                else "§3.5 requires the CISA SBOM Type in CreatorComment "
                "(Design, Source, Build, Analyzed, Deployed or Runtime).",
                "" if has_type else "Add 'SBOM Type: Build' (or the applicable type) to CreatorComment.",
            )
        )
        return findings

    def _create_error_result(self, error_message: str) -> AssessmentResult:
        """An unreadable document cannot be judged conformant or not."""
        return AssessmentResult(
            plugin_name="openchain-telco-1.1",
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(total_findings=1, pass_count=0, fail_count=0, warning_count=0, error_count=1),
            findings=[
                Finding(
                    id="openchain-telco-1.1:error",
                    title="Assessment Error",
                    description=error_message,
                    status="error",
                    severity="high",
                )
            ],
            metadata={"standard_name": self.STANDARD_NAME, "standard_version": self.STANDARD_VERSION},
        )
