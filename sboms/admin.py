from django.contrib import admin

from .models import SBOM

# Product, Project, Component admin moved to core app
admin.site.register(SBOM)
