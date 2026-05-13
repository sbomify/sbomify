"""CRA Compliance Wizard models — OSCAL + CRA-specific."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from sbomify.apps.core.utils import generate_id


class OSCALCatalog(models.Model):
    """Stores an OSCAL catalog (e.g., BSI TR-03183-1).

    Each catalog contains a set of controls that can be assessed.
    The full OSCAL JSON is stored for reference, while individual
    controls are materialized in OSCALControl for querying.
    """

    class Meta:
        db_table = "compliance_oscal_catalogs"
        unique_together = [("name", "version")]
        ordering = ["-created_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=50)
    source_url = models.URLField(blank=True, default="")
    catalog_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"


class OSCALControl(models.Model):
    """Materialized control from an OSCAL catalog.

    Controls are extracted from the catalog JSON and stored individually
    for efficient querying, filtering, and linking to findings.
    """

    class Meta:
        db_table = "compliance_oscal_controls"
        unique_together = [("catalog", "control_id")]
        constraints = [
            # The Part I/II invariant holds across four code paths (schema
            # import, migration 0007 backfill, update_finding gate, and
            # the Alpine badge). Enforce it at the DB layer so a future
            # edit that slips the equivalence through any one of those
            # paths is rejected outright. CRA Art 13(4) / FAQ 4.1.3.
            #
            # The constraint explicitly enumerates both legal
            # combinations — a looser ``~Q(annex_part="part-ii")``
            # version would accept typos like ``"part-iii"`` as long as
            # ``is_mandatory=False``, silently downgrading a
            # vulnerability-handling control whose import flipped the
            # value. The enumerated form fails closed.
            models.CheckConstraint(
                check=(
                    (models.Q(annex_part="part-ii") & models.Q(is_mandatory=True))
                    | (models.Q(annex_part="part-i") & models.Q(is_mandatory=False))
                ),
                name="oscal_control_is_mandatory_iff_part_ii",
            ),
        ]
        indexes = [
            models.Index(fields=["catalog", "group_id"]),
        ]
        ordering = ["sort_order"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    catalog = models.ForeignKey(OSCALCatalog, on_delete=models.CASCADE, related_name="controls")
    control_id = models.CharField(max_length=50)
    group_id = models.CharField(max_length=50)
    group_title = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    description = models.TextField()
    is_mandatory = models.BooleanField(
        default=False,
        help_text="Part II (vulnerability handling) controls are always mandatory (CRA Art 13(4))",
    )

    class AnnexPart(models.TextChoices):
        PART_I = "part-i", "Part I (Essential requirements)"
        PART_II = "part-ii", "Part II (Vulnerability handling)"

    annex_part = models.CharField(
        max_length=10,
        choices=AnnexPart.choices,
        default=AnnexPart.PART_I,
        help_text="Which part of CRA Annex I this control belongs to (part-i or part-ii)",
    )
    sort_order = models.PositiveIntegerField()

    def __str__(self) -> str:
        return f"{self.control_id}: {self.title}"


class OSCALAssessmentResult(models.Model):
    """An assessment result set against an OSCAL catalog.

    Represents a complete assessment session, containing multiple
    findings against individual controls.
    """

    class AssessmentStatus(models.TextChoices):
        IN_PROGRESS = "in-progress", "In Progress"
        COMPLETE = "complete", "Complete"

    class Meta:
        db_table = "compliance_oscal_assessment_results"
        ordering = ["-started_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    catalog = models.ForeignKey(OSCALCatalog, on_delete=models.PROTECT, related_name="assessment_results")
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="oscal_assessment_results")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    assessor = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=AssessmentStatus.choices, default=AssessmentStatus.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    def __str__(self) -> str:
        return f"{self.title} ({self.status})"


class OSCALFinding(models.Model):
    """Individual finding against a control within an assessment.

    Each finding records the assessment status of a single control
    and can have multiple observations as evidence.
    """

    class FindingStatus(models.TextChoices):
        SATISFIED = "satisfied", "Satisfied"
        NOT_SATISFIED = "not-satisfied", "Not Satisfied"
        NOT_APPLICABLE = "not-applicable", "Not Applicable"
        UNANSWERED = "unanswered", "Unanswered"

    class Meta:
        db_table = "compliance_oscal_findings"
        unique_together = [("assessment_result", "control")]
        indexes = [
            models.Index(fields=["assessment_result", "status"]),
        ]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    assessment_result = models.ForeignKey(OSCALAssessmentResult, on_delete=models.CASCADE, related_name="findings")
    control = models.ForeignKey(OSCALControl, on_delete=models.PROTECT, related_name="findings")
    status = models.CharField(max_length=20, choices=FindingStatus.choices, default=FindingStatus.UNANSWERED)
    notes = models.TextField(blank=True, default="")
    justification = models.TextField(
        blank=True,
        default="",
        help_text="Required justification when Part I control is marked not-applicable (CRA Art 13(4))",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.control.control_id}: {self.status}"


class OSCALObservation(models.Model):
    """Evidence linked to a finding.

    Observations provide supporting evidence for findings using
    one of three OSCAL assessment methods: EXAMINE, INTERVIEW, or TEST.
    """

    class ObservationMethod(models.TextChoices):
        EXAMINE = "EXAMINE", "Examine"
        INTERVIEW = "INTERVIEW", "Interview"
        TEST = "TEST", "Test"

    class Meta:
        db_table = "compliance_oscal_observations"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    finding = models.ForeignKey(OSCALFinding, on_delete=models.CASCADE, related_name="observations")
    description = models.TextField()
    method = models.CharField(max_length=20, choices=ObservationMethod.choices)
    evidence_document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    collected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.method} observation for {self.finding}"


# ---------------------------------------------------------------------------
# CRA-specific models
# ---------------------------------------------------------------------------


class CRAAssessment(models.Model):
    """Master CRA compliance wizard record, one per product.

    Tracks the multi-step wizard state and stores answers for every
    step of the CRA compliance assessment workflow.
    """

    class ProductCategory(models.TextChoices):
        DEFAULT = "default", "Default"
        CLASS_I = "class_i", "Class I"
        CLASS_II = "class_ii", "Class II"
        CRITICAL = "critical", "Critical"

    class ConformityProcedure(models.TextChoices):
        MODULE_A = "module_a", "Module A"
        MODULE_B_C = "module_b_c", "Module B+C"
        MODULE_H = "module_h", "Module H"
        EUCC = "eucc", "EUCC"

    class WizardStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETE = "complete", "Complete"
        # Set by ``save_scope_screening`` when the operator edits the scope
        # screening and ``CRAScopeScreening.cra_applies`` flips
        # ``True → False`` while a live assessment exists (issue #921). The
        # assessment is preserved on disk (ADR-004) but every mutation
        # endpoint refuses further edits with 409 until the operator either
        # re-scopes back into CRA-applicable territory (clears the stale
        # flag) or explicitly deletes the assessment. See
        # ``wizard_service.save_scope_screening`` for the transition code.
        STALE = "stale", "Stale (scope changed)"

    class Meta:
        ordering = ["-created_at"]
        db_table = "compliance_cra_assessments"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="cra_assessments")
    product = models.OneToOneField("core.Product", on_delete=models.CASCADE, related_name="cra_assessment")
    oscal_assessment_result = models.OneToOneField(
        OSCALAssessmentResult, on_delete=models.CASCADE, related_name="cra_assessment"
    )

    # Step 1 — Product classification
    intended_use = models.TextField(blank=True, default="")
    target_eu_markets = models.JSONField(default=list)
    support_period_end = models.DateField(null=True, blank=True)
    support_period_short_justification = models.TextField(
        blank=True,
        default="",
        help_text="Required when support period is less than 5 years (CRA Art 13(8))",
    )
    product_category = models.CharField(max_length=20, choices=ProductCategory.choices, default=ProductCategory.DEFAULT)
    is_open_source_steward = models.BooleanField(default=False)
    harmonised_standard_applied = models.BooleanField(
        default=False,
        help_text="Whether a harmonised standard has been applied (CRA Art 32(2)); required for Class I + Module A",
    )
    conformity_assessment_procedure = models.CharField(
        max_length=20, choices=ConformityProcedure.choices, default=ConformityProcedure.MODULE_A
    )
    # RED / EN 18031 applicability. Orthogonal to ``product_category``
    # (which is the CRA risk-tier classification Default/Class I/II/Critical).
    # A product can be Class I AND radio equipment; these flags decide
    # whether the EN 18031 harmonised-standard entries show up on the
    # DoC as presumption-of-conformity evidence. See issue #905 and
    # ``cra-harmonised-standards.json`` for the applies_when rule tree.
    is_radio_equipment = models.BooleanField(
        default=False,
        help_text="Product falls under the EU Radio Equipment Directive — triggers EN 18031-1 applicability.",
    )
    processes_personal_data = models.BooleanField(
        default=False,
        help_text="Product processes personal data under GDPR — triggers EN 18031-2 (privacy) when combined with RED.",
    )
    handles_financial_value = models.BooleanField(
        default=False,
        help_text=(
            "Product handles monetary value or virtual currency — "
            "triggers EN 18031-3 (fraud protection) when combined with RED."
        ),
    )

    # Step 3b — Vulnerability disclosure
    vdp_url = models.URLField(blank=True, default="")
    acknowledgment_timeline_days = models.PositiveIntegerField(null=True, blank=True)
    csirt_contact_email = models.EmailField(blank=True, default="")
    security_contact_url = models.URLField(blank=True, default="")

    # Step 3c — Incident reporting
    csirt_country = models.CharField(max_length=2, blank=True, default="")
    enisa_srp_registered = models.BooleanField(default=False)
    incident_response_plan_url = models.URLField(blank=True, default="")
    incident_response_notes = models.TextField(blank=True, default="")

    # Step 4 — Support & updates
    update_frequency = models.CharField(max_length=30, blank=True, default="")
    update_method = models.CharField(max_length=30, blank=True, default="")
    update_channel_url = models.URLField(blank=True, default="")
    # CharField (not FK) because actual contact details are denormalized into
    # support_email/support_phone and must survive contact deletion.
    support_contact_id = models.CharField(max_length=50, blank=True, default="")
    support_email = models.EmailField(blank=True, default="")
    support_url = models.URLField(blank=True, default="")
    support_phone = models.CharField(max_length=50, blank=True, default="")
    support_hours = models.CharField(max_length=100, blank=True, default="")
    data_deletion_instructions = models.TextField(blank=True, default="")

    # Step 2 — BSI tooling-limitation waivers (issue #907).
    # Maps finding id → {justification: str, waived_at: ISO8601, waived_by: user_id}.
    # Only ``remediation_type=tooling_limitation`` findings may be
    # waived; operator-action findings must be fixed rather than
    # waived because they represent genuine Annex I Part II(1) gaps.
    bsi_waivers = models.JSONField(default=dict, blank=True)

    # Wizard state
    status = models.CharField(max_length=20, choices=WizardStatus.choices, default=WizardStatus.DRAFT)
    current_step = models.PositiveSmallIntegerField(default=1)
    completed_steps = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # ── Signature block (Annex V Section 8) ───────────────────────────
    # Captured once via the wizard's signature pad; stored alongside
    # the assessment so the DoC template can render filled values
    # instead of underscore placeholders. ``signature_image`` carries a
    # base64-encoded PNG data URL (size-capped at the API layer; small
    # canvases produce <30 KB output).
    signature_place = models.CharField(max_length=255, blank=True, default="")
    signature_name = models.CharField(max_length=255, blank=True, default="")
    signature_function = models.CharField(max_length=255, blank=True, default="")
    signature_image = models.TextField(blank=True, default="")
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="User who saved the signature on this assessment.",
    )

    @property
    def is_signed(self) -> bool:
        """Whether the manufacturer signature block is fully captured.

        Mirrors the API's signing rules so that records populated outside
        the API (admin, manual SQL, future migration) don't render as
        "signed" when they have only whitespace text or a stub image
        with no payload. Returns ``True`` only when:

        - every Annex V text field is non-empty after stripping
        - ``signature_image`` carries a non-empty payload after the
          ``data:image/png;base64,`` prefix

        Date is automatic so it's not part of the gate.
        """
        text_fields_ok = all(
            (getattr(self, name) or "").strip() for name in ("signature_place", "signature_name", "signature_function")
        )
        image = self.signature_image or ""
        prefix = "data:image/png;base64,"
        image_has_payload = image.startswith(prefix) and len(image) > len(prefix)
        return text_fields_ok and image_has_payload

    def __str__(self) -> str:
        return f"CRA Assessment for {self.product} ({self.status})"


class CRAGeneratedDocument(models.Model):
    """Document generated by the CRA compliance wizard.

    Each assessment can produce multiple document kinds (VDP, security.txt,
    risk assessment, etc.). Only one document per kind per assessment is kept;
    newer versions overwrite the old record.
    """

    class DocumentKind(models.TextChoices):
        VDP = "vdp", "Vulnerability Disclosure Policy"
        SECURITY_TXT = "security_txt", "security.txt"
        RISK_ASSESSMENT = "risk_assessment", "Risk Assessment"
        EARLY_WARNING = "early_warning", "Early Warning"
        FULL_NOTIFICATION = "full_notification", "Full Notification"
        FINAL_REPORT = "final_report", "Final Report"
        USER_INSTRUCTIONS = "user_instructions", "User Instructions"
        DECOMMISSIONING_GUIDE = "decommissioning_guide", "Decommissioning Guide"
        DECLARATION_OF_CONFORMITY = "declaration_of_conformity", "Declaration of Conformity"

    class Meta:
        db_table = "compliance_cra_generated_documents"
        unique_together = [("assessment", "document_kind")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    assessment = models.ForeignKey(CRAAssessment, on_delete=models.CASCADE, related_name="generated_documents")
    document_kind = models.CharField(max_length=40, choices=DocumentKind.choices)
    storage_key = models.CharField(max_length=500)
    content_hash = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    is_stale = models.BooleanField(default=False)
    generated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.get_document_kind_display()} for {self.assessment}"


class CRAExportPackage(models.Model):
    """ZIP export package for a CRA assessment.

    Contains a snapshot of all generated documents plus metadata,
    packaged for download or submission.
    """

    class Meta:
        ordering = ["-created_at"]
        db_table = "compliance_cra_export_packages"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    assessment = models.ForeignKey(CRAAssessment, on_delete=models.CASCADE, related_name="export_packages")
    storage_key = models.CharField(max_length=500)
    content_hash = models.CharField(max_length=64)
    manifest = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    def __str__(self) -> str:
        return f"Export package {self.pk} for {self.assessment}"


class CRAScopeScreening(models.Model):
    """Pre-wizard scope determination for CRA applicability.

    Captures whether a product falls within CRA scope based on the criteria
    in FAQ Section 1 (citing CRA Art 2-3, Art 21).
    """

    class Meta:
        db_table = "compliance_cra_scope_screenings"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    product = models.OneToOneField("core.Product", on_delete=models.CASCADE, related_name="cra_scope_screening")
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="cra_scope_screenings")

    # FAQ 1.1/1.3 — CRA Art 3(1-2): data connection capability
    has_data_connection = models.BooleanField(
        default=True,
        help_text="Direct or indirect data connection capability (FAQ 1.1, CRA Art 3(1))",
    )

    # FAQ 1.5 — CRA Art 2(1), Recital 15: own-use exclusion
    is_own_use_only = models.BooleanField(
        default=False,
        help_text="Manufactured exclusively for own use, not on EU market (FAQ 1.5, CRA Art 2(1))",
    )

    # FAQ 1.6 — CRA Art 21(1): testing versions
    is_testing_version = models.BooleanField(
        default=False,
        help_text="Testing/pre-release version with non-compliance indication (FAQ 1.6, CRA Art 21(1))",
    )

    # FAQ 1.9 — CRA Art 2(3-5): exempted by other EU legislation
    is_covered_by_other_legislation = models.BooleanField(
        default=False,
        help_text=(
            "Is the product covered by exempted EU legislation (medical devices, motor vehicles, "
            "civil aviation, marine equipment)? (FAQ 1.9, CRA Art 2(3-5))"
        ),
    )
    exempted_legislation_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Which exempted legislation applies (e.g., Regulation 2017/745 — Medical Devices)",
    )

    # FAQ 1.8 — CRA Art 2(2): national security / dual-use
    is_dual_use = models.BooleanField(
        default=False,
        help_text="Is this a dual-use product with both civilian and defence applications? (FAQ 1.8, CRA Art 2(2))",
    )

    screening_notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    @property
    def cra_applies(self) -> bool:
        """Determine if CRA applies based on screening answers.

        CRA applies when all three cumulative conditions are met (FAQ 1.1):
        1. Product with digital elements (has data connection)
        2. Made available on the market (not own-use)
        3. Not covered by exempted legislation

        Testing versions are a special case — CRA scope but relaxed requirements.
        """
        if not self.has_data_connection:
            return False
        if self.is_own_use_only:
            return False
        if self.is_covered_by_other_legislation:
            return False
        return True

    def __str__(self) -> str:
        applies = "in scope" if self.cra_applies else "out of scope"
        return f"CRA Scope Screening for {self.product} ({applies})"
