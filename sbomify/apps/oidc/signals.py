"""Signal handlers for the OIDC app.

We hook ``post_delete`` on ``OIDCBinding`` so the synthetic bot User
created during ``provision_bot_user_for_binding`` is also removed when
the binding goes away. That, in turn, cascades to the bot's Member
row and every short-lived AccessToken it ever signed.

The signal is registered from ``apps.OIDCConfig.ready`` (not at
module import time) so the User model is loaded by the time the
handler runs.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete
from django.dispatch import receiver

from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import delete_bot_user_for_binding


@receiver(post_delete, sender=OIDCBinding)
def cleanup_bot_user_on_binding_delete(sender: type, instance: OIDCBinding, **kwargs: Any) -> None:
    """Reap the synthetic bot User after its binding is gone."""
    delete_bot_user_for_binding(instance.id)
