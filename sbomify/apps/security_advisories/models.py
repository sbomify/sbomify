"""Security advisories: the workspace's own vulnerability disclosures.

An advisory is the human-curated record a vendor publishes about a vulnerability
in *their* products: what it is, which products and versions it touches, what
users should do, and how the story developed over time. It is internal status
tracking first and trust-center content second.

Aggregate root is :class:`SecurityAdvisory`, scoped to a ``teams.Team``. Everything
else cascades from it. History lives in the append-only :class:`AdvisoryEvent`
timeline, which carries both human messages and field-change audit rows, so the
advisory has one chronological story rather than two.

**VEX feeds in, not out.** An uploaded VEX document (an ``SBOM`` row with
``bom_type="vex"``, parsed by ``vulnerability_scanning.vex_formats``) can
pre-populate status rows. No CSAF/OpenVEX/CycloneDX document is generated from an
advisory.

**Stored vocabulary is CycloneDX**, matching ``vulnerability_scanning.triage``:
``TRIAGE_STATES`` for :class:`AdvisoryProductStatus.Status` and
``TRIAGE_JUSTIFICATIONS`` for its justifications. That is deliberate and the one
place this schema departs from a pure OpenVEX/CISA shape:

* ``vex.py`` normalises every ingested format to CycloneDX vocabulary, so storing
  anything else would mean converting on the way in.
* The CISA five-value justification set cannot express six of CycloneDX's nine
  values (``requires_configuration``, ``requires_dependency``,
  ``requires_environment``, ``protected_by_compiler``, ``protected_at_runtime``,
  ``protected_at_perimeter``), and ``_CISA_TO_CDX_JUSTIFICATION`` collapses two
  pairs, so it cannot be reversed without guessing.
* ``false_positive`` is one of the two suppressing states this codebase honours
  and neither OpenVEX nor CSAF can express it.

Converting outward to the CISA set is lossy but well-defined, so a future CSAF
export maps at the boundary. The reverse would lose data at rest.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from sbomify.apps.core.utils import generate_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sbomify.apps.teams.models import Team

# CVE ID syntax: the sequence part is four or more digits and has no upper bound.
CVE_ID_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")


class Severity(models.TextChoices):
    """CVSS qualitative severity ratings, shared by advisories and vulnerabilities."""

    NONE = "none", "None"
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class ReferenceType(models.TextChoices):
    """Which database an external identifier belongs to.

    Advisory ids arrive from every vulnerability database in circulation and the
    codebase already branches on their prefixes in several templates. Naming the
    scheme once, at ingest, means consumers read a field instead of re-parsing a
    string. ``OTHER`` keeps an unrecognised id storable rather than rejected.
    """

    CVE = "cve", "CVE"
    GHSA = "ghsa", "GitHub Security Advisory"
    EUVD = "euvd", "EU Vulnerability Database"
    OSV = "osv", "OSV"
    MAL = "mal", "OpenSSF malicious package"
    PYSEC = "pysec", "PySec"
    RUSTSEC = "rustsec", "RustSec"
    GO = "go", "Go vulnerability database"
    DSA = "dsa", "Debian security advisory"
    DLA = "dla", "Debian LTS advisory"
    USN = "usn", "Ubuntu security notice"
    RHSA = "rhsa", "Red Hat security advisory"
    ALSA = "alsa", "AlmaLinux security advisory"
    ALAS = "alas", "Amazon Linux security advisory"
    SUSE = "suse", "SUSE security update"
    CERT_VU = "cert_vu", "CERT/CC vulnerability note"
    ZDI = "zdi", "Zero Day Initiative"
    EDB = "edb", "Exploit-DB"
    MSRC = "msrc", "Microsoft Security Response Center"
    JVNDB = "jvndb", "JVN iPedia"
    OTHER = "other", "Other"


# Longest-prefix-first so ``GHSA-`` is not shadowed by a shorter token.
_REFERENCE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("CVE-", ReferenceType.CVE),
    ("GHSA-", ReferenceType.GHSA),
    ("EUVD-", ReferenceType.EUVD),
    ("OSV-", ReferenceType.OSV),
    ("MAL-", ReferenceType.MAL),
    ("PYSEC-", ReferenceType.PYSEC),
    ("RUSTSEC-", ReferenceType.RUSTSEC),
    ("GO-", ReferenceType.GO),
    ("DSA-", ReferenceType.DSA),
    ("DLA-", ReferenceType.DLA),
    ("USN-", ReferenceType.USN),
    ("RHSA-", ReferenceType.RHSA),
    ("ALSA-", ReferenceType.ALSA),
    ("ALAS-", ReferenceType.ALAS),
    ("SUSE-SU-", ReferenceType.SUSE),
    ("VU#", ReferenceType.CERT_VU),
    ("ZDI-", ReferenceType.ZDI),
    ("EDB-", ReferenceType.EDB),
    ("MSRC-", ReferenceType.MSRC),
    ("JVNDB-", ReferenceType.JVNDB),
)


def detect_reference_type(identifier: str | None) -> str:
    """Classify an advisory identifier by its prefix, case-insensitively.

    Returns :attr:`ReferenceType.OTHER` for an empty or unrecognised id.
    """
    if not identifier:
        return ReferenceType.OTHER
    upper = identifier.strip().upper()
    for prefix, reference_type in _REFERENCE_PREFIXES:
        if upper.startswith(prefix):
            return reference_type
    return ReferenceType.OTHER


class SecurityAdvisory(models.Model):
    """A workspace's advisory. Zero or more vulnerabilities, zero or more products."""

    class AdvisoryType(models.TextChoices):
        PRODUCT_ADVISORY = "product_advisory", "Product advisory"
        # A notice that names no product: "we investigated CVE-X, nothing we ship
        # is affected", or an infrastructure incident update.
        WORKSPACE_NOTICE = "workspace_notice", "Workspace notice"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class RemediationStatus(models.TextChoices):
        """Where the team is on fixing it, which is not whether it is published.

        A separate axis from ``status`` on purpose: a critical advisory can be
        resolved but still unpublished, or published while the fix is in
        progress, and collapsing the two would make either question
        unanswerable. Also distinct from :class:`AdvisoryProductStatus`, which
        is the per-product VEX assertion rather than the team's workflow.
        """

        IDENTIFIED = "identified", "Identified"
        INVESTIGATING = "investigating", "Investigating"
        FIX_IN_PROGRESS = "fix_in_progress", "Fix in progress"
        RESOLVED = "resolved", "Resolved"
        WONT_FIX = "wont_fix", "Won't fix"

    # Terminal states. Everything else counts as open on the dashboard.
    CLOSED_REMEDIATION_STATUSES = frozenset({RemediationStatus.RESOLVED, RemediationStatus.WONT_FIX})

    class Visibility(models.TextChoices):
        """Same vocabulary as ``Component.Visibility``.

        Orthogonal to :class:`Status` on purpose: an advisory can be published and
        private (regulator notified, nothing outside the workspace), published and
        gated (embargoed customer disclosure), then flipped public.
        """

        PRIVATE = "private", "Private"
        GATED = "gated", "Gated"
        PUBLIC = "public", "Public"

    class Meta:
        db_table = "security_advisories_advisories"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "tracking_id"],
                condition=~Q(tracking_id=""),
                name="security_advisory_unique_tracking_id_per_team",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "status"], name="sec_adv_team_status_idx"),
            models.Index(fields=["team", "advisory_type"], name="sec_adv_team_type_idx"),
            models.Index(fields=["team", "-updated_at"], name="sec_adv_team_updated_idx"),
            # Trust-center query path: status=published, visibility=public.
            models.Index(fields=["team", "status", "visibility"], name="sec_adv_team_status_vis_idx"),
        ]
        verbose_name_plural = "security advisories"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="security_advisories", db_column="workspace_id"
    )

    advisory_type = models.CharField(max_length=20, choices=AdvisoryType.choices, default=AdvisoryType.PRODUCT_ADVISORY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # Denormalised from the latest status_change event rather than walked at
    # read time: the list sorts and filters on it, and deriving it per row would
    # be one events query per advisory on every page load.
    remediation_status = models.CharField(
        max_length=20,
        choices=RemediationStatus.choices,
        default=RemediationStatus.IDENTIFIED,
        help_text="Where the team is on fixing this, kept in step with the latest status_change event",
    )
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.PRIVATE)

    # Set the first time the advisory becomes public and never cleared: evidence of
    # when public disclosure actually happened.
    made_public_at = models.DateTimeField(null=True, blank=True)
    # Human-readable display id (ACME-SA-2026-0001), assigned at first publish and
    # immutable afterwards. Blank until then.
    tracking_id = models.CharField(max_length=50, blank=True, default="")

    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    severity = models.CharField(max_length=10, choices=Severity.choices, blank=True, default="")

    # [{"name", "organization", "summary", "urls": []}]: credit for reporters.
    acknowledgments = models.JSONField(default=list, blank=True)

    published_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.tracking_id or self.id}: {self.title}"

    @property
    def is_externally_visible(self) -> bool:
        """A draft is never visible outside the workspace, whatever ``visibility`` says."""
        return self.status != self.Status.DRAFT and self.visibility != self.Visibility.PRIVATE

    @classmethod
    def allocate_tracking_id(cls, team: Team, *, prefix: str | None = None, year: int | None = None) -> str:
        """Next per-team, per-year tracking id, e.g. ``ACME-SA-2026-0001``.

        The sequence restarts each year, matching CVE and CSAF practice. Callers
        must already hold a lock that serialises concurrent publishes for the team
        (lock the ``Team`` row); there is no counter table to lock instead, and the
        highest existing id for the year is the counter.
        """
        year = year or timezone.now().year
        token = (prefix or (team.name or "").upper()) or "SA"
        token = re.sub(r"[^A-Z0-9]+", "", token.upper())[:12] or "SA"
        stem = f"{token}-SA-{year}-"

        # Descending order plus a lazy iterator means the first row is normally the
        # only one fetched, rather than the whole year's ids. The loop continues
        # only past ids whose tail is not a number, which the allocator never
        # writes. Zero padding keeps the ordering numeric; a team that somehow
        # published past 9999 in one year would read a stale maximum and hit the
        # unique constraint, which fails loudly rather than reusing an id.
        highest = 0
        existing = (
            cls.objects.filter(team=team, tracking_id__startswith=stem)
            .order_by("-tracking_id")
            .values_list("tracking_id", flat=True)
        )
        for value in existing.iterator():
            tail = value[len(stem) :]
            if tail.isdigit():
                highest = int(tail)
                break
        return f"{stem}{highest + 1:04d}"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.status == self.Status.PUBLISHED and not self.published_at:
            errors["published_at"] = "A published advisory must record when it was published."
        if self.published_at and self.status == self.Status.DRAFT:
            errors["status"] = "published_at is set, so the advisory cannot be a draft."

        # The tracking id follows publication rather than the current status: it is
        # assigned at publish, outlives a withdrawal, and never exists before.
        # Keying only on PUBLISHED would let a withdrawn advisory lose its id and a
        # draft hold one, which would also consume a number from the year sequence.
        if (self.status == self.Status.PUBLISHED or self.published_at) and not self.tracking_id:
            errors["tracking_id"] = "A published advisory must have a tracking id."
        if self.status == self.Status.DRAFT and self.tracking_id:
            errors["tracking_id"] = "A draft has no tracking id; publishing assigns it."

        if self.status == self.Status.WITHDRAWN:
            if not self.withdrawn_at:
                errors["withdrawn_at"] = "A withdrawn advisory must record when it was withdrawn."
            if not self.withdrawal_reason.strip():
                errors["withdrawal_reason"] = "Withdrawing an advisory requires a reason."
            if not self.published_at:
                errors["status"] = "Only a published advisory can be withdrawn; delete drafts instead."
        elif self.withdrawn_at or self.withdrawal_reason.strip():
            errors["status"] = "withdrawn_at/withdrawal_reason are set, so status must be withdrawn."

        if self.visibility == self.Visibility.PUBLIC and self.status != self.Status.DRAFT:
            if not self.made_public_at:
                errors["made_public_at"] = "Going public must record when."
        if self.status == self.Status.DRAFT and self.made_public_at:
            # A draft has disclosed nothing. Allowing one to carry the timestamp
            # would let it be backdated and then frozen by the write-once rule at
            # publish, which is the opposite of evidence.
            errors["made_public_at"] = "A draft has not been disclosed; publishing records when."

        # AdvisoryProduct.clean() stops a product joining a notice; this stops the
        # advisory turning into a notice underneath products that already exist.
        if (
            self.advisory_type == self.AdvisoryType.WORKSPACE_NOTICE
            and not self._state.adding
            and AdvisoryProduct.objects.filter(advisory_id=self.pk).exists()
        ):
            errors["advisory_type"] = "This advisory names products, so it cannot become a workspace notice."

        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values("team_id", "tracking_id", "made_public_at").first()
            if previous:
                if previous["tracking_id"] and previous["tracking_id"] != self.tracking_id:
                    errors["tracking_id"] = "tracking_id is immutable once assigned."
                if previous["team_id"] != self.team_id:
                    errors["team"] = "An advisory cannot move between workspaces."
                if previous["made_public_at"] and previous["made_public_at"] != self.made_public_at:
                    # Write-once, not merely non-null: rewriting the timestamp
                    # would rewrite when disclosure happened.
                    errors["made_public_at"] = "made_public_at is a disclosure record and cannot be changed."

        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Normalise before validating: a whitespace-only id would satisfy the
        # published check and sit outside the partial unique's blank exemption,
        # so two of them would collide on nothing a reader can see.
        self.tracking_id = self.tracking_id.strip()
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class AdvisoryVulnerability(models.Model):
    """One vulnerability inside an advisory. A multi-CVE incident is one advisory."""

    class ExploitationStatus(models.TextChoices):
        """Whether the vulnerability is being exploited.

        CRA Article 14 reporting is triggered by *actively exploited*
        vulnerabilities, so the predicate needs a field rather than prose. CSAF
        carries the same signal as ``threats[category=exploit_status]``.
        """

        UNKNOWN = "unknown", "Unknown"
        NONE = "none", "No known exploitation"
        POC = "poc", "Proof of concept"
        SUSPECTED = "suspected", "Suspected exploitation"
        KNOWN_EXPLOITED = "known_exploited", "Known exploited"

    class Meta:
        db_table = "security_advisories_vulnerabilities"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["advisory", "cve_id"],
                condition=~Q(cve_id=""),
                name="security_advisory_unique_cve_per_advisory",
            ),
        ]
        indexes = [
            # Cross-workspace: "who has said something about CVE-X".
            models.Index(fields=["cve_id"], name="sec_adv_vuln_cve_idx"),
            models.Index(fields=["advisory"], name="sec_adv_vuln_advisory_idx"),
        ]
        verbose_name_plural = "advisory vulnerabilities"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    advisory = models.ForeignKey(SecurityAdvisory, on_delete=models.CASCADE, related_name="vulnerabilities")

    # Blank for an issue with no CVE assigned (internal finding, embargoed request).
    # Wide enough that the column never rejects an id CVE_ID_RE accepts: the
    # sequence part has no upper bound, and 20 would already truncate an
    # eleven-digit one.
    cve_id = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    cwe_ids = models.JSONField(default=list, blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, blank=True, default="")
    # [{"version": "3.1", "vector": "CVSS:3.1/...", "base_score": 9.8}]
    cvss_scores = models.JSONField(default=list, blank=True)
    exploitation_status = models.CharField(
        max_length=20, choices=ExploitationStatus.choices, default=ExploitationStatus.UNKNOWN
    )
    discovery_date = models.DateTimeField(null=True, blank=True)
    disclosure_date = models.DateTimeField(null=True, blank=True)
    recommendation = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.cve_id or self.title or self.id

    def clean(self) -> None:
        super().clean()
        if self.cve_id and not CVE_ID_RE.match(self.cve_id):
            raise ValidationError(
                {"cve_id": f"{self.cve_id!r} is not a CVE id (expected CVE-<year>-<four or more digits>)."}
            )
        if not self.cve_id and not self.title.strip():
            raise ValidationError({"title": "A vulnerability needs a CVE id or a title."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class AdvisoryReference(models.Model):
    """A typed external identifier or link.

    Covers both advisory-level references (vendor bulletin, patch notes) and the
    alias ids a vulnerability is also known by. ``vulnerability`` NULL means the
    reference belongs to the advisory itself. ``advisory`` is always set so the
    tenant is one hop away.
    """

    class Category(models.TextChoices):
        """CSAF ``references_t`` categories: who published the thing linked to."""

        EXTERNAL = "external", "External"
        SELF = "self", "Self"

    class Meta:
        db_table = "security_advisories_references"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["advisory"], name="sec_adv_ref_advisory_idx"),
            models.Index(fields=["vulnerability"], name="sec_adv_ref_vuln_idx"),
            models.Index(fields=["reference_type", "external_id"], name="sec_adv_ref_type_extid_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~(Q(external_id="") & Q(url="")),
                name="security_advisory_reference_needs_id_or_url",
            ),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    advisory = models.ForeignKey(SecurityAdvisory, on_delete=models.CASCADE, related_name="references")
    vulnerability = models.ForeignKey(
        AdvisoryVulnerability, on_delete=models.CASCADE, null=True, blank=True, related_name="references"
    )
    reference_type = models.CharField(max_length=20, choices=ReferenceType.choices, default=ReferenceType.OTHER)
    external_id = models.CharField(max_length=100, blank=True, default="")
    url = models.URLField(max_length=2048, blank=True, default="")
    summary = models.CharField(max_length=255, blank=True, default="")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.EXTERNAL)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.external_id or self.url

    def clean(self) -> None:
        super().clean()
        if not self.external_id.strip() and not self.url.strip():
            raise ValidationError({"external_id": "A reference needs an identifier or a URL."})
        if self.vulnerability_id and self.advisory_id:
            owner = AdvisoryVulnerability.objects.filter(pk=self.vulnerability_id).values("advisory_id").first()
            if owner and owner["advisory_id"] != self.advisory_id:
                raise ValidationError({"vulnerability": "The vulnerability belongs to a different advisory."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Normalise first: whitespace-only values would otherwise satisfy both the
        # emptiness check and the CheckConstraint, and would break prefix matching.
        self.external_id = self.external_id.strip()
        self.url = self.url.strip()
        # Classify on write so readers get a typed field instead of re-parsing the
        # id, and re-classify on every write so editing the id cannot strand the
        # old type. A recognised prefix settles the question, so the caller's value
        # survives only for ids no prefix matches, which is the one case where it
        # says something the id does not.
        if self.external_id:
            detected = detect_reference_type(self.external_id)
            if detected != ReferenceType.OTHER:
                self.reference_type = detected
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class AdvisoryProduct(models.Model):
    """A product this advisory covers.

    ``product`` goes NULL when the product is deleted; ``product_name`` keeps the
    published advisory readable. Retiring a product must not rewrite security
    history, and it must not be blocked by an advisory either.
    """

    class Meta:
        db_table = "security_advisories_products"
        ordering = ["product_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["advisory", "product"],
                condition=Q(product__isnull=False),
                name="security_advisory_unique_product_per_advisory",
            ),
        ]
        indexes = [models.Index(fields=["advisory"], name="sec_adv_prod_advisory_idx")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    advisory = models.ForeignKey(SecurityAdvisory, on_delete=models.CASCADE, related_name="products")
    product = models.ForeignKey(
        "core.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="security_advisories"
    )
    product_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.product_name or self.id

    def clean(self) -> None:
        super().clean()
        product = self.product
        if product is not None and self.advisory_id and product.team_id != self.advisory.team_id:
            raise ValidationError({"product": "Cross-tenant advisory product rejected."})
        if self.advisory_id and self.advisory.advisory_type == SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE:
            raise ValidationError({"advisory": "A workspace notice names no products."})
        # Without either, the row names nothing a reader can identify, and publish
        # validation would still count it as a product.
        if product is None and not self.product_name.strip():
            raise ValidationError({"product_name": "A product row needs a product or a name."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Normalise before the snapshot: a whitespace-only name would otherwise
        # skip it and persist as an unreadable row.
        self.product_name = self.product_name.strip()
        product = self.product
        if product is not None and not self.product_name:
            self.product_name = product.name
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class AdvisoryComponent(models.Model):
    """A component this advisory covers, when the product is not the subject.

    A product advisory says "Lithium 1.x is affected". This says "the auth
    library we ship at 1.2.3 is affected", which is the statement a workspace
    needs when the same component sits inside several products, and the one
    :class:`AdvisoryProduct` cannot make.

    Mirrors AdvisoryProduct down to the null behaviour: ``component`` goes NULL
    when the component is deleted and ``component_name`` keeps the published
    advisory readable, because retiring a component must not rewrite security
    history or be blocked by an advisory.
    """

    class Meta:
        db_table = "security_advisories_components"
        ordering = ["component_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["advisory", "component"],
                condition=Q(component__isnull=False),
                name="security_advisory_unique_component_per_advisory",
            ),
        ]
        indexes = [models.Index(fields=["advisory"], name="sec_adv_comp_advisory_idx")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    advisory = models.ForeignKey(SecurityAdvisory, on_delete=models.CASCADE, related_name="components")
    component = models.ForeignKey(
        "core.Component", on_delete=models.SET_NULL, null=True, blank=True, related_name="security_advisories"
    )
    component_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.component_name or self.id

    def clean(self) -> None:
        super().clean()
        component = self.component
        if component is not None and self.advisory_id and component.team_id != self.advisory.team_id:
            raise ValidationError({"component": "Cross-tenant advisory component rejected."})
        if self.advisory_id and self.advisory.advisory_type == SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE:
            raise ValidationError({"advisory": "A workspace notice names no components."})
        # Without either, the row names nothing a reader can identify.
        if component is None and not self.component_name.strip():
            raise ValidationError({"component_name": "A component row needs a component or a name."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.component_name = self.component_name.strip()
        component = self.component
        if component is not None and not self.component_name:
            self.component_name = component.name
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class AdvisoryProductStatus(models.Model):
    """What one vulnerability means for one product. The VEX statement of the model.

    ``advisory_product`` NULL is a portfolio-wide statement, which is how a
    workspace notice says "nothing we ship is affected" without naming products.
    """

    class Status(models.TextChoices):
        """CycloneDX ``analysis.state``. Values are drawn from
        ``triage.TRIAGE_STATES``; labels read the way an advisory reads.

        A subset of that vocabulary: ``risk_accepted`` is deliberately absent.
        It is an internal decision carrying an owner and an expiry, and a
        published advisory saying a workspace accepted the risk on its own
        product is a different statement than the triage state means."""

        EXPLOITABLE = "exploitable", "Affected"
        NOT_AFFECTED = "not_affected", "Not affected"
        FALSE_POSITIVE = "false_positive", "False positive"
        IN_TRIAGE = "in_triage", "Under investigation"
        RESOLVED = "resolved", "Fixed"

    class Justification(models.TextChoices):
        """CycloneDX justifications. Values match ``triage.TRIAGE_JUSTIFICATIONS``."""

        CODE_NOT_PRESENT = "code_not_present", "Code not present"
        CODE_NOT_REACHABLE = "code_not_reachable", "Code not reachable"
        REQUIRES_CONFIGURATION = "requires_configuration", "Requires configuration"
        REQUIRES_DEPENDENCY = "requires_dependency", "Requires dependency"
        REQUIRES_ENVIRONMENT = "requires_environment", "Requires environment"
        PROTECTED_BY_COMPILER = "protected_by_compiler", "Protected by compiler"
        PROTECTED_AT_RUNTIME = "protected_at_runtime", "Protected at runtime"
        PROTECTED_AT_PERIMETER = "protected_at_perimeter", "Protected at perimeter"
        PROTECTED_BY_MITIGATING_CONTROL = "protected_by_mitigating_control", "Protected by mitigating control"

    class Response(models.TextChoices):
        """CycloneDX ``analysis.response``: the machine-readable half of
        ``action_statement``. CycloneDX allows several; an advisory states one."""

        CAN_NOT_FIX = "can_not_fix", "Cannot fix"
        WILL_NOT_FIX = "will_not_fix", "Will not fix"
        UPDATE = "update", "Update"
        ROLLBACK = "rollback", "Rollback"
        WORKAROUND_AVAILABLE = "workaround_available", "Workaround available"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        VEX_IMPORT = "vex_import", "VEX import"

    # States that clear a finding, matching ``vex._SUPPRESSING_STATES``.
    SUPPRESSING_STATES = frozenset({Status.NOT_AFFECTED, Status.FALSE_POSITIVE})

    class Meta:
        db_table = "security_advisories_product_statuses"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["vulnerability", "advisory_product"],
                condition=Q(advisory_product__isnull=False),
                name="security_advisory_unique_status_per_product",
            ),
            models.UniqueConstraint(
                fields=["vulnerability", "advisory_component"],
                condition=Q(advisory_component__isnull=False),
                name="security_advisory_unique_status_per_component",
            ),
            # Portfolio-wide means naming no subject at all. Before components
            # existed, "no product" was enough to say that; now a status with no
            # product may still name a component, and that is not portfolio-wide.
            models.UniqueConstraint(
                fields=["vulnerability"],
                condition=Q(advisory_product__isnull=True) & Q(advisory_component__isnull=True),
                name="security_advisory_unique_portfolio_status",
            ),
            # One subject or the other, never both: the statement would be
            # ambiguous about what it is asserting.
            models.CheckConstraint(
                condition=~(Q(advisory_product__isnull=False) & Q(advisory_component__isnull=False)),
                name="security_advisory_status_one_subject",
            ),
        ]
        indexes = [models.Index(fields=["vulnerability"], name="sec_adv_status_vuln_idx")]
        verbose_name_plural = "advisory product statuses"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    vulnerability = models.ForeignKey(AdvisoryVulnerability, on_delete=models.CASCADE, related_name="product_statuses")
    advisory_product = models.ForeignKey(
        AdvisoryProduct, on_delete=models.CASCADE, null=True, blank=True, related_name="statuses"
    )
    advisory_component = models.ForeignKey(
        AdvisoryComponent, on_delete=models.CASCADE, null=True, blank=True, related_name="statuses"
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_TRIAGE)
    justification = models.CharField(max_length=40, choices=Justification.choices, blank=True, default="")
    response = models.CharField(max_length=25, choices=Response.choices, blank=True, default="")
    impact_statement = models.TextField(blank=True, default="")
    action_statement = models.TextField(blank=True, default="")

    recommended_version = models.CharField(max_length=100, blank=True, default="")
    # Named, not "+": a release has to be able to answer which advisories point
    # at it. The pins were write-only, so "what does this release fix" needed a
    # scan of every range in the workspace.
    recommended_release = models.ForeignKey(
        "core.Release",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advisory_statuses_recommending",
    )

    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    source_vex = models.ForeignKey("sboms.SBOM", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        # Three subjects, not two. Falling through to "All products" whenever
        # advisory_product is unset predates advisory_component and would now
        # print a component-scoped status as portfolio-wide, which is the one
        # reading an operator must not get wrong.
        if self.advisory_product:
            scope = self.advisory_product.product_name
        elif self.advisory_component:
            scope = self.advisory_component.component_name
        else:
            scope = "All products"
        return f"{self.vulnerability}: {self.status} ({scope})"

    @property
    def is_suppressing(self) -> bool:
        return self.status in self.SUPPRESSING_STATES

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.advisory_product_id and self.advisory_component_id:
            errors["advisory_component"] = "A status names a product or a component, not both."

        if self.justification and self.status != self.Status.NOT_AFFECTED:
            errors["justification"] = "A justification only applies to a not_affected status."

        # Both subjects get the same check. Guarding only the product half let a
        # component from another advisory through, which is the same defect the
        # product check exists to stop.
        if self.vulnerability_id and (self.advisory_product_id or self.advisory_component_id):
            vuln_advisory = AdvisoryVulnerability.objects.filter(pk=self.vulnerability_id).values("advisory_id").first()
            subject_field, subject_advisory = "advisory_product", None
            if self.advisory_product_id:
                subject_advisory = (
                    AdvisoryProduct.objects.filter(pk=self.advisory_product_id).values("advisory_id").first()
                )
            else:
                subject_field = "advisory_component"
                subject_advisory = (
                    AdvisoryComponent.objects.filter(pk=self.advisory_component_id).values("advisory_id").first()
                )
            if vuln_advisory and subject_advisory and vuln_advisory["advisory_id"] != subject_advisory["advisory_id"]:
                subject_noun = "product" if subject_field == "advisory_product" else "component"
                errors[subject_field] = f"The vulnerability and the {subject_noun} belong to different advisories."

        if self.source_vex_id:
            # Imported here: sboms imports core, and core is imported above.
            from sbomify.apps.sboms.models import SBOM

            vex_row = SBOM.objects.filter(pk=self.source_vex_id).values("bom_type", "component__team_id").first()
            if vex_row:
                if vex_row["bom_type"] != SBOM.BomType.VEX:
                    errors["source_vex"] = "source_vex must point at a VEX artifact."
                elif self.vulnerability_id:
                    team_id = (
                        AdvisoryVulnerability.objects.filter(pk=self.vulnerability_id)
                        .values_list("advisory__team_id", flat=True)
                        .first()
                    )
                    if team_id and vex_row["component__team_id"] != team_id:
                        errors["source_vex"] = "source_vex belongs to a different workspace."

        # A manually authored row citing a VEX artifact as its origin is incoherent.
        # The reverse is legitimate: source_vex is SET_NULL, so deleting the
        # artifact leaves a vex_import row that remembers how it was written.
        if self.source_vex_id and self.source == self.Source.MANUAL:
            errors["source"] = "A manual status cannot cite a source VEX artifact."

        # A release only names something this status covers when the status
        # resolves to a concrete Product. AdvisoryVersionRange.clean enforces the
        # same rule for its pins; keep the two in step.
        if self.recommended_release_id:
            from sbomify.apps.core.models import Release

            product_id = (
                AdvisoryProduct.objects.filter(pk=self.advisory_product_id).values_list("product_id", flat=True).first()
                if self.advisory_product_id
                else None
            )
            if self.advisory_component_id:
                # A product Release is not this status's subject. The component's
                # own release would be, and that is a different field.
                errors["recommended_release"] = "A component status cannot recommend a product release."
            elif not self.advisory_product_id:
                errors["recommended_release"] = "A portfolio-wide status cannot recommend a release."
            elif not product_id:
                errors["recommended_release"] = "A product with no sbomify record has no releases to recommend."
            else:
                owner = (
                    Release.objects.filter(pk=self.recommended_release_id).values_list("product_id", flat=True).first()
                )
                if owner and owner != product_id:
                    errors["recommended_release"] = "The recommended release belongs to a different product."

        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class AdvisoryVersionRange(models.Model):
    """One contiguous affected interval for a product status.

    Version strings are the source of truth and the Release pins are optional
    sugar: an advisory has to describe versions that predate sbomify or were never
    cut as Releases. When a pin is set and the string is empty, the pin's version
    is copied in, so a deleted Release still leaves a readable range.
    """

    class Meta:
        db_table = "security_advisories_version_ranges"
        ordering = ["created_at"]
        constraints = [
            # OSV: a range carries "fixed" or "last_affected", never both.
            models.CheckConstraint(
                condition=~(~Q(fixed="") & ~Q(last_affected="")),
                name="security_advisory_range_fixed_xor_last_affected",
            ),
            models.CheckConstraint(
                condition=~(Q(introduced="") & Q(fixed="") & Q(last_affected="")),
                name="security_advisory_range_needs_endpoint",
            ),
        ]
        indexes = [models.Index(fields=["product_status"], name="sec_adv_range_status_idx")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    product_status = models.ForeignKey(AdvisoryProductStatus, on_delete=models.CASCADE, related_name="version_ranges")
    # A ``vers`` type token (semver, generic, npm, deb, ...).
    versioning_scheme = models.CharField(max_length=20, default="generic")
    introduced = models.CharField(max_length=100, blank=True, default="")
    fixed = models.CharField(max_length=100, blank=True, default="")
    last_affected = models.CharField(max_length=100, blank=True, default="")

    introduced_release = models.ForeignKey(
        "core.Release",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advisory_ranges_introduced_here",
    )
    fixed_release = models.ForeignKey(
        "core.Release",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advisory_ranges_fixed_here",
    )
    last_affected_release = models.ForeignKey(
        "core.Release",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advisory_ranges_last_affected_here",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    _PIN_FIELDS = (
        ("introduced", "introduced_release"),
        ("fixed", "fixed_release"),
        ("last_affected", "last_affected_release"),
    )

    def __str__(self) -> str:
        start = self.introduced or "*"
        if self.fixed:
            return f"[{start}, {self.fixed})"
        if self.last_affected:
            return f"[{start}, {self.last_affected}]"
        return f"[{start}, *)"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.fixed and self.last_affected:
            errors["last_affected"] = "A range carries fixed or last_affected, not both."
        if not (self.introduced or self.fixed or self.last_affected):
            errors["introduced"] = "A range needs at least one endpoint."

        pinned = [(name, getattr(self, f"{name}_id")) for _, name in self._PIN_FIELDS]
        pinned_ids = [(name, pk) for name, pk in pinned if pk]
        if pinned_ids and self.product_status_id:
            status = (
                AdvisoryProductStatus.objects.filter(pk=self.product_status_id)
                .values("advisory_product_id", "advisory_product__product_id")
                .first()
            )
            if status:
                product_id = status["advisory_product__product_id"]
                if not status["advisory_product_id"]:
                    reason = "A portfolio-wide status cannot pin releases."
                elif not product_id:
                    # ``Release.product`` cascades, so a live pin here was never
                    # orphaned by a product deletion: it points somewhere else.
                    reason = "A product with no sbomify record has no releases to pin."
                else:
                    reason = ""

                if reason:
                    # Key the error to the pins the caller actually set, so a form
                    # highlights the offending field instead of the first one.
                    for name, _pk in pinned_ids:
                        errors[name] = reason
                else:
                    from sbomify.apps.core.models import Release

                    for name, pk in pinned_ids:
                        owner = Release.objects.filter(pk=pk).values_list("product_id", flat=True).first()
                        if owner and owner != product_id:
                            errors[name] = "The pinned release belongs to a different product."

        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Strings are truth; copy a pin's version in when the string is empty.
        for field, pin_field in self._PIN_FIELDS:
            pin = getattr(self, pin_field, None)
            if pin and not getattr(self, field):
                setattr(self, field, pin.version or "")
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class AppendOnlyQuerySet(models.QuerySet["AdvisoryEvent"]):
    """Rejects the bulk paths that would otherwise walk around ``save``/``delete``.

    ``QuerySet.update()`` and ``QuerySet.delete()`` never call model methods, so
    guarding only the instance methods would leave the timeline editable through
    the ORM. Cascades from the advisory still work: Django's collector deletes
    through its own query, not through this manager.
    """

    def update(self, **kwargs: Any) -> int:
        raise ValidationError("Advisory events are append-only.")

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise ValidationError("Advisory events are append-only.")


class AdvisoryEvent(models.Model):
    """Append-only timeline: messages and field changes in one ordering.

    The advisory's history is one story, so comments, status changes and field
    edits share a table rather than being joined back together at read time. New
    event kinds need no migration.
    """

    objects = AppendOnlyQuerySet.as_manager()

    class EventType(models.TextChoices):
        # Internal team discussion. Never leaves the workspace.
        COMMENT = "comment", "Comment"
        # Public-facing progress message, the feed a trust-center visitor reads.
        UPDATE = "update", "Update"
        FIELD_CHANGE = "field_change", "Field change"
        STATUS_CHANGE = "status_change", "Status change"
        VISIBILITY_CHANGED = "visibility_changed", "Visibility changed"
        PUBLISHED = "published", "Published"
        WITHDRAWN = "withdrawn", "Withdrawn"
        VULNERABILITY_ADDED = "vulnerability_added", "Vulnerability added"
        VULNERABILITY_REMOVED = "vulnerability_removed", "Vulnerability removed"
        PRODUCT_ADDED = "product_added", "Product added"
        PRODUCT_REMOVED = "product_removed", "Product removed"
        # CRA Article 14 leaves a reporting trail the advisory has to evidence.
        CRA_EARLY_WARNING = "cra_early_warning", "CRA early warning submitted"
        CRA_NOTIFICATION = "cra_notification", "CRA notification submitted"
        CRA_FINAL_REPORT = "cra_final_report", "CRA final report submitted"
        USERS_NOTIFIED = "users_notified", "Impacted users notified"

    # Event kinds a trust-center visitor may read.
    PUBLIC_EVENT_TYPES = frozenset(
        {EventType.UPDATE, EventType.PUBLISHED, EventType.WITHDRAWN, EventType.STATUS_CHANGE}
    )
    MESSAGE_EVENT_TYPES = frozenset({EventType.COMMENT, EventType.UPDATE})

    class Meta:
        db_table = "security_advisories_events"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["advisory", "created_at"], name="sec_adv_event_advisory_idx")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    advisory = models.ForeignKey(SecurityAdvisory, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # A real column rather than a payload key: messages are searchable.
    body = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d}"

    def clean(self) -> None:
        super().clean()
        if self.event_type in self.MESSAGE_EVENT_TYPES and not self.body.strip():
            # Plural and the human label: "A update event" reads wrong, and the
            # raw value is an internal token.
            raise ValidationError({"body": f"{self.get_event_type_display()} events need a body."})
        if self.event_type == self.EventType.FIELD_CHANGE:
            missing = {"field", "old", "new"} - set(self.payload or {})
            if missing:
                raise ValidationError({"payload": f"A field_change payload needs {sorted(missing)}."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Advisory events are append-only.")
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise ValidationError("Advisory events are append-only.")


def validate_publishable(advisory: SecurityAdvisory) -> list[str]:
    """Reasons an advisory cannot be published yet. Empty list means it can.

    These are the rules that need the whole object graph, so they cannot live in a
    row's ``clean()``. The publish service calls this inside its transaction.
    """
    problems: list[str] = []

    if not advisory.title.strip():
        problems.append("The advisory needs a title.")

    products = list(advisory.products.all())
    # Prefetch the whole status graph: the per-status checks below would otherwise
    # query once per status, so an advisory with many products x vulnerabilities
    # would pay N+1 to validate.
    vulnerabilities = list(
        advisory.vulnerabilities.prefetch_related(
            "product_statuses__advisory_product", "product_statuses__version_ranges"
        )
    )
    is_notice = advisory.advisory_type == SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE

    if is_notice and products:
        problems.append("A workspace notice cannot name products.")
    if not is_notice and not products:
        problems.append("A product advisory needs at least one product.")

    for vulnerability in vulnerabilities:
        statuses = list(vulnerability.product_statuses.all())
        by_product = {status.advisory_product_id for status in statuses}

        if is_notice:
            if None not in by_product:
                problems.append(f"{vulnerability} needs a portfolio-wide status.")
        else:
            if None in by_product:
                problems.append(f"{vulnerability} has a portfolio status on a product advisory.")
            for product in products:
                if product.id not in by_product:
                    problems.append(f"{vulnerability} has no status for {product.product_name}.")

        for status in statuses:
            label = f"{vulnerability} / {status.advisory_product or 'all products'}"
            if status.status == AdvisoryProductStatus.Status.RESOLVED:
                # ``.all()`` reads the prefetch cache; ``.exclude()`` would re-query.
                has_fix = (
                    status.recommended_version
                    or status.recommended_release_id
                    or any(version_range.fixed for version_range in status.version_ranges.all())
                )
                if not has_fix:
                    problems.append(f"{label} is fixed but names no fixed version.")
            if status.status == AdvisoryProductStatus.Status.NOT_AFFECTED:
                if not status.justification and not status.impact_statement.strip():
                    problems.append(f"{label} is not_affected without a justification or impact statement.")
            if status.status == AdvisoryProductStatus.Status.EXPLOITABLE:
                if not status.action_statement.strip() and not vulnerability.recommendation.strip():
                    problems.append(f"{label} is affected but tells users nothing to do.")

    return problems
