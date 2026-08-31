from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.apis import _build_item_response, get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_public_path,
    get_workspace_public_url,
    resolve_component_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.documents.services.documents import get_document_detail
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.public_assessment_utils import get_sbom_passing_assessments, passing_assessments_to_dict
from sbomify.apps.sboms.services.sboms import get_sbom_detail
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.logging import getLogger

logger = getLogger(__name__)


class ComponentItemPublicView(View):
    def get(self, request: HttpRequest, component_id: str, item_type: str, item_id: str) -> HttpResponse:
        # Resolve component by slug (on custom domains) or ID (on main app)
        component_obj = resolve_component_identifier(request, component_id)
        if not component_obj:
            return error_response(request, HttpResponseNotFound("Component not found"))

        # Use the resolved component's ID for API calls
        resolved_id = component_obj.id
        component_slug = component_obj.slug

        status_code, component = get_component(request, resolved_id, return_instance=True)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        if item_type in ("sboms", "vex", "cbom", "hbom"):
            result = get_sbom_detail(request, item_id)
            if not result.ok:
                return error_response(
                    request,
                    HttpResponse(status=result.status_code or 400, content=result.error or "Unknown error"),
                )
            item = result.value

        elif item_type == "documents":
            result = get_document_detail(request, item_id)
            if not result.ok:
                return error_response(
                    request,
                    HttpResponse(status=result.status_code or 400, content=result.error or "Unknown error"),
                )
            item = result.value

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if component.team and (
            should_redirect_to_custom_domain(request, component.team) or should_redirect_to_clean_url(request)
        ):
            path = get_public_path(
                "component",
                resolved_id,
                is_custom_domain=True,
                slug=component_slug,
                item_type=item_type,
                item_id=item_id,
            )
            return HttpResponseRedirect(build_custom_domain_url(component.team, path, request.is_secure()))

        brand = build_branding_context(component.team)

        # Get workspace public URL for breadcrumbs
        workspace_public_url = get_workspace_public_url(request, component.team)

        # Get passing assessments for SBOMs
        passing_assessments = []
        if item_type == "sboms":
            sbom_passing = get_sbom_passing_assessments(item_id)
            passing_assessments = passing_assessments_to_dict(sbom_passing)

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "brand": brand,
            "item": item,
            "item_type": item_type,
            "component": _build_item_response(request, component, "component"),
            "passing_assessments": passing_assessments,
            "workspace_public_url": workspace_public_url,
        }
        add_custom_domain_to_context(request, context, component.team)

        return render(request, "core/component_item_public.html.j2", context)


class ComponentItemView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            return ComponentItemPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, component_id: str, item_type: str, item_id: str) -> HttpResponse:
        # Fetch the component for context (needed for title and other template elements)
        # return_instance gives the access-checked model in one query; the
        # template reads attributes/methods off it directly. Error responses
        # are dicts regardless of the flag.
        status_code, component = get_component(request, component_id, return_instance=True)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        vulnerability_summary = None
        assessment_runs = None
        vex_suppressions = None
        vex_suppression_terms: list[str] = []
        vex_suppression_states: list[str] = []

        # VEX, CBOM and HBOM artifacts are SBOM-backed rows served under their own paths.
        is_vex = item_type == "vex"
        is_cbom = item_type == "cbom"
        is_hbom = item_type == "hbom"
        is_sbom_backed = item_type in ("sboms", "vex", "cbom", "hbom")

        if is_sbom_backed:
            result = get_sbom_detail(request, item_id)
            if not result.ok:
                return error_response(
                    request,
                    HttpResponse(status=result.status_code or 400, content=result.error or "Unknown error"),
                )
            item = result.value

            from sbomify.apps.sboms.models import SBOM
            from sbomify.apps.vulnerability_scanning.vex import vex_suppression_rows

            sbom_row = SBOM.objects.filter(pk=item_id).only("id", "bom_type", "sbom_filename").first()
            actual_bom_type = sbom_row.bom_type if sbom_row else None
            # Keep the URL canonical: a VEX opens under /vex/, a CBOM under /cbom/,
            # an HBOM under /hbom/, everything else under /sboms/. Redirect a
            # mismatched path.
            canonical_type = {
                SBOM.BomType.VEX.value: "vex",
                SBOM.BomType.CBOM.value: "cbom",
                SBOM.BomType.HBOM.value: "hbom",
            }.get(actual_bom_type or "", "sboms")
            if item_type != canonical_type:
                return HttpResponseRedirect(
                    reverse("core:component_item", args=[component_id, canonical_type, item_id])
                )

            # For a VEX artifact, list exactly which vulnerabilities it suppresses.
            if actual_bom_type == SBOM.BomType.VEX:
                vex_suppressions = vex_suppression_rows(sbom_row)

                # A VEX statement usually names one id; the component's scanners
                # know the full alias set (OSV publishes the GHSA↔CVE mapping),
                # so enrich each row from the merged scan findings.
                if vex_suppressions:
                    from sbomify.apps.vulnerability_scanning.utils import merge_findings_by_alias

                    # Scope to the artifact's own component — the URL segment is
                    # only canonical after the redirect above.
                    own_component_id = item.get("component_id") or component_id  # type: ignore[union-attr]
                    latest_sbom_id = (
                        SBOM.objects.filter(component_id=own_component_id, bom_type=SBOM.BomType.SBOM)
                        .order_by("-created_at")
                        .values_list("id", flat=True)
                        .first()
                    )
                    alias_map: dict[str, list[str]] = {}
                    if latest_sbom_id:
                        # Two-phase DISTINCT ON: picking the winning run ids first
                        # touches no JSON; only then is `result` fetched for just
                        # those winners. Projecting `result` directly on the
                        # DISTINCT ON query forces Postgres to de-TOAST every
                        # historical rescan's blob before picking a winner — the
                        # same class of bug #1121 fixed for the SBOM list and
                        # trends endpoints, still live here (#1218).
                        winner_ids = list(
                            AssessmentRun.objects.filter(
                                sbom_id=latest_sbom_id, category="security", status="completed"
                            )
                            .order_by("plugin_name", "-created_at")
                            .distinct("plugin_name")
                            .values_list("id", flat=True)
                        )
                        provider_results = list(
                            AssessmentRun.objects.filter(id__in=winner_ids).values_list("result", flat=True)
                        )
                        for finding in merge_findings_by_alias(provider_results)["findings"]:
                            id_set = [i for i in [finding.get("id"), *(finding.get("aliases") or [])] if i]
                            for advisory_id in id_set:
                                alias_map[str(advisory_id).lower()] = [str(i) for i in id_set]
                    for row in vex_suppressions:
                        known = {row["id"], *row["aliases"]}
                        for advisory_id in list(known):
                            known.update(alias_map.get(advisory_id.lower(), []))
                        display_id = next((i for i in sorted(known) if i.upper().startswith("CVE-")), row["id"])
                        row["id"] = display_id
                        row["aliases"] = sorted(i for i in known if i != display_id)

                vex_suppression_terms = [
                    f"{r['id']} {' '.join(r['aliases'])} {r['package']} {r['state']} {r['justification']}".lower()
                    for r in vex_suppressions
                ]
                vex_suppression_states = [r["state"] for r in vex_suppressions]
            # Get latest vulnerability scan for this SBOM from AssessmentRun
            component_id_from_item = item.get("component_id") or component_id  # type: ignore[union-attr]
            latest_scan = (
                AssessmentRun.objects.filter(
                    sbom_id=item_id,
                    sbom__component_id=component_id_from_item,
                    category="security",
                    status="completed",
                )
                .select_related("sbom__component")
                .order_by("-created_at")
                .first()
            )
            if latest_scan:
                # Actionable counts from every provider's latest run, merged by
                # alias and filtered through the component's VEX — the same math
                # as the component page badge, so the numbers agree everywhere.
                from sbomify.apps.vulnerability_scanning.utils import (
                    extract_finding_rows,
                    merge_findings_by_alias,
                )
                from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

                # Two-phase DISTINCT ON — see the VEX alias-enrichment block above
                # for why: picking winner ids first avoids de-TOASTing every
                # historical rescan's `result` blob just to discard the losers.
                winner_ids = list(
                    AssessmentRun.objects.filter(sbom_id=item_id, category="security", status="completed")
                    .order_by("plugin_name", "-created_at")
                    .distinct("plugin_name")
                    .values_list("id", flat=True)
                )
                provider_runs = list(
                    AssessmentRun.objects.filter(id__in=winner_ids).values_list("plugin_name", "result")
                )
                merged = merge_findings_by_alias([result for _, result in provider_runs])
                rows = extract_finding_rows(merged, load_vex_suppressions(component_id_from_item))
                if rows:
                    counts = {
                        "total": len(rows),
                        "critical": sum(1 for row in rows if row["severity"] == "critical"),
                        "high": sum(1 for row in rows if row["severity"] == "high"),
                        "medium": sum(1 for row in rows if row["severity"] == "medium"),
                        "low": sum(1 for row in rows if row["severity"] == "low"),
                    }
                else:
                    # Summary-only results (no findings list) still carry counts.
                    from sbomify.apps.vulnerability_scanning.utils import extract_severity_counts

                    counts = max(
                        (extract_severity_counts(result) for _, result in provider_runs),
                        key=lambda c: c["total"],
                        default={"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
                    )
                vulnerability_summary = {
                    **counts,
                    "provider": ", ".join(sorted({name for name, _ in provider_runs})),
                    "scan_date": latest_scan.created_at,
                }

            # Get assessment runs for this SBOM
            try:
                from sbomify.apps.plugins.apis import get_sbom_assessments

                # Create a mock request object with the sbom_id parameter
                assessment_response = get_sbom_assessments(request, item_id)
                # Use mode='json' to ensure datetime objects are serialized as ISO strings
                assessment_runs = assessment_response.model_dump(mode="json")
            except Exception:
                # Degrade to no assessments section rather than failing the page,
                # but leave a trace — a silent None here hides real data problems.
                logger.exception("Failed to fetch assessments for SBOM %s; rendering without them", item_id)
                assessment_runs = None

        elif item_type == "documents":
            result = get_document_detail(request, item_id)
            if not result.ok:
                return error_response(
                    request,
                    HttpResponse(status=result.status_code or 400, content=result.error or "Unknown error"),
                )
            item = result.value

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        from sbomify.apps.core.authz import can

        can_triage = can(request, "artifact:publish_vex", component)
        # Same tier the rerun endpoint enforces, so the button is only offered
        # to a caller the API would actually accept.
        can_rerun = can(request, "component:manage", component)

        # Page-header context: the icon is conditional and the copy chip and
        # breadcrumb trail are lists, so the view builds them per the design
        # system contract.
        if is_vex:
            item_kind = "VEX"
        elif is_cbom:
            item_kind = "CBOM"
        elif is_sbom_backed:
            item_kind = "SBOM"
        else:
            item_kind = "Document"
        header_icon = "fas fa-file-code" if is_sbom_backed else "fas fa-file-alt"
        header_copy_values = [{"value": item_id, "title": f"ID: {item_id} (click to copy)"}]
        breadcrumb_items = [
            {"label": component.name, "url": reverse("core:component_details", args=[component_id])},
            {"label": f"{item_kind} Details"},
        ]

        return render(
            request,
            "core/component_item.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "item": item,
                "item_type": item_type,
                "header_icon": header_icon,
                "header_copy_values": header_copy_values,
                "breadcrumb_items": breadcrumb_items,
                "component": component,
                "component_id": component_id,
                "vulnerability_summary": vulnerability_summary,
                "assessment_runs": assessment_runs,
                "vex_suppressions": vex_suppressions,
                "vex_suppression_terms": vex_suppression_terms,
                "vex_suppression_states": vex_suppression_states,
                "is_vex": is_vex,
                "is_cbom": is_cbom,
                "is_hbom": is_hbom,
                "is_sbom_backed": is_sbom_backed,
                "can_triage": can_triage,
                "can_rerun": can_rerun,
                "team_key": component.team.key,
            },
        )
