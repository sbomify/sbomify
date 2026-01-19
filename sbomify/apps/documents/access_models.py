from django.contrib.auth import get_user_model
from django.core.validators import MaxLengthValidator
from django.db import models

from sbomify.apps.core.utils import generate_id
from sbomify.apps.teams.models import Team

User = get_user_model()


class AccessRequest(models.Model):
    """Access request for gated components.

    All requests are for blanket access to ALL gated components in a team.
    When approved, user is automatically added as guest member.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        REVOKED = "revoked", "Revoked"

    class Meta:
        db_table = "documents_access_requests"
        unique_together = [("team", "user")]
        indexes = [
            models.Index(fields=["team", "user", "status"]),
            models.Index(fields=["status"]),
            models.Index(fields=["requested_at"]),
        ]
        ordering = ["-requested_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="access_requests")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="access_requests")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Status of the access request",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True, help_text="When the request was approved or rejected")
    decided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decided_access_requests",
        help_text="User who approved or rejected the request",
    )
    revoked_at = models.DateTimeField(null=True, blank=True, help_text="When the access was revoked")
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_access_requests",
        help_text="User who revoked the access",
    )
    notes = models.TextField(
        blank=True,
        validators=[MaxLengthValidator(1000)],
        help_text="Optional notes about the request",
    )

    def __str__(self) -> str:
        return f"AccessRequest {self.id} - {self.user.username} - {self.team.name} - {self.status}"


class NDASignature(models.Model):
    """NDA signature record for access requests.

    Stores the signature details when a user signs an NDA as part of
    requesting access to gated components.
    """

    class Meta:
        db_table = "documents_nda_signatures"
        indexes = [
            models.Index(fields=["access_request"]),
            models.Index(fields=["signed_at"]),
        ]
        ordering = ["-signed_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    access_request = models.OneToOneField(
        AccessRequest,
        on_delete=models.CASCADE,
        related_name="nda_signature",
        help_text="Associated access request",
    )
    nda_document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="nda_signatures",
        help_text="NDA document that was signed",
    )
    nda_content_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 hash of NDA document content at signing time",
    )
    signed_name = models.CharField(max_length=255, help_text="Name provided by user when signing")
    signed_at = models.DateTimeField(auto_now_add=True, help_text="When the NDA was signed")
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="IP address of user when signing")
    user_agent = models.CharField(
        max_length=500,
        blank=True,
        help_text="User agent string of browser when signing",
    )

    def __str__(self) -> str:
        return f"NDASignature {self.id} - {self.signed_name} - {self.signed_at}"

    def is_document_modified(self) -> bool | None:
        """Check if the NDA document has been modified after this signature.

        Compares the stored hash from signing time with the current
        document's content hash.

        Returns:
            True if document has been modified, False if unchanged,
            None if unable to verify.
        """
        if not self.nda_document.content_hash:
            # Document doesn't have a content hash, can't verify
            return None

        return self.nda_content_hash != self.nda_document.content_hash
