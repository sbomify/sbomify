from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db import models
from django.utils import timezone

from sbomify.apps.core.utils import number_to_random_token


def get_team_name_for_user(user) -> str:
    """
    Get the team name for a user based on available information.

    Prioritizes first_name, then extracts a clean name from username
    (handling email-based usernames like "user@example.com" or "user.example.com").

    Args:
        user: The user to generate a team name for

    Returns:
        A human-friendly team name string
    """
    if user.first_name:
        return f"{user.first_name}'s Workspace"

    if hasattr(user, "username") and user.username:
        # Extract clean name from email-based usernames
        # Examples:
        #   "john@example.com" -> "john"
        #   "john.example.com" -> "john"
        #   "john.example.com_1" -> "john"
        #   "alice" -> "alice"
        username = user.username

        # First, remove any numbered suffix (e.g., "_1", "_2")
        if "_" in username:
            username = username.split("_")[0]

        # Then extract the part before @ or . (whichever comes first)
        if "@" in username:
            name = username.split("@")[0]
        elif "." in username:
            name = username.split(".")[0]
        else:
            name = username

        return f"{name}'s Workspace"

    return "My Workspace"


class Team(models.Model):
    class Meta:
        db_table = apps.get_app_config("teams").label + "_teams"
        indexes = [models.Index(fields=["key"])]
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    # Both IDs present
                    (
                        models.Q(billing_plan_limits__stripe_subscription_id__isnull=False)
                        & models.Q(billing_plan_limits__stripe_customer_id__isnull=False)
                    )
                    |
                    # Both IDs null
                    (
                        models.Q(billing_plan_limits__stripe_subscription_id__isnull=True)
                        & models.Q(billing_plan_limits__stripe_customer_id__isnull=True)
                    )
                ),
                name="valid_billing_relationship",
            )
        ]

    key = models.CharField(max_length=30, unique=True, null=True, validators=[MinLengthValidator(9)])
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    branding_info = models.JSONField(default=dict)
    has_completed_wizard = models.BooleanField(default=False)
    billing_plan = models.CharField(max_length=30, null=True)
    billing_plan_limits = models.JSONField(null=True)  # As enterprise plan can have varying limits
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, through="Member")

    def __str__(self) -> str:
        return f"{self.name} ({self.pk})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        super().save(*args, **kwargs)
        if not is_new or self.key is not None:
            return

        self.key = number_to_random_token(self.pk)
        super().save(update_fields=["key"])


class Member(models.Model):
    class Meta:
        db_table = apps.get_app_config("teams").label + "_members"
        unique_together = ("user", "team")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    role = models.CharField(max_length=255, choices=settings.TEAMS_SUPPORTED_ROLES)
    is_default_team = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user.username} - {self.team.name} ({self.team.pk})"


def calculate_invitation_expiry():
    return timezone.now() + timedelta(days=settings.INVITATION_EXPIRY_DAYS)


class Invitation(models.Model):
    class Meta:
        db_table = apps.get_app_config("teams").label + "_invitations"
        unique_together = ("team", "email")

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    email = models.EmailField()
    role = models.CharField(max_length=255, choices=settings.TEAMS_SUPPORTED_ROLES)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=calculate_invitation_expiry)

    def __str__(self) -> str:
        return f"{self.team.name}({self.team.pk}) - {self.email} - {self.role}"

    @property
    def has_expired(self) -> bool:
        """
        Check if the invitation has expired.
        """
        return timezone.now() > self.expires_at
