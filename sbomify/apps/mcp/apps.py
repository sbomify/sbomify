from django.apps import AppConfig


class MCPConfig(AppConfig):
    """Django app configuration for the Model Context Protocol server."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.mcp"
    label = "mcp"
    verbose_name = "Model Context Protocol"
