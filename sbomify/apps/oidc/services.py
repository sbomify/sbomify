"""Service-layer helpers for OIDC bindings.

The big one is bot-user provisioning. Every ``OIDCBinding`` owns a
synthetic ``User`` row that becomes the actor on ``AccessToken``
records issued by the token-exchange endpoint. Splitting "synthetic
user per binding" from "shared workspace bot" means audit trails point
at the exact ``(provider, repo)`` that uploaded an artifact, which is
the whole point of trusted publishing — you can answer "which CI
binding pushed this?" without correlation.

Lifecycle
---------

* On binding create: ``provision_bot_user_for_binding`` is called,
  which creates a User + a ``Member`` row joining that user to the
  Component's workspace at ``role="bot"``. The function is idempotent
  — calling it twice on the same binding is a no-op.

* On binding delete: ``delete_bot_user_for_binding`` is wired via a
  post_delete signal in ``apps.OIDCConfig.ready``. The bot User's
  deletion cascades to its Member row, AccessToken rows, and any
  other FK with CASCADE — so a binding removal also revokes every
  short-lived token that binding ever issued.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db import transaction

from sbomify.apps.core.models import User
from sbomify.apps.teams.models import Member
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.oidc.models import OIDCBinding

logger = getLogger(__name__)

# Synthetic-bot identity convention. ``.local`` is the reserved
# special-use TLD per RFC 6761 §6.3 — guarantees the email is not
# routable, so a misconfigured mailer can't accidentally try to deliver
# notifications to "oidc-bot-…@sbomify.local".
_BOT_USERNAME_PREFIX = "oidc-bot-"
_BOT_EMAIL_DOMAIN = "sbomify.local"
_BOT_ROLE = "bot"


def _bot_username(binding_id: str) -> str:
    return f"{_BOT_USERNAME_PREFIX}{binding_id}"


def _bot_email(binding_id: str) -> str:
    return f"{_BOT_USERNAME_PREFIX}{binding_id}@{_BOT_EMAIL_DOMAIN}"


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
    User = get_user_model()
    username = _bot_username(binding.id)
    email = _bot_email(binding.id)

    bot_user, created = User.objects.get_or_create(
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
        # set_unusable_password ensures no one can log in as this user
        # via the normal Keycloak / password flow — only the OIDC
        # token-exchange endpoint can mint tokens for them.
        bot_user.set_unusable_password()
        bot_user.save(update_fields=["password"])
        logger.info("Provisioned OIDC bot user %s for binding %s", username, binding.id)

    Member.objects.get_or_create(
        team=binding.component.team,
        user=bot_user,
        defaults={"role": _BOT_ROLE, "is_default_team": False},
    )
    return bot_user


def delete_bot_user_for_binding(binding_id: str) -> None:
    """Delete the bot User row for a removed binding.

    Called from a post_delete signal on ``OIDCBinding``. Removing the
    User cascades to:

    * the ``Member`` row joining the bot to the workspace
    * every ``AccessToken`` row that binding ever issued (their
      ``user`` FK is CASCADE on User)

    That last point is the safety property: revoking a binding
    revokes every credential ever derived from it, with no manual
    cleanup step.
    """
    User = get_user_model()
    username = _bot_username(binding_id)
    deleted_count, _ = User.objects.filter(username=username).delete()
    if deleted_count:
        logger.info("Removed OIDC bot user %s after binding deletion", username)
