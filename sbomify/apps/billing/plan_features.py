"""Plan benefits shared by comparison cards and workspace billing settings.

Quotas come from BillingPlan, so this copy must not promise fixed limits.
"""

# "Everything in X" is a pointer to the plan below, not a benefit of its own, so
# it is excluded when working out what a downgrade costs.
_INHERITED_PREFIX = "Everything in "

PLAN_FEATURES: dict[str, tuple[str, ...]] = {
    "community": (
        "Unlimited SBOMs",
        "Public products and components",
        "Weekly vulnerability scans",
        "Community support",
        "API access",
        "Public Trust Center",
        "Custom branding",
    ),
    "business": (
        "Everything in Community",
        "Private products and components",
        "NTIA Minimum Elements check",
        "Vulnerability scans every 12 hours",
        "Product identifiers (SKUs and barcodes)",
        "Priority support",
        "Custom Trust Center domain",
    ),
    "enterprise": (
        "Everything in Business",
        "Custom Dependency Track servers",
        "Dedicated support",
        "Custom integrations",
        "SLA guarantee",
        "Advanced security",
        "Custom deployment options",
    ),
}


def features_lost_moving_to(current_key: str, target_key: str) -> list[str]:
    """What the workspace gives up by moving from one plan to another.

    The cards say what a plan includes. On the one page where someone decides to
    stop paying, the thing they need is the other list, and nobody can read it
    off two columns reliably.
    """
    current = [f for f in PLAN_FEATURES.get(current_key, ()) if not f.startswith(_INHERITED_PREFIX)]
    target = set(PLAN_FEATURES.get(target_key, ()))
    return [feature for feature in current if feature not in target]
