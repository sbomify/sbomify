"""Permission helpers for OIDC-issued AccessTokens.

The existing ``verify_item_access`` (sbomify/apps/core/utils.py) handles
session + PAT auth and checks that the actor has one of
``allowed_roles`` on the item's team. For OIDC trusted-publishing
tokens we need a tighter check: the bot may be a Member of the
workspace at ``role="bot"``, but it must NOT be allowed to operate
on any component other than the one its binding pins.

Two-step pattern at the call site::

    if not verify_item_access(request, component, ["owner", "admin", "bot"]):
        return 403, ...
    if not is_authorised_for_component(request, component):
        return 403, ...

The two checks are independent:

* ``verify_item_access`` enforces the workspace role (covers session
  + PAT + bot membership). For PATs / sessions this is the whole
  picture.
* ``is_authorised_for_component`` is a no-op for PATs / sessions; for
  OIDC tokens it locks the bot to its bound component_id.
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.access_tokens.models import AccessToken


def _lookup_binding(request: Any) -> Any:
    """Return the OIDCBinding row that owns the request's token user, or None."""
    token_record: AccessToken | None = getattr(request, "access_token_record", None)
    if token_record is None or token_record.user is None:
        return None
    # ``oidc_binding`` is the reverse-side related_name on
    # ``OIDCBinding.bot_user`` (OneToOne). Looked up via the model so mypy
    # sees the type.
    from sbomify.apps.oidc.models import OIDCBinding

    return OIDCBinding.objects.filter(bot_user=token_record.user).only("component_id").first()


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


def request_is_oidc_authed(request: Any) -> bool:
    """True iff the request was authenticated via an OIDC-issued AccessToken.

    OIDC-ness is asserted by EITHER of two independent signals:

    * ``access_token_record.expires_at`` is set (PATs never set it; OIDC
      tokens always do at issuance).
    * An ``OIDCBinding`` row exists with ``bot_user`` pointing at the
      request's user (every OIDC-issued token belongs to a bot user that
      a binding owns).

    Belt-and-suspenders by design: requiring BOTH signals to be present
    would let either getting silently wiped (migration bug, manual
    tamper, partial-cleanup data race) demote an OIDC token to PAT
    status — at which point ``is_authorised_for_component`` becomes a
    no-op and the bot escapes its component scope. Treating EITHER as
    sufficient means an attacker would have to corrupt both
    ``AccessToken.expires_at`` AND delete the ``OIDCBinding`` row
    without taking down the bot user, which is a much harder failure
    mode.
    """
    token_record: AccessToken | None = getattr(request, "access_token_record", None)
    if token_record is None:
        return False
    if token_record.expires_at is not None:
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
