from __future__ import annotations

import logging
import typing

if typing.TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import Model
    from django.http import HttpRequest

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from social_django.models import UserSocialAuth

from core.utils import number_to_random_token
from teams.utils import get_user_teams

from ..models import Member, Team, get_team_name_for_user

log = logging.getLogger(__name__)


@receiver(user_logged_in)
def user_logged_in_handler(sender: Model, user: User, request: HttpRequest, **kwargs):
    request.session["user_photo"] = ""
    social_record = UserSocialAuth.objects.filter(user=user).first()
    if social_record:
        request.session["user_photo"] = social_record.extra_data.get("picture", "")

    # Get user teams and store them in session
    user_teams = get_user_teams(user)
    request.session["user_teams"] = user_teams

    if request.session.get("current_team", None) is None and user_teams:
        for team_key, team_data in user_teams.items():
            if team_data["is_default_team"]:
                first_team = {"key": team_key, **team_data}
                request.session["current_team"] = first_team
                break


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def new_user_handler(sender: Model, instance: User, created: bool, **kwargs):
    if created:
        with transaction.atomic():
            default_team = Team(name=get_team_name_for_user(instance))
            default_team.save()

            default_team.key = number_to_random_token(default_team.pk)
            default_team.save()

            team_membership = Member(user=instance, team=default_team, role="owner", is_default_team=True)
            team_membership.save()
            log.info(f"Team {default_team.pk} ({default_team.name}) created for new user {instance.username}")

            context = {
                "user": instance,
                "membership": team_membership,
                "base_url": settings.APP_BASE_URL,
            }
            send_mail(
                subject="Welcome to the Team",
                message=render_to_string("teams/new_user_email.txt", context),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[instance.email],
                html_message=render_to_string("teams/new_user_email.html", context),
            )
