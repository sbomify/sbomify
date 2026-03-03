from typing import TYPE_CHECKING

from django.contrib import admin

from .models import AccessToken

if TYPE_CHECKING:
    _Base = admin.ModelAdmin[AccessToken]
else:
    _Base = admin.ModelAdmin


@admin.register(AccessToken)
class AccessTokenAdmin(_Base):
    list_display = ["user", "description", "team", "created_at"]
    list_filter = ["team", "created_at"]
    search_fields = ["user__email", "user__username", "description"]
    raw_id_fields = ["user", "team"]
