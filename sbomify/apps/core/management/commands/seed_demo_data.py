"""Fill a local workspace with enough realistic data to see every page full.

The bare dev database has a handful of rows, so most lists render empty and
pagination, filters and severity styling never show up. This command writes a
whole catalogue: products with and without components, components backed by
SBOMs and by documents, releases (tagged, pre-release and empty), documents
including one behind an NDA, and advisories covering every severity, every
publication status and every remediation status.

It is idempotent. Everything is keyed off a stable name and skipped when it
already exists, so running it twice changes nothing. SBOM uploads go through
the real upload API (the same route ``create_test_sbom_environment`` uses), and
that API answers 409 for a duplicate artifact, which is what makes the second
run a no-op.

Nothing here weakens a permission check. The API calls are made with a real
``HttpRequest`` carrying the workspace owner, so ``can()`` reads the live
``Member`` row exactly as it would for a browser request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.core.utils import add_artifact_to_release
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.apis import sbom_upload_cyclonedx, sbom_upload_spdx
from sbomify.apps.sboms.models import SBOM, ProductComponent, ProductIdentifier, ProductLink
from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryReference,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.advisories import create_advisory, post_update, publish_advisory
from sbomify.apps.teams.models import Member, Team

# .../apps/core/management/commands/this.py -> .../apps/sboms/tests/test_data
TEST_DATA = Path(__file__).resolve().parents[3] / "sboms" / "tests" / "test_data"

BOM = Component.ComponentType.BOM
DOC = Component.ComponentType.DOCUMENT
PUBLIC = Component.Visibility.PUBLIC
PRIVATE = Component.Visibility.PRIVATE
GATED = Component.Visibility.GATED
APPROVAL = Component.GatingMode.APPROVAL_ONLY
APPROVAL_NDA = Component.GatingMode.APPROVAL_PLUS_NDA

# Version ladder for the components that carry a stack of SBOMs. Enough steps
# that a component detail page shows real history rather than a single row.
VERSION_LADDER = ("1.0.0", "1.2.0", "1.4.1", "2.0.0", "2.1.0", "2.2.3", "3.0.0", "3.1.0")

# Small file first: most components get one SBOM and the small one keeps the
# run quick. The larger ones give the artifact pages something to show.
CDX_FILES = ("hello-world_syft.cdx.json", "sbomify_trivy.cdx.json", "sbomify_syft.cdx.json")
SPDX_FILE = "hello-world_syft.spdx.json"
CBOM_FILE = "cbom_sample_1.6.cdx.json"


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    kind: str = BOM
    visibility: str = PRIVATE
    gating: str = ""
    # How many SBOM versions to upload. Ignored for document components.
    sboms: int = 1
    documents: tuple[tuple[str, str, str], ...] = ()  # (name, document_type, version)


@dataclass(frozen=True)
class ProductSpec:
    name: str
    description: str
    is_public: bool
    components: tuple[ComponentSpec, ...] = ()


@dataclass(frozen=True)
class ReleaseSpec:
    product_index: int
    name: str
    version: str
    description: str
    is_latest: bool = False
    is_prerelease: bool = False
    # Pin one artifact from each of these component indexes within the product.
    artifact_components: tuple[int, ...] = ()


@dataclass(frozen=True)
class AdvisorySpec:
    title: str
    summary: str
    severity: str  # "" means unrated
    identifier: str
    remediation: str
    product_indexes: tuple[int, ...] = ()
    extra_cves: tuple[str, ...] = ()
    publish: str = ""  # "", "public" or "gated"
    withdraw: bool = False
    notice: bool = False
    updates: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


def _doc(name: str, doc_type: str, version: str = "1.0") -> tuple[str, str, str]:
    return (name, doc_type, version)


# Two catalogues so two workspaces do not look like copies of each other. A
# workspace takes the slice at its index, wrapping round, so the choice is
# stable across runs and independent of which workspaces are targeted.
SLICE_A: tuple[ProductSpec, ...] = (
    ProductSpec(
        "Atlas Edge Gateway",
        "Industrial edge gateway that bridges factory-floor protocols to the cloud.",
        True,
        (
            ComponentSpec("atlas-gateway-firmware", BOM, PUBLIC, sboms=6),
            ComponentSpec("atlas-gateway-linux-base", BOM, PUBLIC, sboms=3),
            ComponentSpec("atlas-mqtt-broker", BOM, PUBLIC, sboms=3),
            ComponentSpec("atlas-device-agent", BOM, PRIVATE, sboms=3),
            ComponentSpec("atlas-provisioning-cli", BOM, PRIVATE, sboms=2),
            ComponentSpec("atlas-web-console", BOM, PUBLIC, sboms=1),
            ComponentSpec("atlas-crypto-module", BOM, GATED, APPROVAL, sboms=1),
            ComponentSpec(
                "Atlas security whitepaper",
                DOC,
                PUBLIC,
                documents=(
                    _doc("Atlas security architecture", Document.DocumentType.DOCUMENTATION, "3.1"),
                    _doc("Atlas hardening guide", Document.DocumentType.MANUAL, "3.1"),
                ),
            ),
        ),
    ),
    ProductSpec(
        "Atlas Controller",
        "Programmable controller for the Atlas range, shipped as a sealed firmware image.",
        True,
        (
            ComponentSpec("atlas-controller-firmware", BOM, PUBLIC, sboms=2),
            ComponentSpec("atlas-controller-bootloader", BOM, PRIVATE, sboms=1),
            ComponentSpec("atlas-modbus-driver", BOM, PUBLIC, sboms=1),
            ComponentSpec("atlas-canbus-driver", BOM, PRIVATE, sboms=1),
            ComponentSpec("atlas-controller-ota", BOM, PUBLIC, sboms=1),
            ComponentSpec(
                "Atlas controller manual",
                DOC,
                PUBLIC,
                documents=(_doc("Atlas controller installation manual", Document.DocumentType.MANUAL, "2.4"),),
            ),
        ),
    ),
    ProductSpec(
        "Helios Sensor Hub",
        "Multi-sensor aggregation hub for cold-storage and process monitoring.",
        False,
        (
            ComponentSpec("helios-sensor-firmware", BOM, PRIVATE, sboms=2),
            ComponentSpec("helios-edge-runtime", BOM, PRIVATE, sboms=1),
            ComponentSpec("helios-calibration-tool", BOM, PRIVATE, sboms=1),
            ComponentSpec(
                "Helios assurance evidence",
                DOC,
                GATED,
                APPROVAL_NDA,
                documents=(_doc("Helios penetration test report", Document.DocumentType.PENTEST_REPORT, "2026.1"),),
            ),
        ),
    ),
    ProductSpec(
        "Helios Firmware Suite",
        "Signing and update services that ship firmware to the Helios fleet.",
        False,
        (
            ComponentSpec("helios-update-service", BOM, PRIVATE, sboms=1),
            ComponentSpec("helios-signing-service", BOM, PRIVATE, sboms=1),
        ),
    ),
    ProductSpec(
        "Vector Fleet Manager",
        "Web platform for tracking, grouping and updating deployed devices.",
        True,
        (
            ComponentSpec("vector-fleet-api", BOM, PUBLIC, sboms=2),
            ComponentSpec("vector-fleet-ui", BOM, PUBLIC, sboms=1),
        ),
    ),
    ProductSpec(
        "Vector Mobile App",
        "Field engineer app for commissioning and diagnosing devices on site.",
        True,
        (ComponentSpec("vector-mobile-client", BOM, PUBLIC, sboms=1),),
    ),
    ProductSpec(
        "Beacon Telemetry Service",
        "Ingest tier that accepts device telemetry and normalises it for analytics.",
        False,
        (ComponentSpec("beacon-ingest-service", BOM, PRIVATE, sboms=1),),
    ),
    ProductSpec(
        "Beacon Analytics",
        "Reporting and alerting built on the Beacon telemetry store.",
        True,
        (ComponentSpec("beacon-analytics-engine", BOM, GATED, APPROVAL, sboms=1),),
    ),
    ProductSpec(
        "Orion Cold Chain Monitor",
        "Battery-powered logger for temperature-controlled transport.",
        True,
        (ComponentSpec("orion-monitor-firmware", BOM, PUBLIC, sboms=1),),
    ),
    ProductSpec(
        "Orion Retail Kiosk",
        "Self-service kiosk build used in retail pilot deployments.",
        False,
        (ComponentSpec("orion-kiosk-shell", BOM, PRIVATE, sboms=1),),
    ),
    ProductSpec("Pioneer Field Terminal", "Rugged handheld terminal. Onboarding not started.", True),
    ProductSpec("Pioneer Docking Station", "Charging and data dock for the Pioneer terminal.", False),
    ProductSpec("Legacy Meter Reader", "End of life meter reader kept for support records only.", False),
)

SLICE_B: tuple[ProductSpec, ...] = (
    ProductSpec(
        "Meridian Payments Core",
        "Card and account payment processing engine behind the Meridian platform.",
        True,
        (
            ComponentSpec("meridian-payments-api", BOM, PUBLIC, sboms=6),
            ComponentSpec("meridian-auth-service", BOM, PUBLIC, sboms=3),
            ComponentSpec("meridian-settlement-worker", BOM, PUBLIC, sboms=3),
            ComponentSpec("meridian-fraud-rules", BOM, PRIVATE, sboms=3),
            ComponentSpec("meridian-card-vault", BOM, PRIVATE, sboms=2),
            ComponentSpec("meridian-admin-console", BOM, PUBLIC, sboms=1),
            ComponentSpec("meridian-hsm-adapter", BOM, GATED, APPROVAL, sboms=1),
            ComponentSpec(
                "Meridian compliance pack",
                DOC,
                PUBLIC,
                documents=(
                    _doc("Meridian PCI DSS attestation", Document.DocumentType.COMPLIANCE, "2026"),
                    _doc("Meridian threat model", Document.DocumentType.THREAT_MODEL, "4.0"),
                ),
            ),
        ),
    ),
    ProductSpec(
        "Meridian Ledger",
        "Double-entry ledger and reconciliation service.",
        True,
        (
            ComponentSpec("meridian-ledger-core", BOM, PUBLIC, sboms=2),
            ComponentSpec("meridian-ledger-migrations", BOM, PRIVATE, sboms=1),
            ComponentSpec("meridian-reconciliation", BOM, PUBLIC, sboms=1),
            ComponentSpec("meridian-export-service", BOM, PRIVATE, sboms=1),
            ComponentSpec("meridian-ledger-cli", BOM, PUBLIC, sboms=1),
            ComponentSpec(
                "Meridian ledger handbook",
                DOC,
                PUBLIC,
                documents=(_doc("Meridian ledger operations handbook", Document.DocumentType.MANUAL, "1.9"),),
            ),
        ),
    ),
    ProductSpec(
        "Aurora Identity Platform",
        "Customer identity, session and consent management.",
        False,
        (
            ComponentSpec("aurora-identity-api", BOM, PRIVATE, sboms=2),
            ComponentSpec("aurora-session-store", BOM, PRIVATE, sboms=1),
            ComponentSpec("aurora-consent-service", BOM, PRIVATE, sboms=1),
            ComponentSpec(
                "Aurora assurance evidence",
                DOC,
                GATED,
                APPROVAL_NDA,
                documents=(_doc("Aurora penetration test report", Document.DocumentType.PENTEST_REPORT, "2026.1"),),
            ),
        ),
    ),
    ProductSpec(
        "Aurora Access Broker",
        "Policy broker that issues short-lived credentials to internal services.",
        False,
        (
            ComponentSpec("aurora-policy-engine", BOM, PRIVATE, sboms=1),
            ComponentSpec("aurora-token-issuer", BOM, PRIVATE, sboms=1),
        ),
    ),
    ProductSpec(
        "Quantum Risk Engine",
        "Real-time scoring service for transaction risk.",
        True,
        (
            ComponentSpec("quantum-scoring-api", BOM, PUBLIC, sboms=2),
            ComponentSpec("quantum-feature-store", BOM, PUBLIC, sboms=1),
        ),
    ),
    ProductSpec(
        "Quantum Reporting",
        "Scheduled risk and exposure reporting for compliance teams.",
        True,
        (ComponentSpec("quantum-report-builder", BOM, PUBLIC, sboms=1),),
    ),
    ProductSpec(
        "Harbor Merchant Portal",
        "Self-service portal where merchants manage payouts and disputes.",
        False,
        (ComponentSpec("harbor-portal-web", BOM, PRIVATE, sboms=1),),
    ),
    ProductSpec(
        "Harbor Settlement Service",
        "Batch settlement and payout scheduling.",
        True,
        (ComponentSpec("harbor-settlement-core", BOM, GATED, APPROVAL, sboms=1),),
    ),
    ProductSpec(
        "Cascade Data Pipeline",
        "Streaming pipeline that feeds the analytics warehouse.",
        True,
        (ComponentSpec("cascade-stream-processor", BOM, PUBLIC, sboms=1),),
    ),
    ProductSpec(
        "Cascade Warehouse",
        "Analytical store and query layer for finance reporting.",
        False,
        (ComponentSpec("cascade-query-gateway", BOM, PRIVATE, sboms=1),),
    ),
    ProductSpec("Summit Partner API", "Partner integration surface. Onboarding not started.", True),
    ProductSpec("Summit Sandbox", "Sandbox environment for partner testing.", False),
    ProductSpec("Archive Statement Service", "Retired statement generator kept for support records.", False),
)

CATALOGUES: tuple[tuple[ProductSpec, ...], ...] = (SLICE_A, SLICE_B)

# Workspace-wide document components. Only document components may be global,
# and the NDA lives here because it belongs to the workspace, not a product.
GLOBAL_COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        "Company NDA",
        DOC,
        PRIVATE,
        documents=(_doc("Mutual non-disclosure agreement", Document.DocumentType.COMPLIANCE, "2026.1"),),
    ),
    ComponentSpec(
        "Security policies",
        DOC,
        PUBLIC,
        documents=(
            _doc("Vulnerability disclosure policy", Document.DocumentType.COMPLIANCE, "2.0"),
            _doc("Secure development policy", Document.DocumentType.COMPLIANCE, "2.0"),
        ),
    ),
    ComponentSpec(
        "Certifications",
        DOC,
        PUBLIC,
        documents=(_doc("ISO 27001 certificate", Document.DocumentType.COMPLIANCE, "2026"),),
    ),
)

RELEASE_SPECS: tuple[ReleaseSpec, ...] = (
    ReleaseSpec(0, "latest", "", "Rolling pointer to the newest artifact from every component.", is_latest=True),
    ReleaseSpec(0, "v3.1.0", "3.1.0", "Current shipping build.", artifact_components=(0, 1, 2, 7)),
    ReleaseSpec(0, "v3.0.0", "3.0.0", "First build of the 3.x line.", artifact_components=(0, 3)),
    ReleaseSpec(0, "v3.2.0-rc1", "3.2.0-rc1", "Release candidate, not for production.", is_prerelease=True),
    ReleaseSpec(1, "latest", "", "Rolling pointer to the newest artifact from every component.", is_latest=True),
    ReleaseSpec(1, "v2.0.0", "2.0.0", "Controller refresh with the new bootloader.", artifact_components=(0, 2)),
    ReleaseSpec(2, "v1.4.0", "1.4.0", "Sensor hub maintenance build.", artifact_components=(0,)),
    ReleaseSpec(4, "v0.9.0-beta", "0.9.0-beta", "Early access build. No artifacts pinned yet.", is_prerelease=True),
)

ADVISORY_SPECS: tuple[AdvisorySpec, ...] = (
    AdvisorySpec(
        title="Remote code execution in the device management endpoint",
        summary="An unauthenticated attacker can run commands on the gateway.",
        severity="critical",
        identifier="CVE-2026-21001",
        remediation="resolved",
        product_indexes=(0, 1),
        extra_cves=("CVE-2026-21002",),
        publish="public",
        updates=(
            "We confirmed the issue on all 3.x builds and started work on a fix.",
            "Patched builds are available. Update as soon as you can.",
        ),
        references=("https://example.com/advisories/rce-device-management",),
    ),
    AdvisorySpec(
        title="Authentication bypass in the session refresh flow",
        summary="A crafted refresh token can extend an expired session.",
        severity="critical",
        identifier="CVE-2026-21010",
        remediation="fix_in_progress",
        product_indexes=(4, 5),
        publish="public",
        updates=("A fix is in testing. We will publish a patched build this week.",),
    ),
    AdvisorySpec(
        title="Privilege escalation through the provisioning CLI",
        summary="A local user can gain root while provisioning a device.",
        severity="critical",
        identifier="CVE-2026-21020",
        remediation="investigating",
        product_indexes=(0,),
        publish="gated",
        updates=("We are reproducing the report and will confirm affected versions.",),
    ),
    AdvisorySpec(
        title="Denial of service in the telemetry ingest parser",
        summary="A malformed telemetry frame can stop the ingest service.",
        severity="high",
        identifier="CVE-2026-21030",
        remediation="resolved",
        product_indexes=(6,),
        publish="public",
        updates=("Fixed and rolled out to all hosted instances.",),
    ),
    AdvisorySpec(
        title="Stored cross-site scripting in the web console",
        summary="A device name can carry script that runs for other operators.",
        severity="high",
        identifier="CVE-2026-21040",
        remediation="resolved",
        product_indexes=(0,),
        publish="public",
    ),
    AdvisorySpec(
        title="Weak key generation in the crypto module",
        summary="Keys generated before 2.2.3 have less entropy than documented.",
        severity="high",
        identifier="GHSA-2026-atls-crypto",
        remediation="fix_in_progress",
        product_indexes=(0, 2),
        publish="gated",
        updates=("Rotation guidance is being written and will be published with the fix.",),
    ),
    AdvisorySpec(
        title="Path traversal in the firmware update handler",
        summary="A signed update package can write outside its target directory.",
        severity="medium",
        identifier="CVE-2026-21050",
        remediation="resolved",
        product_indexes=(3,),
        publish="public",
    ),
    AdvisorySpec(
        title="Sensitive values written to the diagnostic log",
        summary="Diagnostic bundles included API keys in plain text.",
        severity="medium",
        identifier="CVE-2026-21060",
        remediation="investigating",
        product_indexes=(2, 3),
        publish="public",
        updates=("We are checking whether older diagnostic bundles are affected.",),
    ),
    AdvisorySpec(
        title="Open redirect on the mobile sign-in callback",
        summary="The sign-in callback accepts an arbitrary return URL.",
        severity="medium",
        identifier="CVE-2026-21070",
        remediation="identified",
        product_indexes=(5,),
    ),
    AdvisorySpec(
        title="Missing rate limit on the fleet search endpoint",
        summary="Search can be called without a limit and slows the API for others.",
        severity="low",
        identifier="",
        remediation="fix_in_progress",
        product_indexes=(4,),
        publish="public",
    ),
    AdvisorySpec(
        title="Outdated TLS ciphers offered by the analytics endpoint",
        summary="The endpoint still offers ciphers we no longer recommend.",
        severity="low",
        identifier="CVE-2026-21080",
        remediation="wont_fix",
        product_indexes=(7,),
        publish="public",
        updates=("Removing these ciphers would break a supported client, so they stay for now.",),
    ),
    AdvisorySpec(
        title="Verbose error page on the kiosk shell",
        summary="An error page showed the build path and version.",
        severity="none",
        identifier="",
        remediation="resolved",
        product_indexes=(9,),
        publish="public",
    ),
    AdvisorySpec(
        title="Reported issue in a bundled library did not apply",
        summary="We looked at the report and our build does not use the affected code.",
        severity="none",
        identifier="CVE-2026-21090",
        remediation="wont_fix",
        product_indexes=(8,),
        publish="public",
    ),
    AdvisorySpec(
        title="Third party report about the cold chain logger",
        summary="An external researcher sent us a report. Triage has not started.",
        severity="",
        identifier="",
        remediation="identified",
        product_indexes=(8,),
    ),
    AdvisorySpec(
        title="Suspected memory leak under sustained load",
        summary="Long running instances grow in memory. Cause not yet known.",
        severity="",
        identifier="",
        remediation="investigating",
        product_indexes=(6, 7),
    ),
    AdvisorySpec(
        title="Duplicate report withdrawn",
        summary="This advisory duplicated an earlier one and has been withdrawn.",
        severity="",
        identifier="CVE-2026-21100",
        remediation="resolved",
        product_indexes=(1,),
        publish="public",
        withdraw=True,
    ),
    AdvisorySpec(
        title="No product affected by the reported OpenSSL issue",
        summary="We checked every shipping product and none uses the affected build.",
        severity="low",
        identifier="CVE-2026-21110",
        remediation="resolved",
        notice=True,
        publish="public",
        updates=("Checks are complete across the whole portfolio. No action is needed.",),
    ),
)

# The remediation status decides what each per-product VEX row says, and each
# combination carries the field publish validation demands for it.
STATUS_BY_REMEDIATION: dict[str, dict[str, str]] = {
    "identified": {"status": AdvisoryProductStatus.Status.IN_TRIAGE},
    "investigating": {"status": AdvisoryProductStatus.Status.IN_TRIAGE},
    "fix_in_progress": {
        "status": AdvisoryProductStatus.Status.EXPLOITABLE,
        "response": AdvisoryProductStatus.Response.WORKAROUND_AVAILABLE,
        "action_statement": "Restrict access to the affected service until a patched build is available.",
    },
    "resolved": {
        "status": AdvisoryProductStatus.Status.RESOLVED,
        "response": AdvisoryProductStatus.Response.UPDATE,
        "recommended_version": "3.1.0",
        "action_statement": "Update to 3.1.0 or later.",
    },
    "wont_fix": {
        "status": AdvisoryProductStatus.Status.NOT_AFFECTED,
        "justification": AdvisoryProductStatus.Justification.CODE_NOT_REACHABLE,
        "response": AdvisoryProductStatus.Response.WILL_NOT_FIX,
        "impact_statement": "The affected code path is not reachable in any shipping configuration.",
    },
}

NOTICE_STATUS: dict[str, str] = {
    "status": AdvisoryProductStatus.Status.NOT_AFFECTED,
    "justification": AdvisoryProductStatus.Justification.CODE_NOT_PRESENT,
    "impact_statement": "The affected code is not present in any product we ship.",
}

PRODUCT_LINKS: tuple[tuple[str, str, str], ...] = (
    (ProductLink.LinkType.WEBSITE, "Product page", "https://example.com/products/"),
    (ProductLink.LinkType.DOCUMENTATION, "Documentation", "https://example.com/docs/"),
    (ProductLink.LinkType.SECURITY, "Security contact", "https://example.com/security/"),
)


def _document_body(name: str, version: str, team_name: str) -> bytes:
    return (
        f"# {name}\n\n"
        f"Version {version}\n\n"
        f"Prepared for {team_name}.\n\n"
        "This is sample content created by the seed_demo_data command so the "
        "document pages have something to show. It is not a real document.\n"
    ).encode()


@dataclass
class Counts:
    products: int = 0
    components: int = 0
    sboms: int = 0
    documents: int = 0
    releases: int = 0
    release_artifacts: int = 0
    advisories: int = 0
    skipped: dict[str, int] = field(default_factory=dict)


class Command(BaseCommand):
    help = "Fills workspaces with realistic demo data so every page can be seen full. Safe to run repeatedly."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--workspace",
            type=str,
            default="",
            help="Workspace key to seed. Defaults to every non-test workspace.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        all_workspaces = self._non_test_workspaces()
        if not all_workspaces:
            self.stdout.write(self.style.ERROR("No workspace found. Create one first."))
            return

        wanted = options["workspace"].strip()
        if wanted:
            targets = [team for team in all_workspaces if team.key == wanted]
            if not targets:
                self.stdout.write(self.style.ERROR(f"Workspace {wanted!r} not found."))
                return
        else:
            targets = all_workspaces

        totals = Counts()
        for team in targets:
            # The catalogue is chosen by the workspace's position among ALL
            # workspaces, not among the targeted ones, so seeding one workspace
            # alone gives it the same catalogue as seeding everything.
            catalogue = CATALOGUES[all_workspaces.index(team) % len(CATALOGUES)]
            self.stdout.write(self.style.MIGRATE_HEADING(f"\nWorkspace {team.name} ({team.key})"))
            self._seed_workspace(team, catalogue, totals)

        self._report(totals)

    def _non_test_workspaces(self) -> list[Team]:
        """Every real workspace, oldest first.

        The migration-created placeholder has no key, and a workspace named
        for testing is not somewhere to write demo data.
        """
        teams = Team.objects.exclude(key__isnull=True).exclude(key="").order_by("pk")
        return [team for team in teams if not team.name.lower().startswith("test")]

    def _owner(self, team: Team) -> Any:
        member = Member.objects.filter(team=team, role="owner").select_related("user").first()
        if member is None:
            member = Member.objects.filter(team=team).exclude(role="bot").select_related("user").first()
        return member.user if member else None

    def _request_for(self, user: Any) -> HttpRequest:
        """A request the real permission check can read a Member row from.

        ``verify_item_access`` looks the role up in the database from
        ``request.user``, so nothing needs patching or relaxing here.
        """
        request = HttpRequest()
        request.user = user
        request.session = {}  # type: ignore[assignment]
        return request

    def _seed_workspace(self, team: Team, catalogue: tuple[ProductSpec, ...], totals: Counts) -> None:
        owner = self._owner(team)
        if owner is None:
            self.stdout.write(self.style.WARNING("  No member to act as. Skipping."))
            return
        request = self._request_for(owner)

        products: list[Product] = []
        components_by_product: list[list[Component]] = []

        for spec in catalogue:
            product, created = Product.objects.get_or_create(
                team=team,
                name=spec.name,
                defaults={"description": spec.description, "is_public": spec.is_public},
            )
            products.append(product)
            if created:
                totals.products += 1
            self._seed_product_metadata(product)

            attached: list[Component] = []
            for component_spec in spec.components:
                component = self._ensure_component(team, component_spec, totals)
                ProductComponent.objects.get_or_create(product=product, component=component)
                attached.append(component)
                self._seed_component_artifacts(request, team, component, component_spec, totals)
            components_by_product.append(attached)

        nda_document = self._seed_global_components(team, totals)
        if nda_document is not None:
            self._wire_nda(team, nda_document)

        self._seed_releases(products, components_by_product, totals)
        self._seed_advisories(team, owner, products, totals)

    def _ensure_component(self, team: Team, spec: ComponentSpec, totals: Counts) -> Component:
        component, created = Component.objects.get_or_create(
            team=team,
            name=spec.name,
            defaults={
                "component_type": spec.kind,
                "visibility": spec.visibility,
                "gating_mode": spec.gating or None,
            },
        )
        if created:
            totals.components += 1
        return component

    def _seed_product_metadata(self, product: Product) -> None:
        """A couple of links and one identifier, so product detail is not bare."""
        for link_type, title, base_url in PRODUCT_LINKS:
            ProductLink.objects.get_or_create(
                product=product,
                link_type=link_type,
                title=title,
                defaults={"url": f"{base_url}{product.slug}", "team": product.team},
            )
        ProductIdentifier.objects.get_or_create(
            product=product,
            identifier_type=ProductIdentifier.IdentifierType.SKU,
            value=f"SKU-{product.slug.upper()[:20]}",
            defaults={"team": product.team},
        )

    def _seed_global_components(self, team: Team, totals: Counts) -> Document | None:
        """Workspace-wide document components, including the NDA."""
        nda_document: Document | None = None
        for spec in GLOBAL_COMPONENTS:
            component, created = Component.objects.get_or_create(
                team=team,
                name=spec.name,
                defaults={
                    "component_type": DOC,
                    "visibility": spec.visibility,
                    "is_global": True,
                },
            )
            if created:
                totals.components += 1
            for name, doc_type, version in spec.documents:
                document = self._ensure_document(team, component, name, doc_type, version, totals)
                if spec.name == "Company NDA":
                    nda_document = document
        return nda_document

    def _wire_nda(self, team: Team, nda_document: Document) -> None:
        """Point the workspace and its NDA-gated components at the NDA."""
        branding = dict(team.branding_info or {})
        if branding.get("company_nda_document_id") != nda_document.id:
            branding["company_nda_document_id"] = nda_document.id
            team.branding_info = branding
            team.save(update_fields=["branding_info"])

        gated = Component.objects.filter(team=team, gating_mode=APPROVAL_NDA, nda_document__isnull=True)
        for component in gated:
            component.nda_document = nda_document
            component.save(update_fields=["nda_document"])

    def _ensure_document(
        self, team: Team, component: Component, name: str, doc_type: str, version: str, totals: Counts
    ) -> Document:
        existing = Document.objects.filter(component=component, name=name, version=version).first()
        if existing is not None:
            return existing

        body = _document_body(name, version, team.name)
        subcategory = None
        if doc_type == Document.DocumentType.COMPLIANCE and "non-disclosure" in name.lower():
            subcategory = Document.ComplianceSubcategory.NDA

        filename = StorageClient("DOCUMENTS").upload_document(body)
        document = Document.objects.create(
            name=name,
            version=version,
            document_filename=filename,
            component=component,
            source="seed_demo_data",
            content_type="text/markdown",
            file_size=len(body),
            document_type=doc_type,
            description=f"Sample {doc_type.replace('-', ' ')} used for local demo data.",
            compliance_subcategory=subcategory,
        )
        totals.documents += 1
        return document

    def _seed_component_artifacts(
        self, request: HttpRequest, team: Team, component: Component, spec: ComponentSpec, totals: Counts
    ) -> None:
        if spec.kind == DOC:
            for name, doc_type, version in spec.documents:
                self._ensure_document(team, component, name, doc_type, version, totals)
            return

        for index in range(min(spec.sboms, len(VERSION_LADDER))):
            source = CDX_FILES[index % len(CDX_FILES)]
            if self._upload_cyclonedx(request, component, source, VERSION_LADDER[index]):
                totals.sboms += 1

        # The busiest component also carries a second format and a CBOM, so the
        # artifact tabs are not all one shape.
        if spec.sboms >= 6:
            if self._upload_spdx(request, component):
                totals.sboms += 1
            if self._upload_cyclonedx(request, component, CBOM_FILE, "1.0.0", bom_type="cbom"):
                totals.sboms += 1

    def _upload_cyclonedx(
        self, request: HttpRequest, component: Component, source: str, version: str, bom_type: str = "sbom"
    ) -> bool:
        path = TEST_DATA / source
        if not path.exists():
            self.stdout.write(self.style.WARNING(f"  Missing sample file {source}"))
            return False

        data = json.loads(path.read_text())
        metadata = data.setdefault("metadata", {})
        primary = metadata.setdefault("component", {})
        primary["name"] = component.name
        primary["version"] = version
        primary.pop("purl", None)

        request._body = json.dumps(data).encode()
        status_code, payload = sbom_upload_cyclonedx(request, component.id, bom_type=bom_type)
        return self._record_upload(status_code, payload, component, version)

    def _upload_spdx(self, request: HttpRequest, component: Component) -> bool:
        path = TEST_DATA / SPDX_FILE
        if not path.exists():
            self.stdout.write(self.style.WARNING(f"  Missing sample file {SPDX_FILE}"))
            return False

        data = json.loads(path.read_text())
        # The upload picks the package whose name matches the document name, so
        # both have to move together for the stored version to be ours.
        original = data.get("name")
        data["name"] = component.name
        for package in data.get("packages", []):
            if package.get("name") == original:
                package["name"] = component.name
                package["versionInfo"] = VERSION_LADDER[0]

        request._body = json.dumps(data).encode()
        status_code, payload = sbom_upload_spdx(request, component.id)
        return self._record_upload(status_code, payload, component, VERSION_LADDER[0])

    def _record_upload(self, status_code: int, payload: dict[str, Any], component: Component, version: str) -> bool:
        if status_code == 201:
            return True
        if status_code == 409:
            return False  # Already seeded. This is what makes a second run a no-op.
        detail = payload.get("detail", payload)
        self.stdout.write(self.style.WARNING(f"  {component.name} {version}: {status_code} {detail}"))
        return False

    def _seed_releases(
        self, products: list[Product], components_by_product: list[list[Component]], totals: Counts
    ) -> None:
        for spec in RELEASE_SPECS:
            if spec.product_index >= len(products):
                continue
            product = products[spec.product_index]

            if spec.is_latest:
                release = Release.get_or_create_latest_release(product)
            else:
                release, created = Release.objects.get_or_create(
                    product=product,
                    name=spec.name,
                    defaults={
                        "version": spec.version,
                        "description": spec.description,
                        "is_prerelease": spec.is_prerelease,
                    },
                )
                if created:
                    totals.releases += 1

            components = components_by_product[spec.product_index]
            for component_index in spec.artifact_components:
                if component_index >= len(components):
                    continue
                component = components[component_index]
                if component.component_type == DOC:
                    document = Document.objects.filter(component=component).order_by("created_at").first()
                    if document is None:
                        continue
                    result = add_artifact_to_release(release, document=document)
                else:
                    sbom = (
                        SBOM.objects.filter(component=component, bom_type=SBOM.BomType.SBOM)
                        .order_by("created_at")
                        .first()
                    )
                    if sbom is None:
                        continue
                    result = add_artifact_to_release(release, sbom=sbom)
                if result.get("created"):
                    totals.release_artifacts += 1

    def _seed_advisories(self, team: Team, user: Any, products: list[Product], totals: Counts) -> None:
        for spec in ADVISORY_SPECS:
            if SecurityAdvisory.objects.filter(team=team, title=spec.title).exists():
                continue
            with transaction.atomic():
                if self._build_advisory(team, user, spec, products):
                    totals.advisories += 1

    def _build_advisory(self, team: Team, user: Any, spec: AdvisorySpec, products: list[Product]) -> bool:
        selected = [products[index] for index in spec.product_indexes if index < len(products)]
        if spec.notice:
            advisory = self._create_notice(team, user, spec)
        else:
            if not selected:
                return False
            result = create_advisory(
                team=team,
                user=user,
                title=spec.title,
                severity=spec.severity,
                description=spec.summary,
                identifier=spec.identifier,
                products=selected,
            )
            if not result.ok:
                self.stdout.write(self.style.WARNING(f"  {spec.title}: {result.error}"))
                return False
            advisory = SecurityAdvisory.objects.get(pk=result.value)
            advisory.summary = spec.summary
            advisory.save()

        self._add_extra_vulnerabilities(advisory, spec)
        self._shape_statuses(advisory, spec)
        for url in spec.references:
            AdvisoryReference.objects.get_or_create(advisory=advisory, url=url, defaults={"summary": "Vendor bulletin"})

        if spec.publish:
            published = publish_advisory(team, user, advisory.id, visibility=spec.publish)
            if not published.ok:
                self.stdout.write(self.style.WARNING(f"  {spec.title}: {published.error}"))
                return False
            advisory.refresh_from_db()

        if spec.remediation != advisory.remediation_status:
            moved = post_update(team, user, advisory.id, kind=spec.remediation, note="")
            if not moved.ok:
                self.stdout.write(self.style.WARNING(f"  {spec.title}: {moved.error}"))
            advisory.refresh_from_db()

        for note in spec.updates:
            post_update(team, user, advisory.id, kind="update", note=note)

        if spec.withdraw:
            self._withdraw(advisory, user)
        return True

    def _create_notice(self, team: Team, user: Any, spec: AdvisorySpec) -> SecurityAdvisory:
        """A workspace notice names no product, so it is built directly.

        ``create_advisory`` always writes a product advisory, and the model
        refuses to turn one into a notice once products exist.
        """
        advisory = SecurityAdvisory.objects.create(
            team=team,
            advisory_type=SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE,
            title=spec.title,
            summary=spec.summary,
            description=spec.summary,
            severity=spec.severity,
            created_by=user,
        )
        vulnerability = AdvisoryVulnerability.objects.create(
            advisory=advisory,
            cve_id=spec.identifier if spec.identifier.upper().startswith("CVE-") else "",
            title="" if spec.identifier.upper().startswith("CVE-") else spec.title,
        )
        AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_product=None, **NOTICE_STATUS)
        AdvisoryEvent.objects.create(
            advisory=advisory,
            event_type=AdvisoryEvent.EventType.STATUS_CHANGE,
            actor=user,
            payload={"to": advisory.remediation_status},
        )
        return advisory

    def _add_extra_vulnerabilities(self, advisory: SecurityAdvisory, spec: AdvisorySpec) -> None:
        """A multi-CVE incident is one advisory, so the extras join this one."""
        advisory_products = list(advisory.products.all())
        for cve_id in spec.extra_cves:
            vulnerability, created = AdvisoryVulnerability.objects.get_or_create(
                advisory=advisory,
                cve_id=cve_id,
                defaults={"severity": spec.severity, "description": spec.summary},
            )
            if not created:
                continue
            for advisory_product in advisory_products:
                AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_product=advisory_product)

    def _shape_statuses(self, advisory: SecurityAdvisory, spec: AdvisorySpec) -> None:
        """Give every per-product row the fields its remediation state needs.

        Publish validation demands a fixed version on a resolved row, a
        justification on a not-affected one and an action on an affected one,
        so this is what makes a published advisory publishable.
        """
        shape = STATUS_BY_REMEDIATION.get(spec.remediation)
        if not shape:
            return
        statuses = AdvisoryProductStatus.objects.filter(
            vulnerability__advisory=advisory, advisory_product__isnull=False
        )
        for status in statuses:
            for attribute, value in shape.items():
                setattr(status, attribute, value)
            status.save()
            if shape["status"] == AdvisoryProductStatus.Status.RESOLVED:
                AdvisoryVersionRange.objects.get_or_create(
                    product_status=status,
                    introduced="3.0.0",
                    fixed=shape["recommended_version"],
                    defaults={"versioning_scheme": "semver"},
                )

        for vulnerability in advisory.vulnerabilities.all():
            changed = False
            if not vulnerability.severity:
                # create_advisory rates the advisory, not the row under it, and
                # a blank severity reads as unrated on the vulnerability list.
                vulnerability.severity = spec.severity
                changed = True
            if not vulnerability.recommendation:
                vulnerability.recommendation = shape.get("action_statement", "Follow the guidance in this advisory.")
                changed = True
            if changed:
                vulnerability.save()

    def _withdraw(self, advisory: SecurityAdvisory, user: Any) -> None:
        now = timezone.now()
        advisory.status = SecurityAdvisory.Status.WITHDRAWN
        advisory.withdrawn_at = now
        advisory.withdrawal_reason = "This advisory duplicated an earlier one."
        advisory.save()
        AdvisoryEvent.objects.create(
            advisory=advisory,
            event_type=AdvisoryEvent.EventType.WITHDRAWN,
            actor=user,
            body=advisory.withdrawal_reason,
        )

    def _report(self, totals: Counts) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("\nCreated this run"))
        for label, value in (
            ("products", totals.products),
            ("components", totals.components),
            ("sboms", totals.sboms),
            ("documents", totals.documents),
            ("releases", totals.releases),
            ("release artifacts", totals.release_artifacts),
            ("advisories", totals.advisories),
        ):
            self.stdout.write(f"  {label:<18} {value}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nTotals in the database"))
        for label, count in (
            ("workspaces", Team.objects.exclude(key__isnull=True).count()),
            ("products", Product.objects.count()),
            ("components", Component.objects.count()),
            ("sboms", SBOM.objects.count()),
            ("documents", Document.objects.count()),
            ("releases", Release.objects.count()),
            ("advisories", SecurityAdvisory.objects.count()),
            ("advisory vulnerabilities", AdvisoryVulnerability.objects.count()),
            ("advisory products", AdvisoryProduct.objects.count()),
        ):
            self.stdout.write(f"  {label:<26} {count}")
        self.stdout.write(self.style.SUCCESS("\nDone."))
