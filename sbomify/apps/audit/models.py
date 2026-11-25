"""The workspace audit trail.

One row per thing a person, an agent acting for a person, or a CI identity did
in a workspace. The table is append-only, and that is enforced by PostgreSQL,
not by this module: ``db.py`` installs triggers that refuse ``UPDATE`` and
``TRUNCATE`` outright and refuse ``DELETE`` for any row still inside its
workspace's retention window. The ORM guards below only make the mistake fail
early and with a readable message; they are not the control.

The shape follows the common audit-event model (actor, action, target, outcome,
context) used by GitHub, GitLab and the OCSF/CADF schemas:

* **Snapshots, not foreign keys.** ``workspace_id``, ``actor_user_id`` and the
  target columns are plain values. A foreign key would either cascade (deleting
  a user or a workspace would delete the evidence of what they did) or block
  those deletions. The labels are copied at write time so an entry still reads
  correctly after its subject is renamed or deleted.
* **The database sets the time and the hash chain.** The insert trigger
  overwrites ``occurred_at`` with the database clock and computes
  ``chain_seq``, ``prev_hash`` and ``entry_hash``, so an application bug cannot
  backdate an event, and a row edited or removed by someone who can bypass the
  triggers breaks the chain where it happened.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# Retention bounds, in days. The floor keeps an owner from shortening the
# window to zero and purging the record of what they just did; the ceiling is
# ten years, past any common regulatory requirement.
RETENTION_MIN_DAYS = 30
RETENTION_MAX_DAYS = 3650
RETENTION_DEFAULT_DAYS = 365

APPEND_ONLY_MESSAGE = "Audit events are append-only."


class Outcome(models.TextChoices):
    SUCCESS = "success", "Success"
    FAILURE = "failure", "Failure"
    DENIED = "denied", "Denied"


class ActorType(models.TextChoices):
    USER = "user", "User"
    # An AI agent acting for a person: the MCP endpoint, or a REST call made
    # with an AI agent token. ``actor_user_id`` is the person it acts for.
    AGENT = "agent", "Agent"
    # OIDC trusted publishing: a CI pipeline, not a person.
    BOT = "bot", "CI"


class Channel(models.TextChoices):
    WEB = "web", "Web"
    API = "api", "API"
    MCP = "mcp", "MCP"
    CI = "ci", "CI"


class AppendOnlyQuerySet(models.QuerySet["AuditEvent"]):
    """Refuses the bulk paths that skip ``save``/``delete``.

    Retention purges do not go through the ORM: ``services.purge_expired``
    issues the one ``DELETE`` the database trigger will accept.
    """

    def update(self, **kwargs: Any) -> int:
        raise ValidationError(APPEND_ONLY_MESSAGE)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise ValidationError(APPEND_ONLY_MESSAGE)


class AuditEvent(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "audit_events"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["workspace_id", "-occurred_at"], name="audit_ws_time_idx"),
            models.Index(fields=["workspace_id", "action", "-occurred_at"], name="audit_ws_action_idx"),
            models.Index(fields=["workspace_id", "actor_user_id", "-occurred_at"], name="audit_ws_actor_idx"),
            models.Index(fields=["workspace_id", "target_type", "target_id"], name="audit_ws_target_idx"),
            # The retention purge scans by age across every workspace.
            models.Index(fields=["occurred_at"], name="audit_time_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "chain_seq"], name="audit_ws_chain_seq_uniq"),
            models.CheckConstraint(
                condition=models.Q(outcome__in=[value for value, _label in Outcome.choices]),
                name="audit_outcome_is_known",
            ),
            models.CheckConstraint(
                condition=models.Q(actor_type__in=[value for value, _label in ActorType.choices]),
                name="audit_actor_type_is_known",
            ),
        ]

    id = models.BigAutoField(primary_key=True)
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    workspace_id = models.BigIntegerField()
    # Position in the workspace's hash chain. Assigned by the insert trigger.
    chain_seq = models.BigIntegerField(null=True, editable=False)
    # Overwritten with the database clock by the insert trigger.
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)

    # What happened: ``<target>.<verb>``, e.g. ``product.created``.
    action = models.CharField(max_length=100)
    outcome = models.CharField(max_length=16, choices=Outcome.choices, default=Outcome.SUCCESS)

    # Who did it, as they were when they did it.
    actor_type = models.CharField(max_length=16, choices=ActorType.choices, default=ActorType.USER)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    actor_label = models.CharField(max_length=255, blank=True, default="")
    actor_role = models.CharField(max_length=32, blank=True, default="")

    # How they got in.
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.WEB)
    credential_kind = models.CharField(max_length=16, blank=True, default="")
    credential_id = models.CharField(max_length=64, blank=True, default="")

    # What it was done to.
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    target_label = models.CharField(max_length=255, blank=True, default="")

    # Where it came from.
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    http_method = models.CharField(max_length=10, blank=True, default="")
    path = models.CharField(max_length=512, blank=True, default="")
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)

    # Field changes and anything else specific to the action. Never secrets
    # and never artifact content.
    metadata = models.JSONField(default=dict, blank=True)

    prev_hash = models.CharField(max_length=64, blank=True, default="", editable=False)
    entry_hash = models.CharField(max_length=64, blank=True, default="", editable=False)

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_label or self.actor_user_id} @ {self.occurred_at:%Y-%m-%d %H:%M}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(APPEND_ONLY_MESSAGE)
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise ValidationError(APPEND_ONLY_MESSAGE)
