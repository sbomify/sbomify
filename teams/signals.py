from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.utils import number_to_random_token

from .models import Member, Team, get_team_name_for_user
from .utils import setup_team_billing_plan

User = get_user_model()


def ensure_user_has_team(user):
    if not Team.objects.filter(members=user).exists():
        team_name = get_team_name_for_user(user)
        with transaction.atomic():
            team = Team.objects.create(name=team_name)
            team.key = number_to_random_token(team.pk)
            team.save()
            Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        # Set up billing plan for the team
        setup_team_billing_plan(team, user=user, send_welcome_email=True)


@receiver(post_save, sender=User)
def create_team_for_new_user(sender, instance, created, **kwargs):
    if created:
        ensure_user_has_team(instance)
