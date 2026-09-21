from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.authz import can
from sbomify.apps.core.errors import error_response
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin

logger = logging.getLogger(__name__)

#: Packages per page. Each one expands into a card per advisory, so the page
#: weight is a multiple of this rather than equal to it; 25 keeps the full
#: report comparable in size to the component page's paged panel.
PACKAGES_PER_PAGE = 25

#: Advisory cards rendered for one package. Paging the packages bounds how many
#: groups a response holds, not how many cards: a kernel package in a BSP image
#: can carry hundreds of advisories on its own, and twenty-five of those rebuild
#: the oversized response this page was paginated to avoid. Together the two
#: numbers put a hard ceiling on the page.
#:
#: The rest are not lost. Advisories are ordered worst-first, the row says how
#: many were left out, and the component page's panel pages through every
#: finding of the artifact with search and filters.
MAX_ADVISORIES_PER_PACKAGE = 10

#: This report's filter controls. Its own page, so nothing would collide with
#: the component panel's ``vuln_`` or the assessment card's ``run_``, but naming
#: them keeps a link carrying more than one readable.
PARAM_PREFIX = "scan_"


def _advisory_matches(advisory: dict[str, Any], package: dict[str, Any], query: Any) -> bool:
    """Whether one merged advisory survives the toolbar.

    The browse engine reads a flatter shape than this page builds, and this page
    merges across providers into its own entries rather than using
    ``extract_finding_rows``. So the few keys the predicates read are gathered
    here, the same way the assessment card does it. The package arrives as its
    own argument because it belongs to the entry rather than the advisory, and
    copying it onto each advisory to pass it along is one dict per advisory on a
    report that can hold thousands.
    """
    from sbomify.apps.vulnerability_scanning.services.finding_browse import matches_query

    return matches_query(
        {
            "id": advisory.get("id") or "",
            "aliases": advisory.get("aliases") or [],
            "package": package.get("name") or "",
            "ecosystem": package.get("ecosystem") or "",
            "severity": advisory.get("severity") or "",
            "vex_state": advisory.get("vex_state") or "",
            "vex_suppressed": bool(advisory.get("vex_suppressed")),
            "kev": bool(advisory.get("kev")),
        },
        query,
    )


def _narrows_rows(query: Any) -> bool:
    """Whether the toolbar is hiding anything.

    ``FindingQuery.is_filtered`` covers search, severity, state and KEV, but not
    the suppressed toggle, and the public trust-center browse reads that same
    property, so widening it there would change a page this has no business
    changing. Hiding suppressed advisories is a filter from the reader's side,
    though: unticking the box has to narrow the list, and the toolbar has to keep
    offering a way back.
    """
    return bool(query.is_filtered) or not query.show_suppressed


def _severity_options(packages: list[dict[str, Any]], query: Any) -> list[str]:
    """The severities the dropdown offers, worst first.

    Built from every advisory rather than the filtered set, so choosing one
    severity does not empty the dropdown that chose it. The shared helper also
    keeps the active token when no advisory carries it, which is what a
    bookmarked ``scan_severity=moderate`` needs: without it the select renders
    as "All Severities" over an empty report and the reader cannot see what
    emptied it.
    """
    from sbomify.apps.vulnerability_scanning.services.finding_browse import SEVERITY_ORDER, present_options

    return present_options(
        [
            str(advisory.get("severity") or "").lower()
            for entry in packages
            for advisory in entry["vulnerabilities"]
            if advisory.get("severity")
        ],
        SEVERITY_ORDER,
        query.severity,
    )


def _filtered_packages(packages: list[dict[str, Any]], query: Any) -> list[dict[str, Any]]:
    """Packages whose advisories still have something to show."""
    if not _narrows_rows(query):
        return packages

    kept: list[dict[str, Any]] = []
    for entry in packages:
        package = entry["package"]
        surviving = [advisory for advisory in entry["vulnerabilities"] if _advisory_matches(advisory, package, query)]
        if surviving:
            kept.append({**entry, "vulnerabilities": surviving})
    return kept


class SbomVulnerabilitiesView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        try:
            sbom: SBOM = SBOM.objects.get(pk=sbom_id)
        except SBOM.DoesNotExist:
            return error_response(request, HttpResponseNotFound("SBOM not found"))

        if not can(request, "sbom:manage", sbom):
            return error_response(
                request, HttpResponseForbidden("You don't have permission to view this SBOM's vulnerabilities")
            )

        vulnerabilities_data: dict[str, Any] | None = None
        # Built before the try because the template reads it on every path. The
        # toolbar itself only renders once there is something to render: an
        # option list, or an active filter. That second half is why this is not
        # inside the try, since a scan that fails while a filter is on would
        # otherwise drop the control the reader needs to clear it.
        from sbomify.apps.vulnerability_scanning.services.finding_browse import parse_finding_query

        scan_query = parse_finding_query(request.GET, prefix=PARAM_PREFIX)
        scan_severity_options: list[str] = []
        scan_timestamp_str = None
        error_message = None
        error_details = None
        is_processing = False
        processing_message = None
        sbom_version_info = None
        latest_result = None
        package_page = None
        page_range: list[Any] = []

        try:
            # One section per provider: the latest completed run of each scanner
            # that has assessed this SBOM, newest provider first.
            provider_runs = list(
                AssessmentRun.objects.filter(
                    sbom=sbom,
                    category="security",
                    status="completed",
                )
                .order_by("plugin_name", "-created_at")
                .distinct("plugin_name")
            )
            provider_runs.sort(key=lambda run: run.created_at, reverse=True)
            latest_result = provider_runs[0] if provider_runs else None

            if latest_result:
                scan_timestamp_str = latest_result.created_at.strftime("%B %d, %Y at %I:%M %p %Z")

                sbom_version_info = {
                    "name": sbom.name,
                    "version": sbom.version,
                    "component_name": sbom.component.name,
                    "format": sbom.format,
                    "format_version": sbom.format_version,
                    "source": sbom.source_display,
                }

                from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK as severity_rank
                from sbomify.apps.vulnerability_scanning.utils import is_vulnerability

                query = scan_query

                def package_identity(component: dict[str, Any]) -> tuple[str, str, str, str, str]:
                    """(tail_key, purl_base, name, version, ecosystem) for a finding's component."""
                    package_name = component.get("name", "Unknown Package")
                    package_version = component.get("version", "Unknown Version")
                    package_ecosystem = component.get("ecosystem", "Unknown")
                    purl = component.get("purl", "") or ""
                    if (not package_ecosystem or package_ecosystem in ["Unknown", "unknown"]) and purl.startswith(
                        "pkg:"
                    ):
                        try:
                            package_ecosystem = purl.split(":")[1].split("/")[0]
                        except (IndexError, AttributeError):
                            package_ecosystem = "Unknown"
                    artifact = package_name.split(":")[-1]
                    tail_key = f"{artifact}:{package_version}:{package_ecosystem}".lower()
                    purl_base = ""
                    if purl.startswith("pkg:"):
                        base = purl.split("?")[0]
                        # Strip the version suffix so a provider that omits the
                        # version in its purl still folds into the same row; a
                        # raw "@" that is followed by "/" is an npm scope, not
                        # a version separator.
                        head, sep, version_tail = base.rpartition("@")
                        if sep and "/" not in version_tail:
                            base = head
                        purl_base = base.lower()
                    return tail_key, purl_base, package_name, package_version, package_ecosystem

                # Pre-scan the purl namespaces per artifact-tail key. Providers
                # name the same package differently (OSV "group:artifact", DT
                # just "artifact"), so rows merge on the artifact tail — but two
                # DISTINCT packages can share a tail (two Maven groupIds with
                # the same artifact and version). The purl base disambiguates:
                # distinct bases split into separate rows, and a purl-less row
                # joins the tail's single purl-carrying group when exactly one
                # exists (the unambiguous cross-provider case).
                # Materialize each finding's identity once; the pre-scan and
                # the merge loop below share it instead of re-parsing every
                # purl twice.
                # The component's uploaded VEX, which is what the drill-down
                # table reads. Deliberately NOT resolve_vex_statements_for_sbom:
                # that re-derives the statements embedded in the document by
                # fetching the document itself from S3, and a Yocto image is
                # megabytes. It does not need re-deriving. The orchestrator
                # already wrote the scan's verdict onto each finding as
                # analysis_state, and that is read first below, so embedded VEX
                # is honoured without the page paying for it. These statements
                # only decide the case the stored state cannot: a VEX uploaded
                # after the scan ran.
                from sbomify.apps.vulnerability_scanning.vex import (
                    SUPPRESSED_STATES,
                    find_in_index,
                    load_vex_suppressions,
                    statement_index,
                )

                # Loaded on the first finding that needs it and indexed once,
                # then reused: a page whose findings all carry a stored state
                # never reads the VEX at all, and one that does pays a single
                # S3 fetch and O(findings + statements) matching rather than a
                # rebuilt index per finding.
                vex_index: dict[str, list[tuple[int, dict[str, Any]]]] | None = None

                def vex_state_of(finding: dict[str, Any]) -> str:
                    """The finding's VEX state: stored first, live statements second.

                    Same precedence as extract_finding_rows, so this page and the
                    drill-down table cannot disagree about one finding.
                    """
                    nonlocal vex_index
                    state = finding.get("analysis_state") or ""
                    if state:
                        return state
                    if vex_index is None:
                        # [] when the artifact is absent or unreadable, so an
                        # unreadable VEX costs the after-the-scan overlay and
                        # nothing else: what the scan itself cleared is already
                        # on each finding. Anything genuinely unexpected belongs
                        # to this view's outer handler rather than a catch here.
                        vex_index = statement_index(load_vex_suppressions(sbom.component_id))
                    statement = find_in_index(finding, vex_index) if vex_index else None
                    return (statement.get("state") or "") if statement else ""

                identified: list[tuple[dict[str, Any], tuple[str, str, str, str, str]]] = []
                purl_bases_by_tail: dict[str, set[str]] = {}
                for run in provider_runs:
                    findings = (run.result or {}).get("findings", [])
                    if not isinstance(findings, list):
                        continue
                    for vuln in findings:
                        if not isinstance(vuln, dict):
                            continue
                        # Scanner status markers (dependency-track:no-product,
                        # osv:error) ride the findings array but are not
                        # vulnerabilities; without this they render as a bogus
                        # "Unknown" package with one finding.
                        if not is_vulnerability(vuln):
                            continue
                        identity = package_identity(vuln.get("component", {}) or {})
                        identified.append((vuln, identity))
                        tail_key, purl_base, *_ = identity
                        if purl_base:
                            purl_bases_by_tail.setdefault(tail_key, set()).add(purl_base)

                # One merged view across every provider's latest run: providers
                # report the same issue under different ids (DT: CVE, OSV: GHSA
                # with the CVE as alias), so findings sharing any id/alias fold
                # into one entry with the worst severity and the union of ids.
                packages_dict: dict[str, dict[str, Any]] = {}
                for vuln, identity in identified:
                    tail_key, purl_base, package_name, package_version, package_ecosystem = identity
                    known_bases = purl_bases_by_tail.get(tail_key, set())
                    if not purl_base and len(known_bases) == 1:
                        purl_base = next(iter(known_bases))
                    package_key = f"{tail_key}|{purl_base}" if purl_base else tail_key

                    entry = packages_dict.setdefault(
                        package_key,
                        {
                            "package": {
                                "name": package_name,
                                "version": package_version,
                                "ecosystem": package_ecosystem,
                            },
                            "vulnerabilities": [],
                            "_by_alias": {},
                        },
                    )

                    ids = {str(vuln.get("id") or "")} | {str(a) for a in (vuln.get("aliases") or [])}
                    ids.discard("")
                    alias_keys = {i.lower() for i in ids}
                    merged = next((entry["_by_alias"][key] for key in alias_keys if key in entry["_by_alias"]), None)
                    severity = (vuln.get("severity") or "medium").lower()

                    vex_state = vex_state_of(vuln)
                    suppressed = vex_state in SUPPRESSED_STATES

                    if merged is None:
                        merged = {
                            "_ids": set(),
                            "id": "Unknown",
                            "aliases": [],
                            "summary": vuln.get("title") or vuln.get("summary", ""),
                            "details": vuln.get("description", ""),
                            "severity": severity,
                            "cvss_score": vuln.get("cvss_score"),
                            "references": list(vuln.get("references") or []),
                            "source": vuln.get("source", "Unknown"),
                            "affected": vuln.get("affected", []),
                            "vex_state": vex_state,
                            "vex_suppressed": suppressed,
                        }
                        entry["vulnerabilities"].append(merged)
                    else:
                        if severity_rank.get(severity, 5) < severity_rank.get(merged["severity"], 5):
                            merged["severity"] = severity
                        if (vuln.get("cvss_score") or 0) > (merged.get("cvss_score") or 0):
                            merged["cvss_score"] = vuln.get("cvss_score")
                        if not merged["summary"]:
                            merged["summary"] = vuln.get("title") or vuln.get("summary", "")
                        if not merged["details"]:
                            merged["details"] = vuln.get("description", "")
                        for reference in vuln.get("references") or []:
                            if reference not in merged["references"]:
                                merged["references"].append(reference)
                        # Suppressed only when every provider reporting it is.
                        # One scanner still calling it live is the answer that
                        # matters, and the state is kept for the marking.
                        if not suppressed:
                            merged["vex_suppressed"] = False
                            # Only a suppressing state contradicts the flag this
                            # just cleared. A non-suppressing one (in_triage,
                            # exploitable) says something true about a finding
                            # that is still open, so dropping it would lose the
                            # only place the page carries it.
                            if merged["vex_state"] in SUPPRESSED_STATES:
                                merged["vex_state"] = ""
                        elif merged.get("vex_suppressed") and not merged.get("vex_state"):
                            merged["vex_state"] = vex_state

                    merged["_ids"] |= ids
                    for key in alias_keys:
                        entry["_by_alias"][key] = merged

                if packages_dict:
                    for entry in packages_dict.values():
                        entry.pop("_by_alias", None)
                        # The headline counts what is still open. Suppressed
                        # advisories stay in the list, marked, because this
                        # page's job is the advisory list; counting them as
                        # live is what the card used to do.
                        entry["open_count"] = sum(1 for v in entry["vulnerabilities"] if not v.get("vex_suppressed"))
                        entry["suppressed_count"] = len(entry["vulnerabilities"]) - entry["open_count"]
                        for merged in entry["vulnerabilities"]:
                            merged_ids = sorted(merged.pop("_ids"))
                            display_id = next((i for i in merged_ids if i.lower().startswith("cve-")), None) or (
                                merged_ids[0] if merged_ids else "Unknown"
                            )
                            merged["id"] = display_id
                            merged["aliases"] = [i for i in merged_ids if i != display_id]
                        # Worst first: severity rank, then CVSS descending within a rank.
                        entry["vulnerabilities"].sort(
                            key=lambda v: (
                                severity_rank.get((v.get("severity") or "").lower(), 5),
                                -(v.get("cvss_score") or 0),
                            )
                        )

                    # Packages worst-first too, by the advisory each one leads
                    # with. The list is paginated below, so its order decides
                    # what page one holds; leaving it in provider order would put
                    # a critical on page 40 of a Yocto image because that is
                    # where the scanner happened to report it. Name breaks ties
                    # so the same scan always pages the same way.
                    packages = sorted(
                        packages_dict.values(),
                        key=lambda entry: (
                            severity_rank.get((entry["vulnerabilities"][0].get("severity") or "").lower(), 5)
                            if entry["vulnerabilities"]
                            else 6,
                            -(entry["vulnerabilities"][0].get("cvss_score") or 0) if entry["vulnerabilities"] else 0,
                            entry["package"]["name"].lower(),
                        ),
                    )

                    # One page of packages, not all of them. Each package renders
                    # a card per advisory, so a BSP-class SBOM with thousands of
                    # findings was building tens of megabytes of HTML for a
                    # reader who sees the first screen of it: 5.1s of render on
                    # the component page's smaller version of the same table,
                    # against a 30s gateway timeout.
                    # Filter the advisories inside each package, then drop the
                    # packages left holding nothing. The grouping is what this
                    # page is for, so a severity filter answers "which packages
                    # have a critical" rather than flattening into a list the
                    # component panel already serves better.
                    #
                    # The counts computed above are deliberately not recomputed:
                    # open_count and suppressed_count describe the whole package,
                    # which is what the reader is deciding about. A row saying
                    # "1 of 40" under a critical filter is the useful reading;
                    # one saying "1 of 1" hides the other 39.
                    scan_severity_options = _severity_options(packages, scan_query)
                    packages = _filtered_packages(packages, query)

                    paginator = Paginator(packages, PACKAGES_PER_PAGE)
                    package_page = paginator.get_page(request.GET.get("page"))
                    page_range = list(paginator.get_elided_page_range(package_page.number, on_each_side=1, on_ends=1))

                    # Paging the packages alone does not bound the page. The
                    # cards are advisories, not packages, and one package can
                    # carry hundreds of them: a kernel or a libc in a BSP image
                    # does. Twenty-five packages each holding four hundred
                    # advisories rebuilds exactly the response this change
                    # exists to prevent, so the nested list is capped too and
                    # the ceiling becomes PACKAGES_PER_PAGE x this.
                    #
                    # Capped after open_count and suppressed_count are computed,
                    # so the row still summarises the whole package rather than
                    # the part of it being shown. Rows are already worst-first,
                    # so the cap keeps the advisories that matter; the count
                    # beside them says what was left out, and the component
                    # panel pages through every one of them with search.
                    for entry in package_page:
                        total = len(entry["vulnerabilities"])
                        entry["shown_count"] = min(total, MAX_ADVISORIES_PER_PACKAGE)
                        entry["hidden_count"] = total - entry["shown_count"]
                        entry["vulnerabilities"] = entry["vulnerabilities"][:MAX_ADVISORIES_PER_PACKAGE]

                    vulnerabilities_data = {"results": [{"packages": list(package_page)}]}

                # Check for error metadata on the newest run
                result_json = latest_result.result or {}
                metadata = result_json.get("metadata", {})
                if metadata.get("error"):
                    error_message = "An error occurred during vulnerability scanning"
                    # Check findings for error details
                    for f in result_json.get("findings", []) or []:
                        if f.get("status") == "error":
                            error_message = f.get("description", error_message)
                            break

        except Exception as e:
            error_message = f"An unexpected error occurred while fetching vulnerability data: {str(e)}"
            logger.error(f"Unexpected error in sbom_vulnerabilities view for SBOM {sbom_id}: {e}", exc_info=True)

        # Page-header breadcrumb trail, built here per the design system
        # contract: list-shaped header params come from the view.
        breadcrumb_items = [
            {
                "label": sbom.component.name,
                "url": reverse("core:component_details", args=[sbom.component.id]),
            },
            {
                "label": sbom.name,
                "url": reverse(
                    "core:component_item",
                    kwargs={"component_id": sbom.component.id, "item_type": "sboms", "item_id": sbom.id},
                ),
            },
            {"label": "Vulnerabilities"},
        ]

        return render(
            request,
            "sboms/sbom_vulnerabilities.html.j2",
            {
                "sbom": sbom,
                "breadcrumb_items": breadcrumb_items,
                "vulnerabilities": vulnerabilities_data,
                "page_obj": package_page,
                "page_range": page_range,
                "scan_query": scan_query,
                "scan_severity_options": scan_severity_options,
                "scan_is_narrowed": _narrows_rows(scan_query),
                "scan_timestamp": scan_timestamp_str,
                "sbom_version_info": sbom_version_info,
                "error_message": error_message,
                "error_details": error_details,
                "APP_BASE_URL": settings.APP_BASE_URL,
                "team_billing_plan": getattr(sbom.component.team, "billing_plan", "community"),
                "is_processing": is_processing,
                "processing_message": processing_message,
                "processing_provider": latest_result.plugin_name.replace("-", " ").title()
                if latest_result and is_processing
                else None,
            },
        )
