from __future__ import annotations

import logging
import typing

if typing.TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import Model
    from django.http import HttpRequest

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from sbomify.apps.teams.models import Team
from sbomify.apps.teams.utils import get_user_teams

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def user_logged_in_handler(sender: Model, user: User, request: HttpRequest, **kwargs):
    request.session["user_photo"] = ""
    social_account = SocialAccount.objects.filter(user=user, provider="keycloak").first()
    if social_account:
        request.session["user_photo"] = social_account.extra_data.get("picture", "")

    # Get user teams and store them in session
    user_teams = get_user_teams(user)
    request.session["user_teams"] = user_teams

    if request.session.get("current_team", None) is None and user_teams:
        # Use the first team as the default
        first_team_key = next(iter(user_teams))
        first_team = {"key": first_team_key, **user_teams[first_team_key]}
        request.session["current_team"] = first_team

    # Fallback safety net: Ensure every user has a team
    # NOTE: This should rarely be needed now that both adapters create teams during signup.
    # This exists only for edge cases (manual user creation, data migrations, etc.)
    if not Team.objects.filter(members=user).exists():
        logger.warning(
            f"User {user.username} has no team on login - creating via fallback handler. "
            f"This should not happen for normal signups."
        )
        from sbomify.apps.teams.utils import create_user_team_and_subscription

        create_user_team_and_subscription(user)
