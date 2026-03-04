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
