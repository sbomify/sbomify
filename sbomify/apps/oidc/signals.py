"""Signal handlers for the OIDC app.

Two handlers, both registered from ``apps.OIDCConfig.ready``:

* ``cleanup_bot_user_on_binding_delete`` — post_delete on
  ``OIDCBinding``: reaps the synthetic bot User, which cascades to
  the Member row and every short-lived AccessToken the binding ever
  signed.

* ``forbid_manual_bot_role`` — pre_save on ``Member``: rejects any
  attempt to write ``role="bot"`` for a user that doesn't have an
  ``OIDCBinding`` pointing at them. Defends against an admin (or
  future API) accidentally creating a privileged "bot" Member that
  isn't backed by a real binding. The
  ``provision_bot_user_for_binding`` flow is exempted by setting
  ``instance._is_oidc_bot_provisioning = True`` before save —
  ``forbid_manual_bot_role`` reads exactly that attribute name via
  ``getattr(instance, "_is_oidc_bot_provisioning", False)``.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import delete_bot_user_by_id
from sbomify.apps.teams.models import Member


@receiver(post_delete, sender=OIDCBinding)
def cleanup_bot_user_on_binding_delete(sender: type, instance: OIDCBinding, **kwargs: Any) -> None:
    """Reap the synthetic bot User after its binding is gone.

    Deletes by the exact ``bot_user_id`` FK on the soon-to-be-removed
    binding instance — not by reconstructing the username from a
    derived convention. If the bot's username was ever renamed (admin
    action, future username-format change) the convention-based
    deletion would leak the bot User and every AccessToken it ever
    signed. ID-based deletion stays correct under any naming change.
    """
    if instance.bot_user_id is not None:
        delete_bot_user_by_id(instance.bot_user_id)


@receiver(pre_save, sender=Member)
def forbid_manual_bot_role(sender: type, instance: Member, **kwargs: Any) -> None:
    """Reject ``Member.role="bot"`` unless the user has an OIDCBinding.

    The "bot" role is reserved for synthetic identities provisioned by
    ``provision_bot_user_for_binding``. Any other path writing
    ``role="bot"`` is a privilege-escalation foot-gun (think: future
    admin-UI rename, a careless migration, a copy-paste in a fixture).

    The provisioning path itself sets
    ``instance._is_oidc_bot_provisioning = True`` to opt out of this
    check — at the moment provisioning runs the bot's binding hasn't
    been attached yet, so the lookup below would falsely reject.
    """
    if instance.role != "bot":
        return
    if getattr(instance, "_is_oidc_bot_provisioning", False):
        return
    # Allow only if the user is the bot for an existing OIDCBinding.
    has_binding = OIDCBinding.objects.filter(bot_user=instance.user).exists()
    if not has_binding:
        raise ValidationError(
            "role='bot' is reserved for synthetic OIDC binding identities and "
            "cannot be assigned to a Member outside the OIDC provisioning flow."
        )
