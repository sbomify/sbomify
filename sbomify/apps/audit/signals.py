"""Turning model changes and sign-ins into audit events.

Every model a person changes in a workspace is listed in ``TRACKED``. A create,
an update that touches a listed field, and a delete each become one event,
attributed to whoever the open ``AuditContext`` names. Changes made with no
context open are background work, not user activity, and are skipped.

Receivers are connected once, without a sender, and look the instance's
concrete model up here. That is what makes proxy models (``core.Product`` over
``sboms.Product``) count: Django sends ``post_save`` with the proxy class as
sender, so a receiver bound to the concrete class would never hear them.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save

from .context import current
from .recorder import Target, record, workspace_has_audit_log


@dataclass(frozen=True)
class Tracked:
    #: ``app_label.ModelName`` of the concrete model.
    model: str
    #: The target type and the first half of the action, e.g. ``product``.
    name: str
    workspace: Callable[[Any], int | None]
    label: Callable[[Any], str]
    #: Fields whose changes are recorded, old and new value both.
    fields: tuple[str, ...] = ()
    #: Fields whose changes are recorded by name only: the value is a secret
    #: or too large to belong in a log line.
    redacted: tuple[str, ...] = ()

    @property
    def watched(self) -> tuple[str, ...]:
        return self.fields + self.redacted


def _team(instance: Any) -> int | None:
    return getattr(instance, "team_id", None)


def _via_component(instance: Any) -> int | None:
    component = getattr(instance, "component", None)
    return getattr(component, "team_id", None)


def _via_product(instance: Any) -> int | None:
    product = getattr(instance, "product", None)
    return getattr(product, "team_id", None)


def _name(instance: Any) -> str:
    return str(getattr(instance, "name", "") or "")


def _user_email(instance: Any) -> str:
    user = getattr(instance, "user", None)
    return str(getattr(user, "email", "") or getattr(user, "username", "") or "")


TRACKED: tuple[Tracked, ...] = (
    Tracked(
        "teams.Workspace",
        "workspace",
        workspace=lambda w: w.pk,
        label=_name,
        fields=(
            "name",
            "slug",
            "is_public",
            "billing_plan",
            "custom_domain",
            "tea_enabled",
            "publish_vulnerability_posture",
            "sbom_freshness_days",
            "default_support_period_years",
            "advisory_id_prefix",
            "advisory_id_start_at",
            "audit_log_retention_days",
        ),
        redacted=("branding_info", "security_txt_config", "patch_sla_days"),
    ),
    Tracked(
        "teams.Member",
        "member",
        workspace=_team,
        label=_user_email,
        fields=("role", "user_id"),
    ),
    Tracked(
        "teams.Invitation",
        "invitation",
        workspace=_team,
        label=lambda i: str(i.email),
        fields=("email", "role"),
    ),
    Tracked(
        "teams.ContactProfile",
        "contact_profile",
        workspace=_team,
        label=_name,
        fields=("name", "is_default", "is_component_private"),
    ),
    Tracked(
        "access_tokens.AccessToken",
        "access_token",
        workspace=_team,
        label=lambda t: str(t.description),
        fields=("description", "scopes", "expires_at"),
    ),
    Tracked(
        "sboms.Product",
        "product",
        workspace=_team,
        label=_name,
        fields=("name", "is_public", "release_date", "end_of_support", "end_of_life"),
        redacted=("description", "custom_metadata"),
    ),
    Tracked(
        "sboms.Component",
        "component",
        workspace=_team,
        label=_name,
        fields=("name", "component_type", "visibility", "gating_mode", "contact_profile_id"),
    ),
    Tracked(
        "sboms.ProductComponent",
        "product_component",
        workspace=_via_product,
        label=lambda pc: f"{_name(pc.product)} / {_name(pc.component)}",
        fields=("product_id", "component_id"),
    ),
    Tracked(
        "sboms.SBOM",
        "artifact",
        workspace=_via_component,
        label=lambda s: f"{_name(s)} {getattr(s, 'version', '')}".strip(),
        fields=("name", "version", "bom_type", "format", "format_version", "component_id"),
    ),
    Tracked(
        "documents.Document",
        "document",
        workspace=_via_component,
        label=lambda d: f"{_name(d)} {getattr(d, 'version', '')}".strip(),
        fields=("name", "version", "document_type", "component_id"),
        redacted=("description",),
    ),
    Tracked(
        "core.Release",
        "release",
        workspace=_via_product,
        label=_name,
        fields=("name", "version", "is_latest", "is_prerelease", "released_at", "product_id"),
        redacted=("description",),
    ),
    Tracked(
        "oidc.OIDCBinding",
        "trusted_publisher",
        workspace=_via_component,
        label=lambda b: str(getattr(b, "repository", "") or ""),
        fields=("provider", "repository", "component_id"),
    ),
    Tracked(
        "security_advisories.SecurityAdvisory",
        "advisory",
        workspace=_team,
        label=lambda a: str(getattr(a, "tracking_id", "") or a.title),
        fields=("title", "status", "visibility", "severity", "remediation_status", "tracking_id"),
        redacted=("summary", "description"),
    ),
    Tracked(
        "integrations.Integration",
        "integration",
        workspace=_team,
        label=lambda i: str(i.provider),
        fields=("provider", "status"),
        redacted=("client_id", "client_secret", "access_token", "refresh_token"),
    ),
)

_BY_MODEL: dict[type, Tracked] = {}


def _resolve_registry() -> None:
    for tracked in TRACKED:
        app_label, model_name = tracked.model.split(".")
        _BY_MODEL[apps.get_model(app_label, model_name)._meta.concrete_model] = tracked


def _concrete(obj: Any) -> type | None:
    """The concrete model of an instance or a queryset."""
    model = obj.model if isinstance(obj, QuerySet) else type(obj)
    meta = getattr(model, "_meta", None)
    return meta.concrete_model if meta is not None else None


def tracked_for(obj: Any) -> Tracked | None:
    concrete = _concrete(obj)
    return _BY_MODEL.get(concrete) if concrete is not None else None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def _attname(instance: Any, field_name: str) -> str:
    """``team_id`` stays ``team_id``; a plain field name maps to its column attribute."""
    try:
        return str(instance._meta.get_field(field_name).attname)
    except Exception:
        return field_name


def _values(instance: Any, tracked: Tracked) -> dict[str, Any]:
    return {name: getattr(instance, _attname(instance, name), None) for name in tracked.watched}


def _workspace_of(instance: Any, tracked: Tracked) -> int | None:
    try:
        workspace_id = tracked.workspace(instance)
        return int(workspace_id) if workspace_id is not None else None
    except Exception:
        # A related row already gone mid-cascade: nothing to attribute it to.
        return None


def _label_of(instance: Any, tracked: Tracked) -> str:
    try:
        return tracked.label(instance)[:255]
    except Exception:
        return ""


def _active(instance: Any) -> tuple[Tracked, int] | None:
    """The registry entry and workspace for ``instance``, if this change should be recorded."""
    ctx = current()
    if ctx is None:
        return None
    tracked = tracked_for(instance)
    if tracked is None:
        return None
    workspace_id = _workspace_of(instance, tracked)
    if workspace_id is None or not workspace_has_audit_log(workspace_id, ctx):
        return None
    return tracked, workspace_id


def on_pre_save(sender: Any, instance: Any, raw: bool = False, update_fields: Any = None, **kwargs: Any) -> None:
    if raw or instance._state.adding:
        return
    tracked = tracked_for(instance)
    if tracked is None or not tracked.watched:
        return
    if update_fields is not None and not set(update_fields) & {
        *tracked.watched,
        *(_attname(instance, f) for f in tracked.watched),
    }:
        return
    if _active(instance) is None:
        return
    before = (
        type(instance)
        ._base_manager.filter(pk=instance.pk)
        .values(*(_attname(instance, name) for name in tracked.watched))
        .first()
    )
    if before is not None:
        instance._audit_before = {name: before[_attname(instance, name)] for name in tracked.watched}


def on_post_save(sender: Any, instance: Any, created: bool = False, raw: bool = False, **kwargs: Any) -> None:
    if raw:
        return
    active = _active(instance)
    if active is None:
        return
    tracked, workspace_id = active
    target = Target(tracked.name, str(instance.pk), _label_of(instance, tracked))

    if created:
        after = _values(instance, tracked)
        initial: dict[str, Any] = {
            "fields": {name: _json_safe(after[name]) for name in tracked.fields if after[name] not in (None, "")}
        }
        record(f"{tracked.name}.created", workspace=workspace_id, target=target, metadata=initial)
        return

    before = instance.__dict__.pop("_audit_before", None)
    if before is None:
        return
    after = _values(instance, tracked)
    changes = {
        name: {"from": _json_safe(before[name]), "to": _json_safe(after[name])}
        for name in tracked.fields
        if before[name] != after[name]
    }
    changed_redacted = [name for name in tracked.redacted if before[name] != after[name]]
    if not changes and not changed_redacted:
        return
    metadata: dict[str, Any] = {"changes": changes}
    if changed_redacted:
        metadata["changed"] = changed_redacted
    record(f"{tracked.name}.updated", workspace=workspace_id, target=target, metadata=metadata)


def _cascaded(instance: Any, origin: Any) -> bool:
    """True when ``instance`` goes because another tracked row was deleted.

    That row's own event covers it: deleting a product does not also log each
    of its links.
    """
    if origin is None or origin is instance:
        return False
    return _concrete(origin) is not _concrete(instance) and tracked_for(origin) is not None


def on_pre_delete(sender: Any, instance: Any, origin: Any = None, **kwargs: Any) -> None:
    if _cascaded(instance, origin):
        return
    # Resolved while the row and its parents still exist: once the delete has
    # run, a deleted workspace no longer has a plan to check, and a deleted
    # component no longer has a workspace.
    if _active(instance) is not None:
        instance._audit_workspace_id = _workspace_of(instance, tracked_for(instance))  # type: ignore[arg-type]


def on_post_delete(sender: Any, instance: Any, origin: Any = None, **kwargs: Any) -> None:
    if _cascaded(instance, origin):
        return
    tracked = tracked_for(instance)
    workspace_id = instance.__dict__.pop("_audit_workspace_id", None)
    if tracked is None or workspace_id is None:
        return
    record(
        f"{tracked.name}.deleted",
        workspace=workspace_id,
        target=Target(tracked.name, str(instance.pk), _label_of(instance, tracked)),
    )


def _internal_workspaces(user: Any) -> list[int]:
    from sbomify.apps.teams.models import Member

    return list(Member.objects.filter(user=user).exclude(role="guest").values_list("team_id", flat=True))


def on_user_logged_in(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    for workspace_id in _internal_workspaces(user):
        record(
            "auth.signed_in",
            workspace=workspace_id,
            actor=user,
            target=Target("user", str(user.pk), str(getattr(user, "email", "") or "")),
        )


def on_user_logged_out(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    if user is None:
        return
    for workspace_id in _internal_workspaces(user):
        record(
            "auth.signed_out",
            workspace=workspace_id,
            actor=user,
            target=Target("user", str(user.pk), str(getattr(user, "email", "") or "")),
        )


def connect() -> None:
    _resolve_registry()
    pre_save.connect(on_pre_save, dispatch_uid="audit_pre_save")
    post_save.connect(on_post_save, dispatch_uid="audit_post_save")
    pre_delete.connect(on_pre_delete, dispatch_uid="audit_pre_delete")
    post_delete.connect(on_post_delete, dispatch_uid="audit_post_delete")
    user_logged_in.connect(on_user_logged_in, dispatch_uid="audit_user_logged_in")
    user_logged_out.connect(on_user_logged_out, dispatch_uid="audit_user_logged_out")
