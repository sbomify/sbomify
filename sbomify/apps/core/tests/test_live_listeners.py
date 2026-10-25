"""Regions that show broadcast state listen for the messages that change it, and for resync.

The server side of each message is pinned in the broadcast tests; these pin
that the listening side exists, so a message is never sent to nobody.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory

REPO_ROOT = Path(__file__).resolve().parents[4]


def _request(path: str = "/component/abc/") -> Any:
    request: Any = RequestFactory().get(path)
    request.user = AnonymousUser()
    request.session = {"current_workspace": {"key": "ws"}}
    return request


def test_component_metadata_refreshes_on_component_updated() -> None:
    html = render_to_string(
        "core/components/component_meta_info.html.j2",
        {"component": SimpleNamespace(id="abc", has_crud_permissions=False), "request": _request()},
    )

    assert "$event.detail.type === 'component_updated'" in html
    assert "$event.detail.type === 'resync'" in html
    # A remote edit re-reads the data quietly; refreshDisplay() would toast "updated" at every reader.
    assert "fetchMetadata()" in html


@pytest.mark.parametrize("issues", [[], [{"status": "fail", "severity": "high", "title": "t", "check": "c"}]])
def test_cbom_issues_card_is_always_a_refresh_target(issues: list[dict[str, str]]) -> None:
    html = render_to_string(
        "core/components/component_cbom_issues.html.j2",
        {
            "component": {"id": "abc"},
            "latest_cbom_issues": issues,
            "latest_cbom_issue_terms": ["t c"] if issues else [],
            "latest_cbom_issue_severities": ["high"] if issues else [],
            "latest_cbom_id": "cbom1" if issues else None,
            "request": _request("/component/abc/?tab=x"),
        },
    )

    assert 'id="component-cbom-issues"' in html
    assert 'hx-get="/component/abc/?tab=x"' in html
    assert 'hx-select="#component-cbom-issues"' in html
    assert "$event.detail.type === 'vex_reapplied' && $event.detail.component_id === 'abc'" in html
    assert "$event.detail.type === 'resync'" in html
    assert ("$event.detail.sbom_id === 'cbom1'" in html) is bool(issues)
    assert ("CBOM issues" in html) is bool(issues)


def test_release_artifacts_reload_scan_counts_on_assessment_and_vex() -> None:
    html = render_to_string(
        "core/components/release_artifacts.html.j2",
        {
            "release_id": "rel1",
            "product_id": "prod1",
            "can_edit": False,
            "is_latest": False,
            "artifact_vulnerabilities": {"sbom1": None},
            "request": _request("/product/prod1/release/rel1/"),
        },
    )

    assert "$event.detail.type === 'release_updated' && $event.detail.release_id === 'rel1'" in html
    assert "$event.detail.type === 'assessment_complete' && $event.detail.sbom_id in vulnerabilities" in html
    assert "$event.detail.type === 'vex_reapplied'" in html
    assert "$event.detail.type === 'resync'" in html
    assert 'hx-get="/product/prod1/release/rel1/"' in html
    assert 'hx-select="#release-artifact-vulnerabilities"' in html
    assert html.count('id="release-artifact-vulnerabilities"') == 1


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("sbomify/apps/sboms/templates/sboms/sboms_table.html.j2", ["'assessment_started'", "'resync'"]),
        ("sbomify/apps/core/templates/core/component_item.html.j2", ["'assessment_started'", "'resync'"]),
        (
            "sbomify/templates/components/vulnerabilities/workspace_browser.html",
            ["'sbom_deleted'", "'component_deleted'", "'product_deleted'", "'resync'"],
        ),
    ],
)
def test_assessment_state_regions_listen(template: str, expected: list[str]) -> None:
    source = (REPO_ROOT / template).read_text()
    listener = next(line for line in source.splitlines() if "@ws:message.window" in line)

    for message in expected:
        assert message in listener
