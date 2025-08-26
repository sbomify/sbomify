from __future__ import annotations

import logging
import typing

if typing.TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import Model
    from django.http import HttpRequest

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.dispatch import receiver

from core.utils import number_to_random_token
from teams.models import get_team_name_for_user
from teams.utils import get_user_teams, setup_team_billing_plan

from ..models import Member, Team

log = logging.getLogger(__name__)


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

    # Fallback: Ensure every user has a team (for native signups)
    if not Team.objects.filter(members=user).exists():
        team_name = get_team_name_for_user(user)
        with transaction.atomic():
            team = Team.objects.create(name=team_name)
            team.key = number_to_random_token(team.pk)
            team.save()
            Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        # Set up billing plan for the team
        setup_team_billing_plan(team, user=user, send_welcome_email=True)
