"""Tests for builtin plugin lifecycle reconciliation."""

import pytest

from sbomify.apps.plugins.models import RegisteredPlugin


@pytest.mark.django_db
class TestBuiltinReconciliation:
    """Tests for _register_builtin_plugins() reconciliation."""

    def test_reconciliation_disables_orphaned_builtins(self) -> None:
        """Orphaned builtin plugins are disabled after registration."""
        RegisteredPlugin.objects.create(
            name="old-removed-plugin",
            display_name="Old Removed Plugin",
            category="compliance",
            version="1.0.0",
            plugin_class_path="sbomify.apps.plugins.builtins.old.OldPlugin",
            is_enabled=True,
            is_builtin=True,
        )

        from sbomify.apps.plugins.apps import PluginsConfig

        config = PluginsConfig("sbomify.apps.plugins", __import__("sbomify.apps.plugins"))
        config._register_builtin_plugins()

        orphan = RegisteredPlugin.objects.get(name="old-removed-plugin")
        assert orphan.is_enabled is False
        assert orphan.is_builtin is True

    def test_reconciliation_does_not_touch_admin_plugins(self) -> None:
        """Admin-created plugins (is_builtin=False) are not affected."""
        RegisteredPlugin.objects.create(
            name="custom-admin-plugin",
            display_name="Custom Admin Plugin",
            category="security",
            version="1.0.0",
            plugin_class_path="some.external.plugin.CustomPlugin",
            is_enabled=True,
            is_builtin=False,
        )

        from sbomify.apps.plugins.apps import PluginsConfig

        config = PluginsConfig("sbomify.apps.plugins", __import__("sbomify.apps.plugins"))
        config._register_builtin_plugins()

        admin_plugin = RegisteredPlugin.objects.get(name="custom-admin-plugin")
        assert admin_plugin.is_enabled is True
        assert admin_plugin.is_builtin is False

    def test_builtins_registered_with_is_builtin_true(self) -> None:
        """All builtin plugins are registered with is_builtin=True."""
        from sbomify.apps.plugins.apps import PluginsConfig

        config = PluginsConfig("sbomify.apps.plugins", __import__("sbomify.apps.plugins"))
        config._register_builtin_plugins()

        builtins = RegisteredPlugin.objects.filter(is_builtin=True)
        assert builtins.count() == 6

        for plugin in builtins:
            assert plugin.is_enabled is True
