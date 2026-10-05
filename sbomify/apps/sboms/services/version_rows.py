"""The component card's rows: one per version, not one per file.

A build published as CycloneDX and SPDX is one piece of software, but each file
is scanned on its own and the scanners read the formats differently, so a table
of files shows the same version twice with two different answers. Grouping by
version merges every file's findings by advisory alias and answers once: what
is still open, what this version introduced, and which check it fails first.
"""

from __future__ import annotations

from typing import Any

from django.urls import reverse

from sbomify.apps.plugins.models import AssessmentRun

#: How many versions the card shows.
VERSION_LIMIT = 5

_SECURITY = "security"
# Worst first: the verdict a version gets for a check is its worst file's.
_STATUS_RANK = {"fail": 0, "error": 1, "pending": 2, "pass": 3, "skipped": 4}  # nosec B105 - check outcomes, not credentials
_ITEM_TYPES = {"sbom": "sboms", "vex": "vex", "cbom": "cbom"}


def build_version_rows(component_id: str, sbom_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group the component's artifacts by version, newest first, and summarise each."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(sbom_items, key=_uploaded, reverse=True):
        groups.setdefault(item["sbom"].get("version") or "", []).append(item)
    # One version past the limit is read so the oldest row shown can still say
    # what it introduced.
    versions = list(groups.items())[: VERSION_LIMIT + 1]

    findings = _open_findings(component_id, versions)
    rows = []
    for index, (version, items) in enumerate(versions[:VERSION_LIMIT]):
        previous = findings[index + 1] if index + 1 < len(versions) else None
        newest_sbom = next((item for item in items if _bom_type(item) == "sbom"), items[0])
        rows.append(
            {
                "version": version,
                "uploaded": _uploaded_at(items[0]),
                "url": _item_url(component_id, newest_sbom),
                "vulnerabilities": _vulnerabilities(findings[index], previous),
                "compliance": _compliance(items),
                "files": " · ".join(dict.fromkeys(_file_label(item) for item in items)),
                "downloads": [_download(item) for item in items],
            }
        )
    return rows


def _open_findings(component_id: str, versions: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """Each version's still-open findings, merged across its files and scanners."""
    from sbomify.apps.vulnerability_scanning.utils import (
        extract_finding_rows,
        extract_severity_counts,
        merge_findings_by_alias,
        result_scanned_nothing,
    )
    from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

    sbom_ids = [item["sbom"]["id"] for _, items in versions for item in items if _bom_type(item) == "sbom"]
    results: dict[str, list[dict[str, Any] | None]] = {}
    if sbom_ids:
        latest = (
            AssessmentRun.objects.filter(sbom_id__in=sbom_ids, category=_SECURITY, status="completed")
            .order_by("sbom_id", "plugin_name", "-created_at", "-id")
            .distinct("sbom_id", "plugin_name")
            .values("sbom_id", "result")
        )
        for run in latest:
            results.setdefault(str(run["sbom_id"]), []).append(run["result"])
    vex_statements = load_vex_suppressions(component_id) if results else []

    summaries: list[dict[str, Any]] = []
    for _, items in versions:
        version_results = [
            result for item in items if _bom_type(item) == "sbom" for result in results.get(str(item["sbom"]["id"]), [])
        ]
        if not version_results:
            # A VEX or CBOM on its own is not something a scanner reads.
            has_sbom = any(_bom_type(item) == "sbom" for item in items)
            summaries.append({"state": "not_scanned" if has_sbom else "not_applicable"})
            continue
        if all(result_scanned_nothing(result) for result in version_results):
            summaries.append({"state": "nothing_scanned"})
            continue
        rows = [
            row
            for row in extract_finding_rows(merge_findings_by_alias(version_results), vex_statements)
            if not row["vex_suppressed"]
        ]
        if rows:
            summaries.append({"state": "scanned", "rows": rows, "keys": {key for row in rows for key in _keys(row)}})
        else:
            # Summary-only providers report counts without findings, so there is
            # nothing to compare between versions, only the worst file's tally.
            counts = max((extract_severity_counts(result) for result in version_results), key=lambda c: c["total"])
            summaries.append({"state": "scanned", "counts": counts})
    return summaries


def _vulnerabilities(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if current["state"] != "scanned":
        return {"state": current["state"]}
    if "counts" in current:
        counts = current["counts"]
        critical, high, total = counts.get("critical", 0), counts.get("high", 0), counts.get("total", 0)
        new = None
    else:
        rows = current["rows"]
        critical = sum(row["severity"] == "critical" for row in rows)
        high = sum(row["severity"] == "high" for row in rows)
        total = len(rows)
        # A finding is new when nothing in the previous version shares any of
        # its ids on the same package. Package versions are left out on
        # purpose: a CVE that survives a dependency bump is not new.
        new = (
            sum(not (_keys(row) & previous["keys"]) for row in rows)
            if previous is not None and "keys" in previous
            else None
        )
    if not total:
        return {"state": "none"}
    return {"state": "open", "critical": critical, "high": high, "other": total - critical - high, "new": new}


def _compliance(items: list[dict[str, Any]]) -> dict[str, Any]:
    """The version's verdict on each check that is not a security scan."""
    worst: dict[str, dict[str, Any]] = {}
    for item in items:
        for plugin in (item.get("assessments") or {}).get("plugins") or []:
            if plugin.get("category") == _SECURITY or plugin.get("status") not in _STATUS_RANK:
                continue
            held = worst.get(plugin["name"])
            if held is None or _STATUS_RANK[plugin["status"]] < _STATUS_RANK[held["status"]]:
                worst[plugin["name"]] = plugin
    checks = [plugin for plugin in worst.values() if plugin["status"] != "skipped"]
    if not checks:
        return {"state": "none"}
    failing = sorted(plugin["display_name"] for plugin in checks if plugin["status"] == "fail")
    if failing:
        return {"state": "fails", "first": failing[0], "more": len(failing) - 1}
    # A check that could not run has not failed, and saying so would be a claim
    # about the artifact the check never made.
    unchecked = sorted(plugin["display_name"] for plugin in checks if plugin["status"] == "error")
    if unchecked:
        return {"state": "error", "first": unchecked[0], "more": len(unchecked) - 1}
    if any(plugin["status"] == "pending" for plugin in checks):
        return {"state": "checking"}
    return {"state": "meets", "total": len(checks)}


def _download(item: dict[str, Any]) -> dict[str, str]:
    sbom = item["sbom"]
    label = _format_label(item)
    if _bom_type(item) != "sbom":
        label = f"{_bom_type(item).upper()} ({label})" if label else _bom_type(item).upper()
    return {"label": label, "url": reverse("sboms:sbom_download", args=[sbom["id"]])}


def _file_label(item: dict[str, Any]) -> str:
    """What a row's file is, for the line under its version: the format, or the document type."""
    return _format_label(item) if _bom_type(item) == "sbom" else _bom_type(item).upper()


def _format_label(item: dict[str, Any]) -> str:
    sbom = item["sbom"]
    names = {"cyclonedx": "CycloneDX", "spdx": "SPDX"}
    file_format = sbom.get("format_display") or names.get(sbom.get("format") or "", (sbom.get("format") or "").upper())
    return f"{file_format} {sbom.get('format_version') or ''}".strip()


def _keys(row: dict[str, Any]) -> set[tuple[str, str]]:
    package = str(row.get("package") or "").split(":")[-1].lower()
    return {(package, advisory) for advisory in [row["id"], *row.get("aliases", [])] if advisory}


def _item_url(component_id: str, item: dict[str, Any]) -> str:
    return reverse(
        "core:component_item",
        kwargs={
            "component_id": component_id,
            "item_type": _ITEM_TYPES.get(_bom_type(item), "sboms"),
            "item_id": item["sbom"]["id"],
        },
    )


def _bom_type(item: dict[str, Any]) -> str:
    return item["sbom"].get("bom_type") or "sbom"


def _uploaded_at(item: dict[str, Any]) -> Any:
    return item["sbom"].get("created_at")


def _uploaded(item: dict[str, Any]) -> float:
    created = _uploaded_at(item)
    return created.timestamp() if created else 0.0
