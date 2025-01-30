from django.contrib import admin

# Register your models here.
from .models import Invitation, Member, Team

admin.site.register(Team)
admin.site.register(Member)
admin.site.register(Invitation)
