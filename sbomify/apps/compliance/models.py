"""CRA Compliance Wizard models — OSCAL + CRA-specific."""

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
    product_category = models.CharField(max_length=20, choices=ProductCategory.choices, default=ProductCategory.DEFAULT)
    is_open_source_steward = models.BooleanField(default=False)
    conformity_assessment_procedure = models.CharField(
        max_length=20, choices=ConformityProcedure.choices, default=ConformityProcedure.MODULE_A
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
    support_email = models.EmailField(blank=True, default="")
    support_url = models.URLField(blank=True, default="")
    support_phone = models.CharField(max_length=50, blank=True, default="")
    support_hours = models.CharField(max_length=100, blank=True, default="")
    data_deletion_instructions = models.TextField(blank=True, default="")

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
