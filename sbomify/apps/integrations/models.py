"""One row per workspace per external tool it has connected.

A workspace's compliance programme usually already lives somewhere else. This
app reads that programme and republishes the part of it the workspace chooses
to show, so the trust center can be true without anyone retyping it.

The connection is the only thing stored here. What comes back over it is
written into the models that already own the concept: a framework becomes a
``controls.ControlCatalog``, a control becomes a ``controls.Control``, and its
state becomes a ``controls.ControlStatus``. Nothing downstream has to know a
provider exists, and the trust center renders synced and hand-maintained
frameworks through exactly the same path.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from sbomify.apps.core.utils import generate_id

# An access token is refreshed this long before it actually expires, so a sync
# that starts just under the wire does not lose its credential halfway through.
TOKEN_REFRESH_LEEWAY = timedelta(minutes=5)


class Integration(models.Model):
    """A workspace's live connection to one provider.

    Credentials are stored as issued, which is the same treatment
    ``vulnerability_scanning.DependencyTrackServer.api_key`` gets: they are
    secrets held for a server-to-server call, and no form of them reaches a
    template, an API schema or a log line. Not even a redacted tail: the access
    token rotates hourly, so one would identify nothing and only invite
    somebody to render a credential on a settings page.
    """

    class Provider(models.TextChoices):
        VANTA = "vanta", "Vanta"
        SLACK = "slack", "Slack"

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        # The refresh token was rejected. Nothing can be synced until someone
        # goes through the provider's consent screen again, so this is a
        # separate state from a sync that merely failed.
        REVOKED = "revoked", "Needs reconnecting"

    class SyncStatus(models.TextChoices):
        NEVER = "never", "Not synced yet"
        RUNNING = "running", "Syncing"
        OK = "ok", "Synced"
        FAILED = "failed", "Failed"

    class Meta:
        db_table = "integrations_integration"
        constraints = [
            models.UniqueConstraint(fields=["team", "provider"], name="unique_workspace_provider"),
        ]
        ordering = ["provider"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    team = models.ForeignKey(
        "teams.Workspace", on_delete=models.CASCADE, related_name="integrations", db_column="workspace_id"
    )
    provider = models.CharField(max_length=32, choices=Provider.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONNECTED)

    access_token = models.TextField(blank=True, default="")
    refresh_token = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(default=list, blank=True)
    # Who the credential belongs to, as the provider names it (a Slack
    # workspace's id and name). Shown on the tile, so an admin with more than
    # one account at the provider can tell which one is connected.
    account = models.JSONField(default=dict, blank=True)

    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    connected_at = models.DateTimeField(default=timezone.now)

    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, choices=SyncStatus.choices, default=SyncStatus.NEVER)
    last_sync_error = models.TextField(blank=True, default="")
    last_sync_summary = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.get_provider_display()} ({self.team.key})"

    @property
    def token_is_stale(self) -> bool:
        """Whether the access token needs refreshing before the next call.

        A connection with no recorded expiry is treated as stale rather than
        as fresh: refreshing an already-valid token costs one request, while
        using a dead one costs the whole sync.
        """
        if not self.access_token:
            return True
        if self.token_expires_at is None:
            return True
        return timezone.now() >= self.token_expires_at - TOKEN_REFRESH_LEEWAY


class NotificationRoute(models.Model):
    """One kind of news a workspace sends to one channel of a connection.

    A row per event rather than a channel with a set of events: what an admin
    chooses is "where does the VEX queue go", and a unique event per connection
    makes that one answer instead of a set of channels to reconcile.

    The channel name is kept beside its id because the provider only knows a
    channel by id, and listing them all again to label one row on the settings
    page is a request per page load. A rename in the provider shows up the next
    time somebody picks the channel.
    """

    class Event(models.TextChoices):
        VEX_SUBMISSIONS = "vex_submissions", "VEX approval queue"
        DAILY_DIGEST = "daily_digest", "Daily vulnerability digest"
        NEW_VULNERABILITIES = "new_vulnerabilities", "New vulnerabilities"

    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical only"
        HIGH = "high", "High and above"
        MEDIUM = "medium", "Medium and above"
        LOW = "low", "All severities"

    class Meta:
        db_table = "integrations_notification_route"
        constraints = [
            models.UniqueConstraint(fields=["integration", "event"], name="unique_integration_event"),
        ]
        ordering = ["event"]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="routes")
    event = models.CharField(max_length=32, choices=Event.choices)
    channel_id = models.CharField(max_length=64)
    channel_name = models.CharField(max_length=255, blank=True, default="")
    # The least severe vulnerability worth a message. Only new vulnerabilities
    # read it: a first scan of a large SBOM opens hundreds at once, and a
    # channel that hears about every low is a channel nobody reads.
    min_severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.HIGH)

    last_delivered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.get_event_display()} to {self.channel_name or self.channel_id}"
