from django.contrib import admin

from .models import SBOM, Component, Product, Project

admin.site.register(Product)
admin.site.register(Project)
admin.site.register(Component)
admin.site.register(SBOM)
