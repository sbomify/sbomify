"""Plan benefits shared by comparison cards and workspace billing settings.

Quotas come from BillingPlan, so this copy must not promise fixed limits.
"""

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
        "Product identifiers",
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
