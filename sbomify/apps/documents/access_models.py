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

    @property
    def nda_signature(self) -> "NDASignature | None":
        """The newest live signature — the shape every display consumer reads.

        Was the reverse accessor of a OneToOneField; kept as a property when
        signatures became history-preserving so templates and serializers did
        not have to change. Superseded rows (revoked/rejected requests) are
        history, not a live signature, so they are excluded here.

        Reads the ``nda_signatures`` prefetch cache when one is present, so
        the queue's list view stays a single query.
        """
        cache = getattr(self, "_prefetched_objects_cache", {})
        if "nda_signatures" in cache:
            live = [s for s in cache["nda_signatures"] if s.superseded_at is None]
            return max(live, key=lambda s: s.signed_at) if live else None
        return self.nda_signatures.live().order_by("-signed_at").first()


class NDASignatureQuerySet(models.QuerySet["NDASignature"]):
    def live(self) -> "NDASignatureQuerySet":
        """Signatures that still satisfy the access flow.

        Every "has the user signed?" decision must go through this — a
        superseded row is history (the request was rejected or access
        revoked), and counting it would let a revoked user skip re-signing.
        """
        return self.filter(superseded_at__isnull=True)


class NDASignature(models.Model):
    """NDA signature record for access requests.

    Stores the signature details when a user signs an NDA as part of
    requesting access to gated components.

    A signature is a legal record — who accepted which document version, when,
    from where — so rows are never deleted while their request exists. An
    access request accumulates one row per acceptance (each NDA version signed,
    each re-request after a revocation); ``superseded_at`` marks a signature
    that no longer satisfies the flow (access revoked or request rejected)
    without destroying the evidence of what was agreed to.
    """

    class Meta:
        db_table = "documents_nda_signatures"
        indexes = [
            models.Index(fields=["access_request"]),
            models.Index(fields=["signed_at"]),
        ]
        ordering = ["-signed_at"]
        constraints = [
            # At most one live signature per (request, document): two
            # concurrent signing POSTs must not both insert. Superseded rows
            # are history and may repeat — a user who re-signs the same
            # version after a revocation legitimately creates a second row.
            models.UniqueConstraint(
                fields=["access_request", "nda_document"],
                condition=models.Q(superseded_at__isnull=True),
                name="one_live_signature_per_request_document",
            ),
        ]

    objects = NDASignatureQuerySet.as_manager()

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    access_request = models.ForeignKey(
        AccessRequest,
        on_delete=models.CASCADE,
        related_name="nda_signatures",
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
    superseded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Set when this signature stopped satisfying the access flow — the "
            "request was rejected or access revoked — so a later re-request "
            "must sign again. NULL = live. The row itself is history and is "
            "never deleted while its request exists."
        ),
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
