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


# PostgreSQL ``bigint`` (the underlying type of ``OIDCBinding.repository_id``
# and ``repository_owner_id``) is signed 64-bit. A coerced Python int that
# exceeds this range would survive ``int()`` (Python ints are unbounded) but
# raise ``DataError`` from psycopg when handed to ``filter()`` below — a 500
# instead of the documented 401. Cap to the positive side: GitHub IDs are
# always positive 32-bit integers in practice, but pinning to int64 keeps the
# bound aligned with the database column.
_MAX_REPO_INT_CLAIM = 2**63 - 1


def _coerce_repo_int_claim(value: Any) -> int | None:
    """Return ``value`` as an ``int`` iff it's a non-negative bigint-sized
    integer expressed exactly the way GitHub emits it (an ASCII-decimal
    string), or a Python ``int`` of the same magnitude.

    GitHub's OIDC tokens encode ``repository_id`` / ``repository_owner_id``
    as JSON strings — ``"74"``, ``"65"``, … — so the str branch is the
    primary path. ``int`` is also accepted because our test factory (and
    conceivably other OIDC providers) may encode them as JSON numbers.

    Rejected (returns ``None`` → caller maps to 401):

    * ``None``, ``bool``, ``float``, ``list``, ``dict`` — wrong JSON type.
      ``bool`` is called out explicitly because in Python ``isinstance(True,
      int)`` is ``True`` and would otherwise let a forged ``"…": true``
      claim through as the integer ``1``.
    * Strings with whitespace, sign prefixes (``"+74"``, ``"-74"``), PEP-515
      underscore separators (``"7_4"``), or non-ASCII decimal digits
      (``"١٢٣"`` etc.) — Python's ``int()`` accepts all of
      these but GitHub never emits any of them, so accepting them only
      widens the input surface for forged tokens.
    * Negative integers — GitHub IDs are always positive.
    * Integers ``> 2**63 - 1`` — would overflow PostgreSQL ``bigint`` when
      handed to ``OIDCBinding.objects.filter(repository_id=…)`` and raise
      a 500 instead of a clean 401.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_REPO_INT_CLAIM else None
    if isinstance(value, str):
        # ``isascii() and isdigit()`` admits only ``"0"`` … ``"9"`` —
        # rejects ``"١"``-style Unicode digits, leading ``+``/``-``,
        # whitespace, and PEP 515 underscores. Also rejects the empty
        # string. Matches GitHub's wire format exactly.
        if not (value.isascii() and value.isdigit()):
            return None
        coerced = int(value)
        return coerced if coerced <= _MAX_REPO_INT_CLAIM else None
    return None


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
        # unlikely — ``binding.id`` comes from ``core.utils.generate_id``,
        # which is a 12-char base62 token (62^12 ≈ 3.2e21, ~72 bits of
        # entropy) — but if it ever happens, the existing user could
        # have a usable password, ``is_active=False``, or other state
        # that would break our invariants. Refuse to take over an
        # unexpected account.
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
    """Resolve (or defer), provision, and persist a new trusted-publisher binding.

    The caller supplies only ``repository_slug`` (``"org/repo"``) — the same
    minimal input for public and private repos. Repo identity is then pinned
    along one of two timelines:

    * **Public repo** — ``resolve_repository`` reads the immutable IDs from
      GitHub's REST API (unauthenticated) and we pin them on the new row now.
    * **Private repo (or any unresolvable-now repo)** — sbomify can't read the
      IDs right now, so the binding is created UNPINNED
      (``repository_id``/``repository_owner_id`` = NULL) and the IDs are pinned
      later, from the first signed OIDC token, in
      ``exchange_github_oidc_token``. This is the path for EVERY
      ``GitHubResolveError`` except ``malformed``: ``not_found`` (private or
      non-existent), ``rate_limited``, and ``unavailable`` all defer. Only a
      ``malformed`` slug (bad ``org/repo`` shape) 400s — it can never resolve.

    Returns a ServiceResult so the caller (view/API) can map outcomes to HTTP
    status without owning any ORM. Two-phase create (binding row first, bot
    provisioned second, FK attached last) is wrapped in ``transaction.atomic``
    so the brief ``bot_user IS NULL`` window never escapes the transaction.
    """
    from sbomify.apps.oidc.models import OIDCBinding

    try:
        resolved = resolve_repository(repository_slug)
    except GitHubResolveError as exc:
        if exc.kind == "malformed":
            # Not a parseable 'org/repo' — never resolvable, so reject outright.
            return ServiceResult.failure(str(exc), status_code=400)
        # not_found (private or non-existent) / rate_limited / unavailable: we
        # can't read the IDs now. Create UNPINNED and pin from the first OIDC
        # token at exchange. The slug shape is already valid (malformed handled
        # above), so normalise the user's input for the display/match name.
        repo_name, repo_id, owner_id = repository_slug.lower(), None, None
    else:
        repo_name, repo_id, owner_id = resolved.repository.lower(), resolved.repository_id, resolved.repository_owner_id

    try:
        with transaction.atomic():
            # Phase 1: INSERT the binding with bot_user=NULL so the
            # generated ``id`` is available to derive the bot's
            # username. The NULL window lives entirely inside this
            # transaction.
            binding = OIDCBinding.objects.create(
                component=component,
                provider=provider,
                repository=repo_name,
                repository_id=repo_id,
                repository_owner_id=owner_id,
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

    # GitHub Actions OIDC tokens ship every numeric identifier as a JSON
    # *string* (``"repository_id": "74"``, ``"repository_owner_id": "65"``,
    # ``"actor_id": "12"`` …) — see the ``Example subject claims`` table
    # in GitHub's OIDC hardening docs. A naive ``isinstance(..., int)``
    # check therefore rejects every real-world token. Coerce defensively:
    # accept ``str`` and ``int`` (some OIDC providers — and our own tests
    # — encode as int), reject everything else including ``bool`` (which
    # would otherwise pass ``int()`` because ``bool`` is an ``int``
    # subclass in Python).
    raw_owner_id = claims.get("repository_owner_id")
    raw_repo_id = claims.get("repository_id")
    repository_owner_id = _coerce_repo_int_claim(raw_owner_id)
    repository_id = _coerce_repo_int_claim(raw_repo_id)
    if repository_owner_id is None or repository_id is None:
        logger.info(
            "OIDC exchange: token missing/invalid repo id claims (repository_owner_id=%r repository_id=%r)",
            raw_owner_id,
            raw_repo_id,
        )
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
        # No pinned (ID-matched) binding. A private repo's binding is created
        # UNPINNED (IDs NULL); pin it now from this verified token, matching on
        # the (also-signed) repository name. Trust-on-first-use: the first valid
        # publish for that name claims the binding and freezes its IDs.
        repo_claim = claims.get("repository")
        repo_name = repo_claim.lower() if isinstance(repo_claim, str) else None
        if repo_name:
            unpinned = (
                OIDCBinding.objects.select_related("bot_user", "component__team")
                .filter(
                    component_id=component_id,
                    provider=OIDCBinding.PROVIDER_GITHUB,
                    repository=repo_name,
                    repository_id__isnull=True,
                )
                .first()
            )
            if unpinned is not None:
                # Guard on BOTH IDs being NULL so two concurrent first-exchanges
                # can't double-pin (the loser's UPDATE touches 0 rows), and a
                # partially-pinned row (only reachable via manual edits/backfills)
                # can't be (re)claimed — the invariant is both pinned together.
                did_pin = OIDCBinding.objects.filter(
                    pk=unpinned.pk, repository_id__isnull=True, repository_owner_id__isnull=True
                ).update(
                    repository_id=repository_id,
                    repository_owner_id=repository_owner_id,
                )
                if did_pin:
                    unpinned.repository_id = repository_id
                    unpinned.repository_owner_id = repository_owner_id
                    binding = unpinned
                    logger.info(
                        "OIDC exchange: pinned binding=%s component=%s repo=%r owner_id=%s repo_id=%s (first use)",
                        unpinned.id,
                        component_id,
                        repo_name,
                        repository_owner_id,
                        repository_id,
                    )
                else:
                    # Lost the race; a concurrent exchange just pinned it. Same
                    # repo ⇒ same IDs, so re-fetch via the now-pinned ID match.
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
