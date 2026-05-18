"""SBOM compliance service for BSI TR-03183-2 assessment status.

Provides functions to check BSI compliance status per product component
and evaluate overall SBOM compliance gates.
"""

from __future__ import annotations

from typing import Iterable

from django.db.models import Prefetch
from packaging.version import Version

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

BSI_PLUGIN_NAME = "bsi-tr03183-v2.1-compliance"

# Minimum format versions for BSI TR-03183-2 compliance
_MIN_FORMAT_VERSIONS: dict[str, str] = {
    "cyclonedx": "1.6",
    "spdx": "3.0.1",
}

# CRA-compliance-level classification of BSI findings (issue #907).
# Every normal-check finding id emitted by the BSI plugin (see
# ``plugins.builtins.bsi.FINDING_IDS``) gets a remediation_type.
# The special ``bsi-tr03183:error`` finding emitted on plugin
# execution failures is NOT classified here — it isn't a check
# result but an operational error and falls through to the
# ``operator_action`` default in ``_classify_bsi_finding`` so the
# operator is told to address it rather than wave it through.
#
# - ``tooling_limitation`` — the field is missing because an upstream
#   scanner (syft, trivy, anchore) does not emit it for apt/yum-
#   packaged components. The operator can fix this by re-running
#   ``sbomify-action`` with ``--enrich`` or by scanning the source
#   manifest (pyproject.toml, package.json, go.mod) instead of the
#   container image. A waiver is acceptable when the limitation is
#   documented and accepted.
#
# - ``operator_action`` — the field is expected to be configured
#   by the operator (contact email, licence text, attestation
#   signature) or represents a fundamental SBOM structural gap that
#   must be fixed before CRA submission. No waiver is appropriate;
#   the operator has to author the missing content.
#
# The wizard Step 2 UI renders the remediation_type inline so
# operators understand what action to take without digging through
# the full BSI remediation text.
_BSI_REMEDIATION_TYPE: dict[str, str] = {
    # Tooling-limitation checks — scanners don't emit these for
    # apt/yum-packaged components.
    "bsi-tr03183:hash-value": "tooling_limitation",
    "bsi-tr03183:executable-property": "tooling_limitation",
    "bsi-tr03183:archive-property": "tooling_limitation",
    "bsi-tr03183:structured-property": "tooling_limitation",
    "bsi-tr03183:filename": "tooling_limitation",
    "bsi-tr03183:source-code-uri": "tooling_limitation",
    "bsi-tr03183:uri-deployable-form": "tooling_limitation",
    # Operator-action checks — the operator authors, configures, or
    # structurally fixes these.
    "bsi-tr03183:sbom-format": "operator_action",
    "bsi-tr03183:sbom-creator": "operator_action",
    "bsi-tr03183:timestamp": "operator_action",
    "bsi-tr03183:component-creator": "operator_action",
    "bsi-tr03183:component-name": "operator_action",
    "bsi-tr03183:component-version": "operator_action",
    "bsi-tr03183:dependencies": "operator_action",
    "bsi-tr03183:distribution-licences": "operator_action",
    "bsi-tr03183:original-licences": "operator_action",
    "bsi-tr03183:sbom-uri": "operator_action",
    "bsi-tr03183:unique-identifiers": "operator_action",
    "bsi-tr03183:no-vulnerabilities": "operator_action",
    "bsi-tr03183:attestation-check": "operator_action",
}

# Default guidance URL for BSI findings without a more specific override.
_BSI_DEFAULT_GUIDANCE_URL = "https://sbomify.com/compliance/"

# BSI TR-03183-2 guidance page. The ``#format-requirements-4`` anchor is the
# best landing for ``sbom-format`` and is acceptable for ``attestation-check``
# (the BSI page is the standard reference for both; no separate attestation
# anchor exists yet). Swap individual overrides to per-finding constants once
# more specific pages (e.g. ``/compliance/attestations/``) ship.
_BSI_TR03183_GUIDANCE_URL = "https://sbomify.com/compliance/bsi-tr-03183/#format-requirements-4"

_BSI_GUIDANCE_URL_OVERRIDES: dict[str, str] = {
    "bsi-tr03183:sbom-format": _BSI_TR03183_GUIDANCE_URL,
    "bsi-tr03183:attestation-check": _BSI_TR03183_GUIDANCE_URL,
}

# Plain-English "why is this failing and what do I do about it" sentence
# per finding, rendered inline on Step 2 alongside the badge (issue
# #907 — this is the operator-facing context that the bare remediation
# prose from the BSI plugin doesn't provide). Text is kept terse so it
# fits one line in the wizard card.
_BSI_HUMAN_SUMMARY: dict[str, str] = {
    # Tooling-limitation: scanner-output gaps.
    "bsi-tr03183:hash-value": (
        "SBOM scanners like syft / trivy don't emit per-component SHA-512 for "
        "apt / yum packages. Re-run sbomify-action with --enrich or scan your "
        "source manifest (pyproject.toml, package.json) instead of a container image."
    ),
    "bsi-tr03183:executable-property": (
        "The isExecutable property is rarely emitted by container scanners. "
        "Run sbomify-action --enrich to annotate components, or author the "
        "SBOM from source where this can be set explicitly."
    ),
    "bsi-tr03183:archive-property": (
        "The isArchive property is rarely emitted by container scanners. "
        "Run sbomify-action --enrich to annotate components."
    ),
    "bsi-tr03183:structured-property": (
        "The isStructured property is a BSI-specific extension that most "
        "scanners don't emit. Use sbomify-action --enrich to annotate."
    ),
    "bsi-tr03183:filename": (
        "Scanner output often omits the component filename inside the image. "
        "Re-run with sbomify-action --enrich or use a source-manifest scan."
    ),
    "bsi-tr03183:source-code-uri": (
        "Source repository URL per component is rarely emitted by container "
        "scanners. Enrich via sbomify-action or author from the source manifest."
    ),
    "bsi-tr03183:uri-deployable-form": (
        "Deployable-form URL per component is rarely available in container "
        "scans. Enrich via sbomify-action or document at the product level."
    ),
    # Operator-action: authoring / configuration gaps.
    "bsi-tr03183:sbom-format": (
        "The SBOM format or version doesn't meet BSI TR-03183-2 §4. "
        "Upgrade your SBOM generator to emit CycloneDX >= 1.6 or SPDX >= 3.0.1."
    ),
    "bsi-tr03183:sbom-creator": (
        "The SBOM lacks a creator identity. Configure your SBOM generator "
        "(or sbomify team settings) with the contact email or URL of the "
        "entity producing the SBOM."
    ),
    "bsi-tr03183:timestamp": (
        "The SBOM is missing an ISO-8601 creation timestamp. Modern "
        "CycloneDX / SPDX generators add this automatically — upgrade yours."
    ),
    "bsi-tr03183:component-creator": (
        "Per-component creator identities are missing. This typically "
        "requires manual authoring or an enrichment plugin — sbomify-action "
        "--enrich is the recommended path."
    ),
    "bsi-tr03183:component-name": (
        "One or more components have no name. Fix in your SBOM source — "
        "this is a structural SBOM requirement, not a tooling limitation."
    ),
    "bsi-tr03183:component-version": ("One or more components have no version. Fix in your SBOM source."),
    "bsi-tr03183:dependencies": (
        "Dependency relationships are incomplete. Ensure your SBOM "
        "generator includes the dependency graph (CycloneDX 'dependencies' "
        "or SPDX 'relationships')."
    ),
    "bsi-tr03183:distribution-licences": (
        "Distribution licences are missing on some components. Licence "
        "data often requires a dedicated licence-scanning tool upstream "
        "of SBOM generation."
    ),
    "bsi-tr03183:original-licences": (
        "Original licences are missing on some components. Same remediation "
        "as distribution licences — use a licence scanner upstream."
    ),
    "bsi-tr03183:sbom-uri": (
        "The SBOM carries no canonical URI. Configure your generator to "
        "emit the bom.metadata.component.externalReferences URL."
    ),
    "bsi-tr03183:unique-identifiers": (
        "Components are missing unique identifiers (PURL / CPE). Ensure "
        "your generator emits at least a purl for every component."
    ),
    "bsi-tr03183:no-vulnerabilities": (
        "The SBOM embeds vulnerability data inline — BSI TR-03183-2 "
        "prohibits this; vulnerabilities belong in a separate VEX / VDR "
        "document referenced by the SBOM."
    ),
    "bsi-tr03183:attestation-check": (
        "No cryptographic attestation is attached to the SBOM. Enable "
        "sigstore / cosign attestation via a signing plugin or "
        "sbomify-action signing."
    ),
}


_UNKNOWN_FINDING_SUMMARY = (
    "Unclassified BSI finding. Treat as operator_action until the "
    "classifier is updated — fix the underlying SBOM gap or file an issue."
)


def _classify_bsi_finding(finding_id: object) -> tuple[str, str, str]:
    """Return ``(remediation_type, guidance_url, human_summary)`` for a BSI finding id.

    Accepts ``object`` rather than ``str`` because the run payload is
    JSON round-tripped and a broken upstream plugin (or corrupted DB
    row) can land here with a list/dict/int in place of the string
    id. ``dict.get()`` with an unhashable key raises
    ``TypeError``, which would break BSI classification for every
    finding in the scan. Coerce to the fail-closed default instead.

    Unknown or non-string finding ids fall back to ``operator_action``
    + ``_BSI_DEFAULT_GUIDANCE_URL`` + a generic summary — the
    conservative default keeps the wizard gate strict when the BSI
    plugin gains a new check that this classifier hasn't been updated
    for yet, or when upstream emits a malformed id that the
    ``_build_bsi_assessment_dict`` coercion didn't catch.

    The ``human_summary`` is a one-line operator-facing sentence
    (issue #907) explaining in plain English why this check fails
    and what to do — e.g. "syft doesn't emit SHA-512 for apt packages;
    re-run with sbomify-action --enrich". Renders inline on Step 2
    alongside the badge so operators don't have to piece together
    the remediation from the BSI plugin's schema-oriented text.
    """
    if not isinstance(finding_id, str):
        return "operator_action", _BSI_DEFAULT_GUIDANCE_URL, _UNKNOWN_FINDING_SUMMARY
    remediation_type = _BSI_REMEDIATION_TYPE.get(finding_id, "operator_action")
    guidance_url = _BSI_GUIDANCE_URL_OVERRIDES.get(finding_id, _BSI_DEFAULT_GUIDANCE_URL)
    human_summary = _BSI_HUMAN_SUMMARY.get(finding_id, _UNKNOWN_FINDING_SUMMARY)
    return remediation_type, guidance_url, human_summary


def is_known_bsi_finding(finding_id: str) -> bool:
    """True iff ``finding_id`` is in the classifier whitelist.

    Public waiver-save validation: the wizard rejects waiver payloads
    that reference finding ids we don't classify. Keeps typos from
    silently poisoning the ``bsi_waivers`` map.
    """
    return isinstance(finding_id, str) and finding_id in _BSI_REMEDIATION_TYPE


def is_waivable_bsi_finding(finding_id: object) -> bool:
    """True iff ``finding_id`` is a tooling-limitation (waiver-eligible).

    Public predicate for waiver-save validation. Keeps the
    ``_BSI_REMEDIATION_TYPE`` dict private to this module — consumers
    ask the question "can this be waived?" without seeing the
    classifier's internals. Typed ``object`` because the waiver save
    path deserialises user JSON: non-string payloads (list / dict /
    None) must fail closed rather than crash ``dict.get`` with
    ``TypeError: unhashable type``.
    """
    if not isinstance(finding_id, str):
        return False
    return _BSI_REMEDIATION_TYPE.get(finding_id) == "tooling_limitation"


def _prefetch_sbomify_action_flags(sboms: Iterable[SBOM]) -> None:
    """Warm the per-SBOM sbomify-action detection cache concurrently.

    Only SBOMs whose latest BSI run has at least one tooling_limitation
    failing check need the flag (per ``_build_bsi_assessment_dict``); the
    rest skip the S3 fetch anyway. Looking up the cache here in a thread
    pool turns the otherwise serial per-component S3 reads into one
    bounded burst, so the wall-clock cost of a cold-cache Step 2 render
    is roughly the slowest single fetch rather than N times that.
    """
    from concurrent.futures import ThreadPoolExecutor

    sboms_needing_lookup: list[SBOM] = []
    for sbom in sboms:
        runs = getattr(sbom, "prefetched_bsi_runs", None) or []
        if not runs:
            continue
        findings = (runs[0].result or {}).get("findings") or []
        if any(
            isinstance(f, dict)
            and f.get("status") == "fail"
            and _classify_bsi_finding(f.get("id", ""))[0] == "tooling_limitation"
            for f in findings
        ):
            sboms_needing_lookup.append(sbom)

    if not sboms_needing_lookup:
        return

    # max_workers caps the burst so a product with thousands of components
    # cannot exhaust the S3 client's connection pool.
    max_workers = min(10, len(sboms_needing_lookup))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(sbom_was_generated_by_sbomify_action, sboms_needing_lookup))


def _is_format_compliant(sbom_format: str | None, format_version: str | None) -> bool:
    """Check whether the SBOM format version meets BSI TR-03183-2 requirements.

    CycloneDX >= 1.6 or SPDX >= 3.0.1 is required.
    """
    if not sbom_format or not format_version:
        return False

    min_version_str = _MIN_FORMAT_VERSIONS.get(sbom_format.lower())
    if not min_version_str:
        return False

    try:
        return Version(format_version) >= Version(min_version_str)
    except (ValueError, TypeError):
        return False


def _build_bsi_assessment_dict(run: AssessmentRun, sbom: SBOM | None = None) -> dict[str, object]:
    """Build the bsi_assessment dict from an AssessmentRun.

    ``sbom`` is optional and only used to compute the
    ``was_generated_by_sbomify_action`` flag the wizard template uses to
    suppress the "See sbomify-action enrichment guide" CTA for SBOMs
    already generated by sbomify-action (issue #902). When omitted, the
    flag defaults to ``False`` and the CTA renders as before.
    """
    result = run.result or {}
    summary = result.get("summary", {})
    raw_findings = result.get("findings", [])

    # Extract failing findings with fix guidance + CRA-compliance
    # classification (issue #907). ``remediation_type`` tells the
    # wizard whether this is an operator action or a known tooling
    # limitation; ``guidance_url`` points at the sbomify-action docs
    # covering the remediation path.
    failing_checks: list[dict[str, str]] = []
    for f in raw_findings:
        if f.get("status") == "fail":
            # Coerce non-string ids to "" so a malformed/corrupted
            # run payload (list, dict, int stored in the JSON blob)
            # can't raise ``TypeError: unhashable type`` when
            # ``_classify_bsi_finding`` uses the value as a dict
            # key. Fail-closed: unknown id maps to the default
            # ``operator_action`` classification.
            raw_id = f.get("id", "")
            finding_id = raw_id if isinstance(raw_id, str) else ""
            remediation_type, guidance_url, human_summary = _classify_bsi_finding(finding_id)
            failing_checks.append(
                {
                    "id": finding_id,
                    "title": f.get("title", ""),
                    "description": f.get("description", ""),
                    "remediation": f.get("remediation", ""),
                    "remediation_type": remediation_type,
                    "guidance_url": guidance_url,
                    "human_summary": human_summary,
                }
            )

    # Issue #902: only fetch + parse the SBOM blob from S3 when at least one
    # failing check is a tooling_limitation. The flag exists solely to gate
    # the "See sbomify-action enrichment guide" CTA on those findings, so
    # passing assessments and assessments whose failures are all
    # operator_action skip the S3 round-trip entirely.
    has_tooling_limitation_failure = any(c["remediation_type"] == "tooling_limitation" for c in failing_checks)
    was_generated_by_sbomify_action_flag = bool(
        sbom and has_tooling_limitation_failure and sbom_was_generated_by_sbomify_action(sbom)
    )

    return {
        "status": run.status,
        "pass_count": summary.get("pass_count", 0),
        "fail_count": summary.get("fail_count", 0),
        "warning_count": summary.get("warning_count", 0),
        "assessed_at": run.created_at.isoformat() if run.created_at else None,
        "failing_checks": failing_checks,
        "was_generated_by_sbomify_action": was_generated_by_sbomify_action_flag,
    }


def get_bsi_assessment_status(product: Product) -> ServiceResult[dict[str, object]]:
    """Query AssessmentRun for BSI plugin per product component.

    Returns a ServiceResult containing component-level BSI assessment
    details and an overall summary.

    """
    from django.db.models import OuterRef, Subquery

    # Annotate each component with its latest SBOM id to avoid loading all history
    latest_sbom_subquery = SBOM.objects.filter(component=OuterRef("pk")).order_by("-created_at").values("pk")[:1]

    components = list(
        Component.objects.filter(products=product)
        .order_by("name")
        .distinct()
        .annotate(latest_sbom_id=Subquery(latest_sbom_subquery))
    )

    # Batch-fetch the latest SBOMs and their BSI runs
    sbom_ids = [c.latest_sbom_id for c in components if c.latest_sbom_id]
    sboms_by_id: dict[str, SBOM] = {}
    if sbom_ids:
        sbom_qs = SBOM.objects.filter(pk__in=sbom_ids).prefetch_related(
            Prefetch(
                "assessment_runs",
                queryset=AssessmentRun.objects.filter(plugin_name=BSI_PLUGIN_NAME).order_by("-created_at"),
                to_attr="prefetched_bsi_runs",
            )
        )
        sboms_by_id = {s.pk: s for s in sbom_qs}

    # Warm the sbomify-action detection cache concurrently for every SBOM
    # that has at least one tooling_limitation failing check. Without this
    # batched prefetch, each per-component call to _build_bsi_assessment_dict
    # would do its own serial S3 fetch on a cold cache, turning Step 2
    # rendering into O(N) sequential round trips for large products.
    _prefetch_sbomify_action_flags(sboms_by_id.values())

    component_results: list[dict[str, object]] = []
    components_with_sbom = 0
    components_passing_bsi = 0

    for component in components:
        latest_sbom: SBOM | None = sboms_by_id.get(component.latest_sbom_id) if component.latest_sbom_id else None

        has_sbom = latest_sbom is not None
        sbom_format: str | None = latest_sbom.format if latest_sbom else None
        sbom_format_version: str | None = latest_sbom.format_version if latest_sbom else None
        format_compliant = _is_format_compliant(sbom_format, sbom_format_version)

        bsi_assessment: dict[str, object] | None = None
        is_passing = False

        if has_sbom:
            components_with_sbom += 1

            prefetched_runs = getattr(latest_sbom, "prefetched_bsi_runs", [])
            latest_run = prefetched_runs[0] if prefetched_runs else None

            if latest_run:
                bsi_assessment = _build_bsi_assessment_dict(latest_run, sbom=latest_sbom)
                if latest_run.status == "completed" and bsi_assessment["fail_count"] == 0 and format_compliant:
                    is_passing = True

        if is_passing:
            components_passing_bsi += 1

        bsi_status: str | None = None
        if bsi_assessment:
            bsi_status = str(bsi_assessment.get("status")) if bsi_assessment.get("status") is not None else None

        component_results.append(
            {
                "component_id": component.id,
                "component_name": component.name,
                "component_url": f"/component/{component.id}/",
                "has_sbom": has_sbom,
                "sbom_format": sbom_format,
                "sbom_format_version": sbom_format_version or None,
                "format_compliant": format_compliant,
                "bsi_assessment": bsi_assessment,
                "bsi_status": bsi_status,
            }
        )

    total_components = len(component_results)
    overall_gate = components_passing_bsi > 0

    return ServiceResult.success(
        {
            "components": component_results,
            "summary": {
                "total_components": total_components,
                "components_with_sbom": components_with_sbom,
                "components_passing_bsi": components_passing_bsi,
                "overall_gate": overall_gate,
            },
        }
    )


def check_sbom_gate(product: Product) -> ServiceResult[bool]:
    """Check whether the product passes the SBOM compliance gate.

    At least one component must have a passing BSI assessment.
    Passing means AssessmentRun with status=completed and fail_count=0.
    """
    result = get_bsi_assessment_status(product)
    if not result.ok:
        return ServiceResult.failure(result.error or "Failed to get BSI assessment status")

    if not result.value:
        return ServiceResult.success(False)
    summary = result.value["summary"]
    gate_passes = bool(isinstance(summary, dict) and summary.get("overall_gate", False))
    return ServiceResult.success(gate_passes)
