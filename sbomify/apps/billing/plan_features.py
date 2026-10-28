"""Plan benefits shared by comparison cards and workspace billing settings.

Quotas come from BillingPlan, so this copy must not promise fixed limits.
"""

# "Everything in X" is a pointer to the plan below, not a benefit of its own. It
# is what makes each tuple below a delta rather than a whole plan, so working out
# what a move costs means following the pointer rather than dropping it.
_INHERITED_PREFIX = "Everything in "

# Cheapest first. A tier carries every feature below it.
PLAN_ORDER: tuple[str, ...] = ("community", "business", "enterprise")

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


def effective_features(key: str) -> tuple[str, ...]:
    """Everything a plan actually carries, with the inherited tiers folded in.

    The tuples above are deltas: Business names what Community does not have and
    points at it with "Everything in Community". Comparing two deltas directly
    answers the wrong question, because an Enterprise workspace dropping to
    Community loses every Business feature as well as the Enterprise ones.
    """
    own = tuple(f for f in PLAN_FEATURES.get(key, ()) if not f.startswith(_INHERITED_PREFIX))
    if key not in PLAN_ORDER:
        return own

    features: list[str] = []
    for tier in PLAN_ORDER[: PLAN_ORDER.index(key) + 1]:
        for feature in PLAN_FEATURES.get(tier, ()):
            if not feature.startswith(_INHERITED_PREFIX) and feature not in features:
                features.append(feature)
    return tuple(features)


def features_lost_moving_to(current_key: str, target_key: str) -> list[str]:
    """What the workspace gives up by moving from one plan to another.

    The cards say what a plan includes. On the one page where someone decides to
    stop paying, the thing they need is the other list, and nobody can read it
    off two columns reliably.
    """
    target = set(effective_features(target_key))
    return [feature for feature in effective_features(current_key) if feature not in target]
