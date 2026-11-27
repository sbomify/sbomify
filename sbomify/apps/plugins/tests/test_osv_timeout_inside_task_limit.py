"""The OSV scanner must time out before the task running it does.

When the Dramatiq time limit fires first, the worker is interrupted mid-scan:
the run's transaction rolls back, the message is retried, and the plugin's own
"OSV scanner timed out" result is never recorded.
"""

from sbomify.apps.plugins.builtins.osv import OSVPlugin
from sbomify.apps.plugins.tasks import run_assessment_task

# Time the task needs around the scan: fetching the SBOM, saving the findings.
HEADROOM_MS = 60_000


def test_the_scanner_times_out_before_the_task_does() -> None:
    task_limit_ms = run_assessment_task.options["time_limit"]

    assert OSVPlugin.DEFAULT_TIMEOUT * 1000 + HEADROOM_MS <= task_limit_ms
