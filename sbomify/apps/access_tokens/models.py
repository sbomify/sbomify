from django.conf import settings
from django.db import models
from django.utils import timezone


class AccessToken(models.Model):
    class Meta:
        db_table = "access_tokens"
        indexes = [
            models.Index(fields=["team", "user"]),
            # Partial index — only OIDC-issued tokens set ``expires_at``.
            # A full index would store a NULL entry for every PAT
            # (the dominant row count) for no payoff; this one stays
            # ~100x smaller in steady state and serves the only query
            # that actually filters on the column (expired-token sweep).
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
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Optional expiry. NULL = never expires (personal access tokens). "
            "Set for OIDC-issued tokens which are short-lived (default 15 min)."
        ),
    )

    def __str__(self) -> str:
        return f"{self.user_id} - {self.description}"

    @property
    def is_expired(self) -> bool:
        """True for OIDC tokens past their expiry; False for PATs (no expiry)."""
        return self.expires_at is not None and timezone.now() >= self.expires_at
