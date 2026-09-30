from typing import TYPE_CHECKING

from django.contrib import admin

from sbomify.apps.core.admin import admin_site

from .models import AccessToken

if TYPE_CHECKING:
    _Base = admin.ModelAdmin[AccessToken]
else:
    _Base = admin.ModelAdmin


@admin.register(AccessToken, site=admin_site)
class AccessTokenAdmin(_Base):
    list_display = ["user", "description", "team", "created_at", "last_used_at"]
    list_filter = ["team", "created_at", "last_used_at"]
    search_fields = ["user__email", "user__username", "description"]
    raw_id_fields = ["user", "team"]
