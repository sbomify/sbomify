"""The per-run assessment card badge.

A plugin that could not run returns ``metadata={"skipped": True}``. The API
layer honours that through ``_is_run_skipped``; these tests hold the template to
the same reading, because a skipped run rendered as "Warnings Only" reads as a
scanner that ran and disagreed with the others.
"""

from __future__ import annotations

from django.template.loader import render_to_string


def _run(**overrides) -> dict:
    run = {
        "id": "run1",
        "plugin_name": "dependency-track",
        "plugin_display_name": "Dependency Track",
        "plugin_version": "1.0.0",
        "category": "security",
        "status": "completed",
        "run_reason": "on_upload",
        "release_names": [],
        "completed_at": None,
        "result": {
            "summary": {
                "total_findings": 1,
                "pass_count": 0,
                "fail_count": 0,
                "warning_count": 1,
                "error_count": 0,
            },
            "findings": [
                {
                    "id": "dependency-track:unsupported-format",
                    "title": "Format Not Supported",
                    "description": "Dependency Track only supports CycloneDX format.",
                    "status": "warning",
                    "severity": "info",
                }
            ],
            "metadata": {},
        },
    }
    run.update(overrides)
    return run


def _render(run: dict) -> str:
    return render_to_string("plugins/components/_assessment_run_item.html.j2", {"run": run, "loop_index": 1})


def _header(run: dict) -> str:
    """What a reader sees before expanding the card.

    The findings list lives inside ``x-show="expanded"``, so asserting against
    the whole render would pass on text nobody can see.
    """
    return _render(run).split('x-show="expanded"')[0]


class TestSkippedRunBadge:
    def test_skipped_run_reads_as_skipped(self):
        """DT on an SPDX SBOM: it never scanned, so "Warnings Only" is a lie."""
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        html = _render(run)

        assert "Skipped" in html
        assert "Warnings Only" not in html

    def test_skipped_run_names_the_reason_without_expanding(self):
        """"1 findings" says nothing about why the plugin stood down, and the
        finding that explains it is hidden until the card is expanded."""
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        header = _header(run)

        assert "Format Not Supported" in header
        assert "1 findings" not in header

    def test_skipped_run_is_not_coloured_as_a_warning(self):
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        html = _render(run)

        assert "tw-collapsible-card--warning" not in html

    def test_a_skipped_compliance_run_reads_the_same(self):
        """PQC skips a document with no crypto assets. Different category, same
        rendering branch, so it was mislabelled the same way."""
        run = _run(
            plugin_name="pqc",
            plugin_display_name="Post-Quantum Readiness",
            category="compliance",
        )
        run["result"]["metadata"] = {"skipped": True}
        run["result"]["findings"] = [
            {
                "id": "pqc:no-assets",
                "title": "No cryptographic assets found",
                "description": "This document declares no crypto-asset components; nothing to assess.",
                "status": "info",
                "severity": "info",
            }
        ]

        header = _header(run)

        assert "Skipped" in header
        assert "Warnings Only" not in header
        assert "No cryptographic assets found" in header

    def test_a_real_warnings_only_run_is_untouched(self):
        """A plugin that ran and produced only warnings still reads that way."""
        html = _render(_run())

        assert "Warnings Only" in html
        assert "Skipped" not in html

    def test_a_passing_run_is_untouched(self):
        run = _run()
        run["result"]["summary"] = {
            "total_findings": 3,
            "pass_count": 3,
            "fail_count": 0,
            "warning_count": 0,
            "error_count": 0,
        }

        html = _render(run)

        assert "Passed" in html
        assert "Skipped" not in html

    def test_a_failing_run_is_untouched(self):
        run = _run()
        run["result"]["summary"] = {
            "total_findings": 2,
            "pass_count": 0,
            "fail_count": 2,
            "warning_count": 0,
            "error_count": 0,
        }

        html = _render(run)

        assert "2 Issues" in html
        assert "Skipped" not in html
