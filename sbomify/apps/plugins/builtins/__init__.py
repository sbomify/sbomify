"""Built-in assessment plugins.

Plugins are loaded lazily by the orchestrator via importlib.import_module()
using the full plugin_class_path (e.g., 'sbomify.apps.plugins.builtins.osv.OSVPlugin').

DO NOT add eager imports here — concurrent Dramatiq worker threads importing
this package simultaneously will deadlock on Python's module lock (observed
with Python 3.14's stricter _ModuleLock deadlock detection).
"""
