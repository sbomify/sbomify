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


def request_is_oidc_authed(request: Any) -> bool:
    """True iff the request was authenticated via an OIDC-issued AccessToken.

    Distinguished from a regular PAT by the presence of an ``expires_at``
    column — PATs never set it, OIDC-issued tokens always do.
    """
    token_record: AccessToken | None = getattr(request, "access_token_record", None)
    return token_record is not None and token_record.expires_at is not None


def bound_component_id_for_request(request: Any) -> str | None:
    """For an OIDC-authed request, return the bot's bound component_id.

    Returns ``None`` when the request isn't OIDC-authed OR when the bot
    has no binding (shouldn't happen — provisioning + cascade-deletion
    keep these in sync — but defensively returns ``None`` rather than
    raising).
    """
    if not request_is_oidc_authed(request):
        return None
    token_record: AccessToken = request.access_token_record
    bot_user = token_record.user
    # ``oidc_binding`` is the reverse-side related_name on
    # ``OIDCBinding.bot_user`` (OneToOne). Looked up explicitly via the
    # model rather than the attribute so mypy sees the type.
    from sbomify.apps.oidc.models import OIDCBinding

    binding = OIDCBinding.objects.filter(bot_user=bot_user).only("component_id").first()
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
