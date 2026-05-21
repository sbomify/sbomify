"""Service-layer for OIDC bindings and token exchange.

Every ``OIDCBinding`` owns a synthetic ``User`` row that becomes the
actor on ``AccessToken`` records issued by the token-exchange
endpoint. Splitting "synthetic user per binding" from "shared
workspace bot" means audit trails point at the exact ``(provider,
repo)`` that uploaded an artifact — you can answer "which CI binding
pushed this?" without cross-correlation.

Three public services back the HTTP layer:

* ``create_binding(component, provider, repository_slug, requested_by)``
  → ``ServiceResult[OIDCBinding]`` — resolves GitHub IDs, provisions
  the bot user, atomically persists the binding fully populated.
* ``delete_binding(component, binding_id)`` → ``ServiceResult[str]`` —
  removes the binding (post_delete signal reaps the bot User and
  cascades to its AccessToken rows).
* ``exchange_github_oidc_token(component_id, oidc_token)`` →
  ``ServiceResult[ExchangeResult]`` — verifies the OIDC token, matches
  the binding by immutable IDs, mints a short-lived AccessToken row.

Two internal helpers (``provision_bot_user_for_binding``,
``delete_bot_user_for_binding``) handle the bot-User lifecycle. The
delete helper is also wired to ``post_delete`` on ``OIDCBinding`` so
revoking a binding via any path triggers credential cleanup.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import TOKEN_TYPE_OIDC, create_personal_access_token
from sbomify.apps.core.models import User
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.oidc.github_api import GitHubResolveError, resolve_repository
from sbomify.apps.oidc.utils import (
    OIDCExpiredToken,
    OIDCInvalidAudience,
    OIDCInvalidIssuer,
    OIDCInvalidSignature,
    OIDCJWKSUnavailable,
    OIDCVerificationError,
    verify_github_oidc_token,
)
from sbomify.apps.teams.models import Member
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.oidc.models import OIDCBinding
    from sbomify.apps.sboms.models import Component

logger = getLogger(__name__)

# Synthetic-bot identity convention. ``.local`` is the reserved
# special-use TLD per RFC 6761 §6.3 — guarantees the email is not
# routable, so a misconfigured mailer can't accidentally try to deliver
# notifications to "oidc-bot-…@sbomify.local".
BOT_USERNAME_PREFIX = "oidc-bot-"
_BOT_EMAIL_DOMAIN = "sbomify.local"
_BOT_ROLE = "bot"


def _bot_username(binding_id: str) -> str:
    return f"{BOT_USERNAME_PREFIX}{binding_id}"


def _bot_email(binding_id: str) -> str:
    return f"{BOT_USERNAME_PREFIX}{binding_id}@{_BOT_EMAIL_DOMAIN}"


@transaction.atomic
def provision_bot_user_for_binding(binding: "OIDCBinding") -> User:
    """Create (or fetch) the bot User + workspace Member for ``binding``.

    Idempotent. Safe to call from a post_save signal, an admin action,
    or a backfill script. The atomic wrapper ensures we never end up
    with a bot User but no Member (or vice versa) if the second insert
    raises.

    Returns the bot User. The caller (typically the binding-create
    endpoint) should attach it via ``binding.bot_user = user`` and
    save the binding.
    """
    # ``get_user_model()`` returns the same class as the module-top
    # ``from sbomify.apps.core.models import User`` import — the local
    # alias is intentional here to satisfy Django's recommendation
    # against importing the User model directly in code that touches
    # the ORM (lets ``AUTH_USER_MODEL`` swaps continue to work even
    # though sbomify doesn't actually swap it).
    UserModel = get_user_model()
    username = _bot_username(binding.id)
    email = _bot_email(binding.id)

    bot_user, created = UserModel.objects.get_or_create(
        username=username,
        defaults={
            "email": email,
            "first_name": "OIDC",
            "last_name": "Bot",
            "is_active": True,
            "email_verified": False,
        },
    )
    if created:
        logger.info("Provisioned OIDC bot user %s for binding %s", username, binding.id)
    else:
        # Username collision against an existing User. This is extremely
        # unlikely (binding.id is a 12-char alphanumeric token, ~36^12
        # collision space) but if it ever happens, the existing user
        # could have a usable password, ``is_active=False``, or other
        # state that would break our invariants. Refuse to take over
        # an unexpected account.
        if bot_user.email != email or bot_user.first_name != "OIDC" or bot_user.last_name != "Bot":
            raise RuntimeError(
                f"OIDC bot username collision: existing user {username!r} does not look like "
                "a sbomify-provisioned bot. Refusing to take it over."
            )
        logger.warning("Re-using existing OIDC bot user %s for binding %s", username, binding.id)
    # ALWAYS enforce the bot invariants — not just on first create. A
    # previously-leaked / hand-edited bot row might have a usable
    # password or ``is_active=False``; reasserting on every provision
    # keeps the bot non-loginable and live.
    bot_user.set_unusable_password()
    bot_user.is_active = True
    bot_user.save(update_fields=["password", "is_active"])

    # Manually upsert the Member row with the
    # ``_is_oidc_bot_provisioning`` flag set BEFORE save() runs, so the
    # ``forbid_manual_bot_role`` pre_save signal lets it through. At
    # this point the binding's ``bot_user`` FK hasn't been attached
    # yet, so the signal's OIDCBinding-lookup defence would falsely
    # reject without the flag.
    #
    # Race-safety: the get-then-save pattern has a TOCTOU window where
    # a concurrent provision could create the (team, user) row between
    # our ``get`` and ``save``, triggering an IntegrityError on
    # ``unique_together``. We catch and re-fetch to make the upsert
    # idempotent under concurrency.
    #
    # update_or_create semantics (NOT get_or_create): a pre-existing
    # Member row for (team, bot_user) is forced back to role="bot" /
    # is_default_team=False — defends against the binding inheriting
    # a stale elevated role (security finding C-2).
    _upsert_bot_member(team=binding.component.team, user=bot_user)
    return bot_user


def _upsert_bot_member(*, team: Any, user: Any) -> Member:
    """Idempotent + race-safe upsert of the bot's Member row.

    Strategy:

    1. Look up an existing (team, user) Member.
    2. If found, force role + is_default_team back to canonical values
       (with the OIDC-provisioning opt-out flag so the signal lets us).
    3. If not found, construct + save a fresh row with the same flag.
    4. If step 3 raises ``IntegrityError`` (concurrent creator won
       the race), re-fetch and force the canonical values via step 2.
    """
    member = Member.objects.filter(team=team, user=user).first()
    if member is None:
        member = Member(team=team, user=user, role=_BOT_ROLE, is_default_team=False)
        member._is_oidc_bot_provisioning = True  # type: ignore[attr-defined]
        try:
            member.save()
            return member
        except IntegrityError:
            # Concurrent provision won the race; fall through to the
            # found-existing path and re-fetch.
            member = Member.objects.get(team=team, user=user)

    if member.role != _BOT_ROLE or member.is_default_team:
        member.role = _BOT_ROLE
        member.is_default_team = False
        member._is_oidc_bot_provisioning = True  # type: ignore[attr-defined]
        member.save(update_fields=["role", "is_default_team"])
    return member


def delete_bot_user_by_id(bot_user_id: int) -> None:
    """Delete a bot User by its primary key.

    Called from the ``post_delete`` signal on ``OIDCBinding`` with the
    binding's ``bot_user_id``. ID-based deletion is correct under any
    username change — a previous version reconstructed the username
    from ``binding_id`` and would leak the bot + its AccessTokens if
    the convention ever drifted.

    Removing the User cascades to:

    * the ``Member`` row joining the bot to the workspace
    * every ``AccessToken`` row the binding ever issued (FK CASCADE
      on User)

    That last point is the safety property: revoking a binding
    revokes every credential ever derived from it, with no manual
    cleanup step.
    """
    UserModel = get_user_model()  # see ``provision_bot_user_for_binding`` for rationale
    deleted_count, _ = UserModel.objects.filter(pk=bot_user_id).delete()
    if deleted_count:
        logger.info("Removed OIDC bot user pk=%s after binding deletion", bot_user_id)


def delete_bot_user_for_binding(binding_id: str) -> None:
    """Legacy username-based fallback. Kept for idempotency-test compat.

    Prefer ``delete_bot_user_by_id`` in new code — that path is robust
    to username changes.
    """
    UserModel = get_user_model()
    username = _bot_username(binding_id)
    deleted_count, _ = UserModel.objects.filter(username=username).delete()
    if deleted_count:
        logger.info("Removed OIDC bot user %s after binding deletion (legacy fallback)", username)


# ============================================================================
# Public services — wrap orchestration into ServiceResult so views/APIs
# stay thin dispatch layers (sbomify CLAUDE.md mandate).
# ============================================================================


@dataclass(frozen=True)
class ExchangeResult:
    """Successful token-exchange payload."""

    access_token: str
    expires_in_seconds: int
    component_id: str
    binding_id: str


def list_bindings_for_component(component: "Component") -> list["OIDCBinding"]:
    """Return all bindings for ``component``, eager-loading ``created_by``.

    Pure read; doesn't need a ServiceResult wrapper. Lives here so the
    view layer doesn't reach into the ORM directly (CLAUDE.md mandate).
    """
    from sbomify.apps.oidc.models import OIDCBinding

    return list(OIDCBinding.objects.filter(component=component).select_related("created_by").order_by("-created_at"))


def create_binding(
    *,
    component: "Component",
    provider: str,
    repository_slug: str,
    requested_by: User,
) -> ServiceResult["OIDCBinding"]:
    """Resolve, provision, and persist a new trusted-publisher binding.

    Returns a ServiceResult so the caller (view) can map outcomes to
    HTTP status without owning any ORM. Two-phase create (binding row
    first, bot provisioned second, FK attached last) is wrapped in
    ``transaction.atomic`` so the brief ``bot_user IS NULL`` window
    never escapes the transaction.
    """
    from sbomify.apps.oidc.models import OIDCBinding

    try:
        resolved = resolve_repository(repository_slug)
    except GitHubResolveError as exc:
        # 400 for malformed / not_found / rate_limited / unavailable.
        # The ``kind`` attribute of the exception (e.g. "rate_limited")
        # is intentionally NOT propagated through the ``ServiceResult``
        # right now — callers (currently only ``TrustedPublishersView``)
        # render ``str(exc)`` straight into the form field error, which
        # is enough for the user. If a future caller needs to branch on
        # the kind, switch this to a structured failure result rather
        # than re-parsing the message string.
        return ServiceResult.failure(str(exc), status_code=400)

    try:
        with transaction.atomic():
            # Phase 1: INSERT the binding with bot_user=NULL so the
            # generated ``id`` is available to derive the bot's
            # username. The NULL window lives entirely inside this
            # transaction.
            binding = OIDCBinding.objects.create(
                component=component,
                provider=provider,
                repository=resolved.repository.lower(),
                repository_id=resolved.repository_id,
                repository_owner_id=resolved.repository_owner_id,
                bot_user=None,
                created_by=requested_by,
            )
            # Phase 2: provision the bot User + Member.
            bot = provision_bot_user_for_binding(binding)
            # Phase 3: attach.
            binding.bot_user = bot
            binding.save(update_fields=["bot_user"])
    except IntegrityError:
        return ServiceResult.failure(
            "This repository is already bound to this component.",
            status_code=409,
        )

    return ServiceResult.success(binding)


def delete_binding(*, component: "Component", binding_id: str) -> ServiceResult[str]:
    """Remove a binding and (via cascade) every token it ever issued."""
    from sbomify.apps.oidc.models import OIDCBinding

    binding = OIDCBinding.objects.filter(component=component, pk=binding_id).first()
    if binding is None:
        return ServiceResult.failure("Trusted publisher not found.", status_code=404)

    repo_label = binding.repository
    binding.delete()
    return ServiceResult.success(repo_label)


def exchange_github_oidc_token(*, component_id: str, oidc_token: str) -> ServiceResult[ExchangeResult]:
    """Verify a GitHub OIDC token and mint a short-lived sbomify AccessToken.

    Maps every failure to a ``ServiceResult.failure`` with the HTTP
    status the caller should return. The status taxonomy matches the
    one documented on ``apis.github_token_exchange``.

    Sparse error messages are deliberate — see security-auditor finding
    on not leaking which sub-check failed.
    """
    from sbomify.apps.oidc.models import OIDCBinding
    from sbomify.apps.sboms.models import Component

    if not Component.objects.filter(pk=component_id).exists():
        return ServiceResult.failure("component not found", status_code=404)

    try:
        claims = verify_github_oidc_token(oidc_token)
    except OIDCJWKSUnavailable as exc:
        logger.warning("OIDC exchange: GitHub JWKS unavailable: %s", exc)
        return ServiceResult.failure("OIDC verification temporarily unavailable", status_code=503)
    except (OIDCInvalidSignature, OIDCInvalidIssuer, OIDCInvalidAudience, OIDCExpiredToken) as exc:
        logger.info("OIDC exchange: token rejected (%s): %s", type(exc).__name__, exc)
        return ServiceResult.failure("invalid OIDC token", status_code=401)
    except OIDCVerificationError as exc:
        logger.warning("OIDC exchange: unexpected verification error: %s", exc)
        return ServiceResult.failure("invalid OIDC token", status_code=401)

    repository_owner_id = claims.get("repository_owner_id")
    repository_id = claims.get("repository_id")
    if not isinstance(repository_owner_id, int) or not isinstance(repository_id, int):
        return ServiceResult.failure("invalid OIDC token", status_code=401)

    binding = (
        OIDCBinding.objects.select_related("bot_user", "component__team")
        .filter(
            component_id=component_id,
            provider=OIDCBinding.PROVIDER_GITHUB,
            repository_owner_id=repository_owner_id,
            repository_id=repository_id,
        )
        .first()
    )
    if binding is None:
        # %r (repr-quoted) defends log aggregators against injection from
        # the attacker-controlled ``repository`` claim — security H-3.
        logger.info(
            "OIDC exchange: no binding for component=%s owner_id=%s repo_id=%s repository=%r",
            component_id,
            repository_owner_id,
            repository_id,
            claims.get("repository"),
        )
        return ServiceResult.failure("repository not bound to this component", status_code=403)

    ttl_seconds = int(getattr(settings, "OIDC_TOKEN_TTL_SECONDS", 900))
    now = timezone.now()
    expires_at = now + datetime.timedelta(seconds=ttl_seconds)

    if binding.bot_user is None:
        # Defensive: the bot_user nullable window should never escape
        # ``create_binding``'s atomic block, but if data integrity is
        # somehow violated we'd rather 503 than mint a malformed token.
        logger.error("OIDC exchange: binding %s has no bot_user — data integrity error", binding.id)
        return ServiceResult.failure("OIDC verification temporarily unavailable", status_code=503)

    sbomify_jwt = create_personal_access_token(
        binding.bot_user,
        expires_at=expires_at.timestamp(),
        token_type=TOKEN_TYPE_OIDC,
    )
    with transaction.atomic():
        AccessToken.objects.create(
            encoded_token=sbomify_jwt,
            description=f"oidc:github:{binding.id}",
            user=binding.bot_user,
            team=binding.component.team,
            expires_at=expires_at,
        )
        OIDCBinding.objects.filter(pk=binding.pk).update(last_used_at=now)

    logger.info(
        "OIDC exchange: issued token for binding=%s component=%s repo=%r ttl=%ds",
        binding.id,
        component_id,
        claims.get("repository"),
        ttl_seconds,
    )
    return ServiceResult.success(
        ExchangeResult(
            access_token=sbomify_jwt,
            expires_in_seconds=ttl_seconds,
            component_id=component_id,
            binding_id=binding.id,
        )
    )
