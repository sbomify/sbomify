from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model."""

    email_verified = models.BooleanField(default=False)
    """Whether the user's email has been verified."""

    class Meta:
        db_table = "core_users"
