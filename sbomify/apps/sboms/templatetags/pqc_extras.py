"""Template filters mapping PQC classification values to display labels + badge variants."""

from django import template

register = template.Library()

# Per-asset PQC status -> (human label, tw-badge variant)
_STATUS_DISPLAY = {
    "quantum_safe": ("Quantum-safe", "success"),
    "quantum_vulnerable": ("Vulnerable", "danger"),
    "review": ("Review", "warning"),
    "unknown": ("Unknown", "secondary"),
}

# Inventory-level readiness -> (human label, tw-badge variant)
_OVERALL_DISPLAY = {
    "at_risk": ("At risk", "danger"),
    "needs_review": ("Needs review", "warning"),
    "ready": ("Quantum-ready", "success"),
    "not_assessed": ("Not assessed", "secondary"),
    "no_crypto": ("No crypto", "secondary"),
}


@register.filter
def pqc_label(status: str | None) -> str:
    return _STATUS_DISPLAY.get(status or "", ("Unknown", "secondary"))[0]


@register.filter
def pqc_variant(status: str | None) -> str:
    return _STATUS_DISPLAY.get(status or "", ("Unknown", "secondary"))[1]


@register.filter
def pqc_overall_label(overall: str | None) -> str:
    return _OVERALL_DISPLAY.get(overall or "", ("Not assessed", "secondary"))[0]


@register.filter
def pqc_overall_variant(overall: str | None) -> str:
    return _OVERALL_DISPLAY.get(overall or "", ("Not assessed", "secondary"))[1]
