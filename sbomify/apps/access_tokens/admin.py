from django.contrib import admin

from .models import AccessToken


@admin.register(AccessToken)
class AccessTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "description", "team", "created_at"]
    list_filter = ["team", "created_at"]
    search_fields = ["user__email", "user__username", "description"]
    raw_id_fields = ["user", "team"]
