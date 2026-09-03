"""A public advisory as a CSAF 2.0 document.

The trust-center service decides what a reader may be told and hands over a
projection with the withheld products already gone. This module turns that
projection, and nothing else, into CSAF: it never reads the advisory row, so
it cannot leak a product name the projection kept back.

The model speaks CycloneDX's VEX vocabulary; CSAF has its own. The crosswalk
below is the one CISA publishes for VEX justifications. It is lossy in one
place on purpose: ``false_positive`` has no CSAF spelling and travels as
``known_not_affected``.
"""

from __future__ import annotations

import re
from typing import Any

from sbomify.apps.security_advisories.models import AdvisoryProductStatus, AdvisoryVulnerability, SecurityAdvisory

CSAF_VERSION = "2.0"

_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}")
_CVSS3_VECTOR_RE = re.compile(r"^CVSS:(3\.[01])/")

# AdvisoryProductStatus.Status -> the product_status group it lands in.
_PRODUCT_STATUS = {
    AdvisoryProductStatus.Status.EXPLOITABLE: "known_affected",
    AdvisoryProductStatus.Status.IN_TRIAGE: "under_investigation",
    AdvisoryProductStatus.Status.NOT_AFFECTED: "known_not_affected",
    AdvisoryProductStatus.Status.FALSE_POSITIVE: "known_not_affected",
    AdvisoryProductStatus.Status.RESOLVED: "known_affected",
}

# CycloneDX justification -> CSAF flag label (the CISA VEX crosswalk).
_FLAGS = {
    "code_not_present": "vulnerable_code_not_present",
    "code_not_reachable": "vulnerable_code_not_in_execute_path",
    "requires_configuration": "vulnerable_code_cannot_be_controlled_by_adversary",
    "requires_dependency": "vulnerable_code_cannot_be_controlled_by_adversary",
    "requires_environment": "vulnerable_code_cannot_be_controlled_by_adversary",
    "protected_by_compiler": "inline_mitigations_already_exist",
    "protected_at_runtime": "inline_mitigations_already_exist",
    "protected_at_perimeter": "inline_mitigations_already_exist",
    "protected_by_mitigating_control": "inline_mitigations_already_exist",
}

# AdvisoryProductStatus.Response -> CSAF remediation category.
_REMEDIATION = {
    "update": "vendor_fix",
    "rollback": "workaround",
    "workaround_available": "workaround",
    "can_not_fix": "none_available",
    "will_not_fix": "no_fix_planned",
}

_TLP = {SecurityAdvisory.Visibility.PUBLIC: "WHITE", SecurityAdvisory.Visibility.GATED: "AMBER"}

_EXPLOIT_STATUS = {
    AdvisoryVulnerability.ExploitationStatus.NONE: "No known exploitation.",
    AdvisoryVulnerability.ExploitationStatus.POC: "A proof of concept exists.",
    AdvisoryVulnerability.ExploitationStatus.SUSPECTED: "Exploitation is suspected.",
    AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED: "Exploitation is known.",
}

# What _version_expressions prints when it has nothing to say.
_NO_VERSIONS = {"", "—"}


def _stamp(value: Any) -> str | None:
    return value.isoformat() if value else None


def _base_severity(score: float) -> str:
    if score == 0:
        return "NONE"
    if score < 4:
        return "LOW"
    if score < 7:
        return "MEDIUM"
    if score < 9:
        return "HIGH"
    return "CRITICAL"


class _ProductTree:
    """CSAF names products by an opaque id and lists them once.

    One entry per distinct (product, version expression) pair, so "Gateway
    >= 1.0, < 1.4.3" and "Gateway >= 1.4.3" are two products, which is how
    CSAF says one is affected and the other fixed.
    """

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str], str] = {}
        self.entries: list[dict[str, str]] = []

    def id_for(self, product: str, versions: str = "") -> str:
        versions = "" if versions in _NO_VERSIONS else versions
        key = (product, versions)
        if key not in self._ids:
            product_id = f"CSAFPID-{len(self._ids) + 1:04d}"
            self._ids[key] = product_id
            self.entries.append({"product_id": product_id, "name": f"{product} {versions}".strip()})
        return self._ids[key]


def _document(
    projection: dict[str, Any], *, publisher: dict[str, str], self_url: str, generator: str
) -> dict[str, Any]:
    published_at = projection.get("published_at")
    revisions = [
        {"date": _stamp(event["created_at"]), "number": "0", "summary": event.get("note") or event.get("kind", "")}
        for event in sorted(projection.get("timeline", []), key=lambda e: e["created_at"])
    ]
    if not revisions:
        revisions = [{"date": _stamp(published_at), "number": "0", "summary": "Published."}]
    for index, revision in enumerate(revisions, start=1):
        revision["number"] = str(index)
        revision["summary"] = revision["summary"] or "Updated."

    notes = [
        {"category": category, "text": text}
        for category, text in (("summary", projection.get("summary")), ("description", projection.get("description")))
        if text
    ]
    if projection.get("is_withdrawn"):
        notes.append(
            {
                "category": "other",
                "title": "Withdrawn",
                "text": projection.get("withdrawal_reason") or "This advisory has been withdrawn.",
            }
        )

    references = [{"category": "self", "summary": "This advisory on the trust center", "url": self_url}]
    for reference in projection.get("references", []):
        if reference.get("url"):
            references.append(
                {
                    "category": "self" if reference.get("category") == "self" else "external",
                    "summary": reference.get("summary") or reference.get("external_id") or reference["url"],
                    "url": reference["url"],
                }
            )

    document: dict[str, Any] = {
        "category": "csaf_base",
        "csaf_version": CSAF_VERSION,
        "lang": "en",
        "title": projection["title"],
        "publisher": publisher,
        "tracking": {
            "id": projection["id"],
            "status": "final",
            "version": revisions[-1]["number"],
            "initial_release_date": _stamp(published_at),
            "current_release_date": revisions[-1]["date"],
            "revision_history": revisions,
            "generator": {"engine": {"name": "sbomify", "version": generator}},
        },
        "distribution": {"tlp": {"label": _TLP.get(projection.get("visibility", ""), "WHITE")}},
        "references": references,
    }
    if notes:
        document["notes"] = notes
    if projection.get("severity"):
        document["aggregate_severity"] = {"text": str(projection["severity"]).title()}
    if projection.get("acknowledgments"):
        names = [a.get("name") for a in projection["acknowledgments"] if isinstance(a, dict) and a.get("name")]
        if names:
            document["acknowledgments"] = [{"names": names}]
    return document


def _score(vulnerability: dict[str, Any], product_ids: list[str]) -> dict[str, Any] | None:
    """The worst CVSS v3 entry as a CSAF score, or None when there is nothing CSAF 2.0 can carry.

    CSAF 2.0 has slots for CVSS v2 and v3 only, and its v3 object needs the
    vector, so an entry with a bare score or a v4 vector is left out rather
    than half-filled.
    """
    best: dict[str, Any] | None = None
    for entry in vulnerability.get("cvss_scores", []):
        match = _CVSS3_VECTOR_RE.match(str(entry.get("vector") or ""))
        if not match:
            continue
        if best is None or float(entry["base_score"]) > float(best["base_score"]):
            best = {**entry, "version": match.group(1)}
    if best is None or not product_ids:
        return None
    score = float(best["base_score"])
    return {
        "cvss_v3": {
            "version": best["version"],
            "vectorString": best["vector"],
            "baseScore": score,
            "baseSeverity": _base_severity(score),
        },
        "products": product_ids,
    }


def _vulnerability(vulnerability: dict[str, Any], rows: list[dict[str, Any]], tree: _ProductTree) -> dict[str, Any]:
    status_groups: dict[str, list[str]] = {}
    flags: dict[str, list[str]] = {}
    threats: list[dict[str, Any]] = []
    remediations: list[dict[str, Any]] = []
    scored: list[str] = []

    def add(group: str, product_id: str) -> None:
        bucket = status_groups.setdefault(group, [])
        if product_id not in bucket:
            bucket.append(product_id)

    for row in rows:
        group = _PRODUCT_STATUS.get(row["status"], "under_investigation")
        product = row["product"]
        affected_id = tree.id_for(product, row.get("affected", "") if group == "known_affected" else "")
        add(group, affected_id)
        if group == "known_affected":
            scored.append(affected_id)
            unaffected = row.get("unaffected", "")
            if unaffected not in _NO_VERSIONS:
                add("fixed", tree.id_for(product, unaffected))
        if group == "known_not_affected" and (label := _FLAGS.get(row.get("justification_value", ""))):
            flags.setdefault(label, []).append(affected_id)
        if row.get("impact_statement"):
            threats.append({"category": "impact", "details": row["impact_statement"], "product_ids": [affected_id]})
        details = row.get("action_statement") or (
            f"Update to {row['recommended_version']}." if row.get("recommended_version") else ""
        )
        if details:
            category = _REMEDIATION.get(
                row.get("response", ""), "vendor_fix" if row.get("recommended_version") else "mitigation"
            )
            remediations.append({"category": category, "details": details, "product_ids": [affected_id]})

    if exploit := _EXPLOIT_STATUS.get(vulnerability.get("exploitation_status", "")):
        threats.append({"category": "exploit_status", "details": exploit})

    item: dict[str, Any] = {}
    cve_id = str(vulnerability.get("cve_id") or "")
    if _CVE_RE.fullmatch(cve_id):
        item["cve"] = cve_id
    if title := vulnerability.get("title") or cve_id:
        item["title"] = title
    notes = []
    if vulnerability.get("description"):
        notes.append({"category": "description", "text": vulnerability["description"]})
    if vulnerability.get("recommendation"):
        notes.append({"category": "other", "title": "Recommendation", "text": vulnerability["recommendation"]})
    if notes:
        item["notes"] = notes
    if status_groups:
        item["product_status"] = status_groups
    if flags:
        item["flags"] = [{"label": label, "product_ids": ids} for label, ids in flags.items()]
    if score := _score(vulnerability, scored):
        item["scores"] = [score]
    if threats:
        item["threats"] = threats
    if remediations:
        item["remediations"] = remediations
    return item


def render_csaf(
    projection: dict[str, Any], *, publisher_name: str, publisher_namespace: str, self_url: str, generator: str
) -> dict[str, Any]:
    """The CSAF 2.0 document for one public advisory projection (``detail=True``).

    ``publisher_namespace`` is the workspace's own URL, which CSAF uses as the
    publisher's identity. The category is ``csaf_security_advisory`` when the
    document names products, and ``csaf_base`` for a notice that names none,
    since the advisory profile requires a product tree.
    """
    tree = _ProductTree()
    rows_by_vulnerability: dict[str, list[dict[str, Any]]] = {}
    for row in projection.get("statuses", []):
        rows_by_vulnerability.setdefault(row["vulnerability"], []).append(row)

    vulnerabilities = []
    for vulnerability in projection.get("vulnerabilities", []):
        rows = rows_by_vulnerability.get(vulnerability.get("cve_id") or vulnerability.get("title") or "", [])
        vulnerabilities.append(_vulnerability(vulnerability, rows, tree))

    publisher = {"category": "vendor", "name": publisher_name, "namespace": publisher_namespace}
    document = _document(projection, publisher=publisher, self_url=self_url, generator=generator)
    payload: dict[str, Any] = {"document": document}
    if tree.entries:
        payload["product_tree"] = {"full_product_names": tree.entries}
        if vulnerabilities and all("product_status" in v for v in vulnerabilities):
            document["category"] = "csaf_security_advisory"
    if vulnerabilities:
        payload["vulnerabilities"] = vulnerabilities
    return payload
