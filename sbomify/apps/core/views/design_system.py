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
    {"id": "assessment-pills", "label": "Assessment pills", "group": "Foundations"},
    {"id": "page-header", "label": "Page & section headers", "group": "Foundations"},
    {"id": "buttons", "label": "Buttons", "group": "Controls"},
    {"id": "forms", "label": "Form controls", "group": "Controls"},
    {"id": "choice-group", "label": "Choice group", "group": "Controls"},
    {"id": "search", "label": "Search input", "group": "Controls"},
    {"id": "file-upload", "label": "File upload", "group": "Controls"},
    {"id": "date-picker", "label": "Date picker", "group": "Controls"},
    {"id": "cards", "label": "Cards", "group": "Containers"},
    {"id": "collapsible", "label": "Collapsible card", "group": "Containers"},
    {"id": "accordion", "label": "Accordion", "group": "Containers"},
    {"id": "modals", "label": "Modals", "group": "Containers"},
    {"id": "action-tiles", "label": "Action tiles", "group": "Containers"},
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
    {"id": "callouts", "label": "Callouts", "group": "Feedback"},
    {"id": "toasts", "label": "Toasts", "group": "Feedback"},
    {"id": "loading", "label": "Loading states", "group": "Feedback"},
    {"id": "tabs", "label": "Tabs", "group": "Navigation"},
    {"id": "breadcrumbs", "label": "Breadcrumbs", "group": "Navigation"},
    {"id": "dropdowns", "label": "Dropdowns", "group": "Navigation"},
    {"id": "actions-menu", "label": "Actions menu", "group": "Navigation"},
    {"id": "stepper", "label": "Stepper", "group": "Navigation"},
    {"id": "avatars", "label": "Avatars", "group": "Misc"},
    {"id": "copy", "label": "Code & tokens", "group": "Misc"},
    {"id": "tooltip", "label": "Tooltip", "group": "Misc"},
    {"id": "branded", "label": "Branded components", "group": "Branded"},
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
            # One row per brand, chosen to show the ink switching rather than to
            # look pretty: navy and violet take white text, amber and mint take
            # dark, and the last row has no brand at all.
            "branded_demos": [
                {"label": "Dark brand", "brand": "#25293F"},
                {"label": "Vivid brand", "brand": "#7C3AED"},
                {"label": "Pale brand", "brand": "#FDE68A"},
                {"label": "Mint brand", "brand": "#6EE7B7"},
                {"label": "No brand set", "brand": ""},
            ],
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
            # The toast demo's Alpine handlers now live in the template: a cotton
            # component takes @click directly, so the attrs string this context used
            # to carry (a template tag argument could not hold its double quotes) is
            # gone.
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
                {"level": "unknown", "label": "Unknown"},
            ],
            "demo_copy_values": [
                {"value": "DLyQjCBkNJkB", "title": "Product ID (click to copy)"},
                {"value": "urn:tei:uuid:sbomify.com", "title": "TEI (click to copy)"},
            ],
            "demo_collapsible": [
                {"id": "links", "label": "Product links"},
                {"id": "identifiers", "label": "Product identifiers"},
                {"id": "lifecycle", "label": "Lifecycle"},
            ],
            "demo_accordion": [
                {
                    "id": "org",
                    "label": "Organisational controls",
                    "body": "Policies, roles and supplier relationships.",
                },
                {
                    "id": "tech",
                    "label": "Technological controls",
                    "body": "Access control, cryptography and secure development.",
                },
                {
                    "id": "phys",
                    "label": "Physical controls",
                    "body": "Facilities, equipment and media handling.",
                },
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
            "demo_marked_breadcrumbs": [
                {"label": "Acme Trust Center", "url": "#", "icon": "fas fa-shield-alt"},
                {"label": "Acme Widget", "url": "#", "icon": "fas fa-box"},
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
            "demo_severity_choices": [
                {
                    "value": "critical",
                    "label": "Critical",
                    "icon": "fas fa-triangle-exclamation",
                    "variant": "severity-critical",
                },
                {"value": "high", "label": "High", "icon": "fas fa-angles-up", "variant": "severity-high"},
                {"value": "medium", "label": "Medium", "icon": "fas fa-angle-up", "variant": "severity-medium"},
                {"value": "low", "label": "Low", "icon": "fas fa-angle-down", "variant": "severity-low"},
            ],
            "demo_status_choices": [
                {
                    "value": "identified",
                    "label": "Identified",
                    "icon": "fas fa-circle-exclamation",
                    "variant": "warning",
                },
                {
                    "value": "investigating",
                    "label": "Investigating",
                    "icon": "fas fa-magnifying-glass",
                    "variant": "info",
                },
                {"value": "fix_in_progress", "label": "Fix in progress", "icon": "fas fa-wrench", "variant": "violet"},
                {"value": "resolved", "label": "Resolved", "icon": "fas fa-circle-check", "variant": "success"},
                {"value": "wont_fix", "label": "Won't fix", "icon": "fas fa-ban", "variant": "secondary"},
            ],
            # Enough rows that the last one's menu has to flip above its trigger.
            "demo_menu_rows": ["Gateway", "Vault", "Edge Agent"],
            "demo_code": (
                'curl -X POST "$SBOMIFY_URL/api/v1/sboms" \\\n'
                '  -H "Authorization: Bearer $TOKEN" \\\n'
                '  -F "file=@bom.cdx.json"'
            ),
        }
        return render(request, "core/design_system.html.j2", context)
