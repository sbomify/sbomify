from __future__ import annotations

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

# The gallery's index and its section order come from here, so a component can
# never be demoed without appearing in the index (or listed without a demo).
GALLERY_SECTIONS: list[dict[str, str]] = [
    {"id": "colors", "label": "Colour tokens", "group": "Foundations"},
    {"id": "typography", "label": "Typography", "group": "Foundations"},
    {"id": "icon-chips", "label": "Icon chips", "group": "Foundations"},
    {"id": "metric-chips", "label": "Metric chips", "group": "Foundations"},
    {"id": "page-header", "label": "Page & section headers", "group": "Foundations"},
    {"id": "buttons", "label": "Buttons", "group": "Controls"},
    {"id": "forms", "label": "Form controls", "group": "Controls"},
    {"id": "search", "label": "Search input", "group": "Controls"},
    {"id": "file-upload", "label": "File upload", "group": "Controls"},
    {"id": "date-picker", "label": "Date picker", "group": "Controls"},
    {"id": "cards", "label": "Cards", "group": "Containers"},
    {"id": "collapsible", "label": "Collapsible card", "group": "Containers"},
    {"id": "modals", "label": "Modals", "group": "Containers"},
    {"id": "select-rows", "label": "Selectable rows", "group": "Containers"},
    {"id": "empty-states", "label": "Empty states", "group": "Containers"},
    {"id": "tables", "label": "Tables", "group": "Data"},
    {"id": "pagination", "label": "Pagination", "group": "Data"},
    {"id": "stats", "label": "Stat cards", "group": "Data"},
    {"id": "severity", "label": "Severity badges", "group": "Data"},
    {"id": "progress", "label": "Progress", "group": "Data"},
    {"id": "badges", "label": "Badges", "group": "Data"},
    {"id": "tags", "label": "Tags", "group": "Data"},
    {"id": "alerts", "label": "Alerts", "group": "Feedback"},
    {"id": "toasts", "label": "Toasts", "group": "Feedback"},
    {"id": "loading", "label": "Loading states", "group": "Feedback"},
    {"id": "tabs", "label": "Tabs", "group": "Navigation"},
    {"id": "breadcrumbs", "label": "Breadcrumbs", "group": "Navigation"},
    {"id": "dropdowns", "label": "Dropdowns", "group": "Navigation"},
    {"id": "stepper", "label": "Stepper", "group": "Navigation"},
    {"id": "avatars", "label": "Avatars", "group": "Misc"},
    {"id": "copy", "label": "Code & tokens", "group": "Misc"},
    {"id": "tooltip", "label": "Tooltip", "group": "Misc"},
]


class DesignSystemView(LoginRequiredMixin, View):
    """Local-development-only gallery showing every design-system component in a single view.

    The URL is only registered when DEBUG is on; this guard is defense in depth so the
    page can never render in production even if the route were exposed by mistake.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        if not settings.DEBUG:
            raise Http404
        context = {
            "team": request.session.get("current_team", {}),
            "sections": GALLERY_SECTIONS,
            "demo_tokens": [
                "primary",
                "primary-dark",
                "primary-light",
                "accent",
                "accent-pink",
                "accent-orange",
                "success",
                "warning",
                "danger",
                "background",
                "surface",
                "surface-elevated",
                "border",
                "text",
                "text-muted",
            ],
            # Alpine handlers come from here, not inline in the template: an `attrs`
            # string containing double quotes cannot survive a template tag argument
            # (the HTML parser splits it into junk attributes).
            "demo_toasts": [
                {
                    "label": "Success toast",
                    "variant": "success",
                    "attrs": "@click=\"$dispatch('toast', "
                    "{ type: 'success', title: 'Saved', message: 'Component updated.' })\"",
                },
                {
                    "label": "Error toast",
                    "variant": "danger",
                    "attrs": "@click=\"$dispatch('toast', "
                    "{ type: 'danger', title: 'Failed', message: 'Could not parse the SBOM.' })\"",
                },
            ],
            "demo_select_rows": [
                {
                    "name": "BSI TR-03183-2 v2.1",
                    "version": "v1.0.0",
                    "beta": True,
                    "checked": True,
                    "disabled": False,
                    "description": "Validates SBOMs against BSI Technical Guideline TR-03183-2 v2.1.0.",
                },
                {
                    "name": "CNSA 2.0 Compliance",
                    "version": "v1.0.0",
                    "beta": True,
                    "checked": False,
                    "disabled": False,
                    "description": "Grades cryptographic assets against the NSA CNSA 2.0 suite.",
                },
                {
                    "name": "Dependency Track",
                    "version": "v2.1.0",
                    "beta": False,
                    "checked": False,
                    "disabled": True,
                    "description": "Requires a Business plan — the row is not clickable.",
                },
            ],
            "demo_severities": [
                {"level": "critical", "label": "Critical"},
                {"level": "high", "label": "High"},
                {"level": "medium", "label": "Medium"},
                {"level": "low", "label": "Low"},
            ],
            "demo_collapsible": [
                {"id": "links", "label": "Product links"},
                {"id": "identifiers", "label": "Product identifiers"},
                {"id": "lifecycle", "label": "Lifecycle"},
            ],
            "demo_select_options": [
                {"value": "sbom", "label": "SBOM"},
                {"value": "document", "label": "Document"},
                {"value": "release", "label": "Release"},
            ],
            "demo_breadcrumbs": [
                {"label": "Products", "url": "#"},
                {"label": "Acme Widget", "url": "#"},
                {"label": "Releases"},
            ],
            "demo_tabs": [
                {"id": "overview", "label": "Overview", "icon": "fas fa-chart-line"},
                {"id": "sboms", "label": "SBOMs", "icon": "fas fa-file-code"},
                {"id": "documents", "label": "Documents", "icon": "fas fa-file-alt"},
            ],
            "demo_page_range": [1, 2, 3, "…", 8],
            "demo_dropdown_items": [
                {"label": "Edit", "icon": "fas fa-pen"},
                {"label": "Duplicate", "icon": "fas fa-copy"},
                {"divider": True},
                {"label": "Delete", "icon": "fas fa-trash", "danger": True},
            ],
            "demo_code": (
                'curl -X POST "$SBOMIFY_URL/api/v1/sboms" \\\n'
                '  -H "Authorization: Bearer $TOKEN" \\\n'
                '  -F "file=@bom.cdx.json"'
            ),
        }
        return render(request, "core/design_system.html.j2", context)
