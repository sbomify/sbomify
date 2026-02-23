from django.conf import settings
from django.db import models


class AccessToken(models.Model):
    class Meta:
        db_table = "access_tokens"
        indexes = [
            models.Index(fields=["team", "user"]),
        ]

    encoded_token = models.CharField(max_length=1000, null=False, unique=True)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.user_id} - {self.description}"
