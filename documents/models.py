from django.db import models

from core.utils import generate_id
from sboms.models import Component


class Document(models.Model):
    """Represents a document artifact associated with a component.

    Documents can be versioned artifacts like specifications, manuals,
    reports, or any other document type associated with a software component.
    """

    class Meta:
        db_table = "documents_documents"
        ordering = ["-created_at"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    name = models.CharField(max_length=255, blank=False)  # document name
    version = models.CharField(max_length=255, default="")  # document version
    document_filename = models.CharField(max_length=255, default="")  # stored filename
    created_at = models.DateTimeField(auto_now_add=True)
    # Where the document came from (file-upload, api, etc)
    source = models.CharField(max_length=255, null=True)
    component = models.ForeignKey(Component, on_delete=models.CASCADE)

    # Additional document-specific fields
    document_type = models.CharField(
        max_length=100, blank=True, help_text="Type of document (e.g., specification, manual, report, compliance)"
    )
    description = models.TextField(blank=True)
    content_type = models.CharField(max_length=100, blank=True)  # MIME type
    file_size = models.PositiveIntegerField(null=True, blank=True)  # File size in bytes

    def __str__(self) -> str:
        return self.name

    @property
    def public_access_allowed(self) -> bool:
        """Check if public access is allowed for this document.

        Returns:
            True if the component is public, False otherwise.
        """
        return self.component.is_public

    @property
    def source_display(self) -> str:
        """Return a user-friendly display name for the source.

        Returns:
            A human-readable string representing the document source.
        """
        source_display_map = {
            "api": "API",
            "manual_upload": "Manual Upload",
        }
        return source_display_map.get(self.source, self.source or "Unknown")
