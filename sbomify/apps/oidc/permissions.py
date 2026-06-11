"""Permission helpers for OIDC-issued AccessTokens.

The existing ``verify_item_access`` (sbomify/apps/core/utils.py) handles
session + PAT auth and checks that the actor has one of
``allowed_roles`` on the item's team. For OIDC trusted-publishing
tokens we need a tighter check: the bot may be a Member of the
workspace at ``role="bot"``, but it must NOT be allowed to operate
on any component other than the one its binding pins.

Two-step pattern at the call site::

    if not can(request, "artifact:publish", component):
        return 403, ...
    if not is_authorised_for_component(request, component):
        return 403, ...

The two checks are independent:

* ``can(..., "artifact:publish", ...)`` enforces the workspace role
  (owner/admin/bot, via ``verify_item_access``; covers session + PAT +
  bot membership). For PATs / sessions this is the whole picture.
* ``is_authorised_for_component`` is a no-op for PATs / sessions; for
  OIDC tokens it locks the bot to its bound component_id.
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.access_tokens.models import AccessToken


def _lookup_binding(request: Any) -> Any:
    """Return the OIDCBinding row that owns the request's token user, or None."""
    token_record: AccessToken | None = getattr(request, "access_token_record", None)
    if token_record is None or token_record.user_id is None:
        return None
    # ``oidc_binding`` is the reverse-side related_name on
    # ``OIDCBinding.bot_user`` (OneToOne). Looked up via the model so mypy
    # sees the type. We key on ``user_id`` (FK column) rather than
    # ``user`` so we don't trigger the lazy User fetch — auth only
    # ``select_related("team")``, so accessing ``user`` would issue an
    # extra round-trip per request that hit this predicate.
    from sbomify.apps.oidc.models import OIDCBinding

    return OIDCBinding.objects.filter(bot_user_id=token_record.user_id).only("component_id").first()


def _cached_binding(request: Any) -> Any:
    """``_lookup_binding`` memoised on the request so we hit the DB once
    per request even if ``request_is_oidc_authed`` AND
    ``bound_component_id_for_request`` both fire on the same view.
    """
    if hasattr(request, "_oidc_binding_cache"):
        return request._oidc_binding_cache
    binding = _lookup_binding(request)
    request._oidc_binding_cache = binding
    return binding


def _token_is_oidc_typed(token_record: AccessToken) -> bool:
    """True iff the token's signed JWT carries ``token_type="oidc"``.

    This is the authoritative OIDC signal: the claim is covered by the
    HMAC signature (so it can't be forged without ``SECRET_KEY``) and is
    ``"oidc"`` only for OIDC-issued tokens. We re-decode here rather than
    keying on ``expires_at`` because, since #1007, PATs may also set a
    DB-row ``expires_at`` (default 90 days) — making that column useless
    as an OIDC discriminator. The token reaching this point already
    passed authentication, so the decode succeeds and isn't expired; any
    decode failure falls through to the binding-based fallback.

    Memoised on the token-record instance: ``request_is_oidc_authed``
    runs twice per upload request (once in ``is_authorised_for_component``
    and again in ``bound_component_id_for_request``), and
    ``request.access_token_record`` is that same per-request instance both
    times — so the JWT is verified at most once per request without a
    request-scoped cache attribute (cf. ``_cached_binding``).
    """
    cached = getattr(token_record, "_is_oidc_typed", None)
    if cached is not None:
        return bool(cached)

    from jwt.exceptions import DecodeError

    from sbomify.apps.access_tokens.utils import TOKEN_TYPE_OIDC, decode_personal_access_token

    try:
        result = decode_personal_access_token(token_record.encoded_token).get("token_type") == TOKEN_TYPE_OIDC
    except DecodeError:
        result = False
    setattr(token_record, "_is_oidc_typed", result)
    return result


def request_is_oidc_authed(request: Any) -> bool:
    """True iff the request was authenticated via an OIDC-issued AccessToken.

    OIDC-ness is asserted by EITHER of two independent, OIDC-specific
    signals:

    * the signed JWT's ``token_type`` claim is ``"oidc"`` — authoritative
      and tamper-evident (HMAC over ``SECRET_KEY``).
    * an ``OIDCBinding`` row exists with ``bot_user`` pointing at the
      request's user (every OIDC-issued token belongs to a bot user that
      a binding owns).

    ``expires_at`` is deliberately NOT a signal: since #1007 personal
    access tokens may also carry a DB-row ``expires_at`` (default 90
    days), so keying on it would misclassify an expiring PAT as OIDC and
    403 its uploads in ``is_authorised_for_component``.

    Belt-and-suspenders by design: requiring BOTH signals to be present
    would let either getting silently wiped (migration bug, manual
    tamper, partial-cleanup data race) demote an OIDC token to PAT
    status — at which point ``is_authorised_for_component`` becomes a
    no-op and the bot escapes its component scope. Treating EITHER as
    sufficient means an attacker would have to forge the signed
    ``token_type`` claim (needs ``SECRET_KEY``) AND delete the
    ``OIDCBinding`` row without taking down the bot user.

    Performance: ``request_is_oidc_authed`` is only reached on the
    component-scoped upload endpoints, and runs at most one JWT verify
    plus (for a PAT) one unique-indexed probe on ``OIDCBinding.bot_user_id``
    per request. Both are memoised — the ``token_type`` decode on the
    token-record instance (``_token_is_oidc_typed``) and the binding
    lookup via ``_cached_binding`` — so the second call this predicate
    receives within a request (``is_authorised_for_component`` then
    ``bound_component_id_for_request``) is effectively free.
    """
    token_record: AccessToken | None = getattr(request, "access_token_record", None)
    if token_record is None:
        return False
    if _token_is_oidc_typed(token_record):
        return True
    return _cached_binding(request) is not None


def bound_component_id_for_request(request: Any) -> str | None:
    """For an OIDC-authed request, return the bot's bound component_id.

    Returns ``None`` when the request isn't OIDC-authed OR when the bot
    has no binding (shouldn't happen — provisioning + cascade-deletion
    keep these in sync — but defensively returns ``None`` rather than
    raising; the caller in ``is_authorised_for_component`` treats
    ``None`` as fail-closed for OIDC requests).
    """
    if not request_is_oidc_authed(request):
        return None
    binding = _cached_binding(request)
    return str(binding.component_id) if binding else None


def is_authorised_for_component(request: Any, component: Any) -> bool:
    """Authorise OIDC tokens for the bound component only.

    Returns ``True`` for non-OIDC requests (PATs / sessions are
    governed by ``verify_item_access`` alone). For OIDC requests:

    * returns ``True`` only when the request's bound component matches
      the target.
    * returns ``False`` when the request is OIDC-authed but the bot
      user has NO OIDCBinding — defense-in-depth against partial-cleanup
      data-integrity gaps (e.g. binding deleted but the bot user's
      cascade somehow didn't fire). An orphan bot must NOT be able to
      reach any component.
    """
    # First branch: not an OIDC token at all — no extra check.
    if not request_is_oidc_authed(request):
        return True
    # OIDC-authed: an orphan (no binding) → fail closed.
    bound_id = bound_component_id_for_request(request)
    if bound_id is None:
        return False
    return bound_id == str(component.id)
