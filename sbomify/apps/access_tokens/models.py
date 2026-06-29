from django.conf import settings
from django.db import models
from django.utils import timezone


class AccessToken(models.Model):
    class Meta:
        db_table = "access_tokens"
        indexes = [
            models.Index(fields=["team", "user"]),
            # Partial index on non-NULL ``expires_at``. Both OIDC tokens
            # and PATs that opt into an expiry populate the column; only
            # never-expiring tokens (``expires_at IS NULL``) are excluded.
            # The expired-token sweep only ever filters on non-NULL rows,
            # so indexing the NULL population would cost space for no gain.
            models.Index(
                fields=["expires_at"],
                name="access_tokens_expires_at_idx",
                condition=models.Q(expires_at__isnull=False),
            ),
        ]

    encoded_token = models.CharField(max_length=1000, null=False, unique=True)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, null=True, blank=True)
    scopes = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Action scopes — a list of can() action strings, e.g. ['artifact:publish']. "
            "NULL = unscoped full-capability token (legacy default). An action scope can "
            "only narrow access: the user's workspace role and resource attributes still "
            "apply. Workspace scoping is the separate 'team' field."
        ),
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Optional expiry. NULL = never expires. Personal access tokens default to "
            "90 days (user-selectable, may be NULL); OIDC-issued tokens are short-lived "
            "(default 15 min)."
        ),
    )
    allowed_ips = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Optional IP allowlist — a list of IP or CIDR strings (IPv4/IPv6). A request "
            "whose client IP falls outside the list is rejected even with a valid token. "
            "NULL/empty = no restriction (legacy default)."
        ),
    )

    def __str__(self) -> str:
        return f"{self.user_id} - {self.description}"

    @property
    def is_expired(self) -> bool:
        """True once a token with a set ``expires_at`` is past it; False when ``expires_at`` is NULL (never expires)."""
        return self.expires_at is not None and timezone.now() >= self.expires_at
