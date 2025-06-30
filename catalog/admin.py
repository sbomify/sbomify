"""Django admin configuration for catalog app."""

from django.contrib import admin

from .models import Component, Product, ProductProject, Project, ProjectComponent


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin configuration for Product model."""

    list_display = ("name", "team", "is_public", "created_at")
    list_filter = ("is_public", "created_at", "team")
    search_fields = ("name", "team__name")
    readonly_fields = ("id", "created_at")
    ordering = ("name",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Admin configuration for Project model."""

    list_display = ("name", "team", "is_public", "created_at")
    list_filter = ("is_public", "created_at", "team")
    search_fields = ("name", "team__name")
    readonly_fields = ("id", "created_at")
    ordering = ("name",)


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    """Admin configuration for Component model."""

    list_display = ("name", "team", "is_public", "created_at")
    list_filter = ("is_public", "created_at", "team")
    search_fields = ("name", "team__name")
    readonly_fields = ("id", "created_at")
    ordering = ("name",)


@admin.register(ProductProject)
class ProductProjectAdmin(admin.ModelAdmin):
    """Admin configuration for ProductProject through model."""

    list_display = ("product", "project", "id")
    list_filter = ("product__team", "project__team")
    search_fields = ("product__name", "project__name")
    readonly_fields = ("id",)


@admin.register(ProjectComponent)
class ProjectComponentAdmin(admin.ModelAdmin):
    """Admin configuration for ProjectComponent through model."""

    list_display = ("project", "component", "id")
    list_filter = ("project__team", "component__team")
    search_fields = ("project__name", "component__name")
    readonly_fields = ("id",)
