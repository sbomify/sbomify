"""Utility functions for computing public assessment status.

This module provides functions to aggregate assessment results for public display,
showing only passing assessments at component, project, and product levels.

Key principle: Only show assessments that PASS. Never show failures on public pages.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import OuterRef, Subquery

from .models import AssessmentRun, RegisteredPlugin
from .sdk.enums import AssessmentCategory, RunStatus

if TYPE_CHECKING:
    from sbomify.apps.core.models import Component, Product, Project


@dataclass
class PassingAssessment:
    """Represents a passing assessment for display."""

    plugin_name: str
    plugin_display_name: str
    category: str


@dataclass
class ComponentAssessmentStatus:
    """Assessment status for a component."""

    component_id: str
    component_name: str
    all_pass: bool
    has_assessments: bool
    passing_assessments: list[PassingAssessment]


@dataclass
class ProjectAssessmentStatus:
    """Aggregated assessment status for a project."""

    project_id: str
    project_name: str
    all_pass: bool  # True if all components pass all assessments
    has_assessments: bool
    passing_assessments: list[PassingAssessment]  # Assessments that pass for ALL components
    component_statuses: list[ComponentAssessmentStatus]


@dataclass
class ProductAssessmentStatus:
    """Aggregated assessment status for a product."""

    product_id: str
    product_name: str
    all_pass: bool  # True if all projects (and their components) pass all assessments
    has_assessments: bool
    passing_assessments: list[PassingAssessment]  # Assessments that pass for ALL projects/components
    project_statuses: list[ProjectAssessmentStatus]


def _get_plugin_display_names() -> dict[str, tuple[str, str]]:
    """Get a mapping of plugin names to (display_name, category)."""
    plugins = RegisteredPlugin.objects.filter(is_enabled=True)
    return {p.name: (p.display_name, p.category) for p in plugins}


def _get_latest_assessment_runs_for_sbom(sbom_id: str) -> list[AssessmentRun]:
    """Get the latest assessment run for each plugin for an SBOM."""
    # Get the latest run per plugin
    latest_run_ids = (
        AssessmentRun.objects.filter(sbom_id=sbom_id)
        .values("plugin_name")
        .annotate(
            latest_id=Subquery(
                AssessmentRun.objects.filter(sbom_id=sbom_id, plugin_name=OuterRef("plugin_name"))
                .order_by("-created_at")
                .values("id")[:1]
            )
        )
        .values_list("latest_id", flat=True)
    )
    return list(AssessmentRun.objects.filter(id__in=latest_run_ids))


def _is_run_passing(run: AssessmentRun) -> bool:
    """Check if an assessment run is passing (completed with no failures)."""
    if run.status != RunStatus.COMPLETED.value:
        return False

    result = run.result or {}
    summary = result.get("summary", {})
    return summary.get("fail_count", 0) == 0 and summary.get("error_count", 0) == 0


def get_sbom_passing_assessments(sbom_id: str) -> list[PassingAssessment]:
    """Get list of passing assessments for an SBOM.

    Only returns assessments that have completed successfully with no failures.
    """
    plugin_info = _get_plugin_display_names()
    latest_runs = _get_latest_assessment_runs_for_sbom(sbom_id)

    passing = []
    for run in latest_runs:
        if _is_run_passing(run):
            display_name, category = plugin_info.get(run.plugin_name, (run.plugin_name, run.category))
            passing.append(
                PassingAssessment(
                    plugin_name=run.plugin_name,
                    plugin_display_name=display_name,
                    category=category,
                )
            )

    return passing


def get_component_assessment_status(component: "Component") -> ComponentAssessmentStatus:
    """Get aggregated assessment status for a component.

    A component passes an assessment if ALL its SBOMs pass that assessment.
    Only returns assessments where all SBOMs pass.
    """
    from sbomify.apps.sboms.models import SBOM

    sboms = SBOM.objects.filter(component=component)
    sbom_ids = list(sboms.values_list("id", flat=True))

    if not sbom_ids:
        return ComponentAssessmentStatus(
            component_id=str(component.id),
            component_name=component.name,
            all_pass=False,
            has_assessments=False,
            passing_assessments=[],
        )

    # Get passing assessments per SBOM
    sbom_passing: dict[str, set[str]] = {}  # sbom_id -> set of passing plugin names
    for sbom_id in sbom_ids:
        passing = get_sbom_passing_assessments(str(sbom_id))
        sbom_passing[str(sbom_id)] = {p.plugin_name for p in passing}

    # Find assessments that pass for ALL SBOMs
    if not sbom_passing:
        common_passing: set[str] = set()
    else:
        common_passing = set.intersection(*sbom_passing.values()) if sbom_passing else set()

    # Check if there are any assessments at all
    has_assessments = any(sbom_passing.values())

    # Get display info for common passing assessments
    plugin_info = _get_plugin_display_names()
    passing_assessments = []
    for plugin_name in sorted(common_passing):
        display_name, category = plugin_info.get(plugin_name, (plugin_name, AssessmentCategory.COMPLIANCE.value))
        passing_assessments.append(
            PassingAssessment(
                plugin_name=plugin_name,
                plugin_display_name=display_name,
                category=category,
            )
        )

    # all_pass is True if we have assessments and ALL of them pass
    # This means every SBOM passes every assessment that was run on it
    all_sboms_have_same_passing = len(common_passing) > 0 if has_assessments else False

    return ComponentAssessmentStatus(
        component_id=str(component.id),
        component_name=component.name,
        all_pass=all_sboms_have_same_passing,
        has_assessments=has_assessments,
        passing_assessments=passing_assessments,
    )


def get_project_assessment_status(project: "Project") -> ProjectAssessmentStatus:
    """Get aggregated assessment status for a project.

    A project passes an assessment if ALL its components pass that assessment.
    Only public components are considered for public display.
    """
    from sbomify.apps.core.models import Component

    # Get public components in this project
    components = Component.objects.filter(
        projects=project,
        is_public=True,
    ).distinct()

    if not components.exists():
        return ProjectAssessmentStatus(
            project_id=str(project.id),
            project_name=project.name,
            all_pass=False,
            has_assessments=False,
            passing_assessments=[],
            component_statuses=[],
        )

    # Get status for each component
    component_statuses = []
    component_passing: list[set[str]] = []

    for component in components:
        status = get_component_assessment_status(component)
        component_statuses.append(status)
        if status.has_assessments:
            component_passing.append({p.plugin_name for p in status.passing_assessments})

    # Find assessments that pass for ALL components
    if not component_passing:
        common_passing: set[str] = set()
    else:
        common_passing = set.intersection(*component_passing) if component_passing else set()

    has_assessments = any(cs.has_assessments for cs in component_statuses)

    # Get display info for common passing assessments
    plugin_info = _get_plugin_display_names()
    passing_assessments = []
    for plugin_name in sorted(common_passing):
        display_name, category = plugin_info.get(plugin_name, (plugin_name, AssessmentCategory.COMPLIANCE.value))
        passing_assessments.append(
            PassingAssessment(
                plugin_name=plugin_name,
                plugin_display_name=display_name,
                category=category,
            )
        )

    all_pass = len(common_passing) > 0 if has_assessments else False

    return ProjectAssessmentStatus(
        project_id=str(project.id),
        project_name=project.name,
        all_pass=all_pass,
        has_assessments=has_assessments,
        passing_assessments=passing_assessments,
        component_statuses=component_statuses,
    )


def get_product_assessment_status(product: "Product") -> ProductAssessmentStatus:
    """Get aggregated assessment status for a product.

    A product passes an assessment if ALL its public projects (and their components) pass.
    """
    from sbomify.apps.core.models import Project

    # Get public projects in this product
    projects = Project.objects.filter(
        products=product,
        is_public=True,
    ).distinct()

    if not projects.exists():
        return ProductAssessmentStatus(
            product_id=str(product.id),
            product_name=product.name,
            all_pass=False,
            has_assessments=False,
            passing_assessments=[],
            project_statuses=[],
        )

    # Get status for each project
    project_statuses = []
    project_passing: list[set[str]] = []

    for project in projects:
        status = get_project_assessment_status(project)
        project_statuses.append(status)
        if status.has_assessments:
            project_passing.append({p.plugin_name for p in status.passing_assessments})

    # Find assessments that pass for ALL projects
    if not project_passing:
        common_passing: set[str] = set()
    else:
        common_passing = set.intersection(*project_passing) if project_passing else set()

    has_assessments = any(ps.has_assessments for ps in project_statuses)

    # Get display info for common passing assessments
    plugin_info = _get_plugin_display_names()
    passing_assessments = []
    for plugin_name in sorted(common_passing):
        display_name, category = plugin_info.get(plugin_name, (plugin_name, AssessmentCategory.COMPLIANCE.value))
        passing_assessments.append(
            PassingAssessment(
                plugin_name=plugin_name,
                plugin_display_name=display_name,
                category=category,
            )
        )

    all_pass = len(common_passing) > 0 if has_assessments else False

    return ProductAssessmentStatus(
        product_id=str(product.id),
        product_name=product.name,
        all_pass=all_pass,
        has_assessments=has_assessments,
        passing_assessments=passing_assessments,
        project_statuses=project_statuses,
    )


def get_latest_sbom_for_component(component: "Component"):
    """Get the most recent SBOM for a component.

    Returns None if the component has no SBOMs.
    """
    from sbomify.apps.sboms.models import SBOM

    return SBOM.objects.filter(component=component).order_by("-created_at").first()


def get_component_latest_sbom_assessment_status(component: "Component") -> ComponentAssessmentStatus:
    """Get assessment status based on ONLY the latest SBOM for a component.

    Unlike get_component_assessment_status which checks ALL SBOMs,
    this only looks at the most recent SBOM.
    """
    latest_sbom = get_latest_sbom_for_component(component)

    if not latest_sbom:
        return ComponentAssessmentStatus(
            component_id=str(component.id),
            component_name=component.name,
            all_pass=False,
            has_assessments=False,
            passing_assessments=[],
        )

    # Check if any assessments were run (even failing ones)
    latest_runs = _get_latest_assessment_runs_for_sbom(str(latest_sbom.id))
    has_assessments = len(latest_runs) > 0

    # Get only passing assessments for display
    passing = get_sbom_passing_assessments(str(latest_sbom.id))
    all_pass = len(passing) > 0 and len(passing) == len(latest_runs)

    return ComponentAssessmentStatus(
        component_id=str(component.id),
        component_name=component.name,
        all_pass=all_pass,
        has_assessments=has_assessments,
        passing_assessments=passing,
    )


def get_product_latest_sbom_assessment_status(product: "Product") -> ProductAssessmentStatus:
    """Get assessment status based on ONLY the latest SBOM per component in a product.

    A product passes an assessment if the latest SBOM of every public component
    in the product passes that assessment.

    This differs from get_product_assessment_status which checks ALL SBOMs.
    """
    from sbomify.apps.core.models import Component

    # Get all public components in this product (via projects)
    components = (
        Component.objects.filter(
            projects__products=product,
            projects__is_public=True,
            is_public=True,
        )
        .distinct()
        .order_by("name")
    )

    if not components.exists():
        return ProductAssessmentStatus(
            product_id=str(product.id),
            product_name=product.name,
            all_pass=False,
            has_assessments=False,
            passing_assessments=[],
            project_statuses=[],  # Not populated for latest-SBOM mode
        )

    # Get latest SBOM assessment status for each component
    component_passing: list[set[str]] = []
    has_any_assessments = False

    for component in components:
        status = get_component_latest_sbom_assessment_status(component)
        if status.has_assessments:
            has_any_assessments = True
            # Always add the set of passing plugin names (even if empty)
            # This ensures intersection works correctly: if one component fails,
            # its empty set will result in empty intersection
            component_passing.append({p.plugin_name for p in status.passing_assessments})

    # Find assessments that pass for ALL components' latest SBOMs
    if not component_passing:
        common_passing: set[str] = set()
    else:
        common_passing = set.intersection(*component_passing)

    # Get display info for common passing assessments
    plugin_info = _get_plugin_display_names()
    passing_assessments = []
    for plugin_name in sorted(common_passing):
        display_name, category = plugin_info.get(plugin_name, (plugin_name, AssessmentCategory.COMPLIANCE.value))
        passing_assessments.append(
            PassingAssessment(
                plugin_name=plugin_name,
                plugin_display_name=display_name,
                category=category,
            )
        )

    all_pass = len(common_passing) > 0 if has_any_assessments else False

    # project_statuses left empty intentionally - this function focuses on
    # component-level aggregation via latest SBOMs, not project hierarchy
    return ProductAssessmentStatus(
        product_id=str(product.id),
        product_name=product.name,
        all_pass=all_pass,
        has_assessments=has_any_assessments,
        passing_assessments=passing_assessments,
        project_statuses=[],
    )


def get_products_latest_sbom_assessments_batch(
    products: list["Product"],
) -> dict[str, list[PassingAssessment]]:
    """Get latest SBOM assessments for multiple products in a single batch.

    This is an optimized version of get_product_latest_sbom_assessment_status
    for use when processing multiple products (e.g., workspace listing).

    Returns a dict mapping product_id -> list of PassingAssessment.
    """
    from sbomify.apps.core.models import Component
    from sbomify.apps.sboms.models import SBOM

    if not products:
        return {}

    product_ids = [p.id for p in products]

    # Step 1: Get all public components for all products (single query)
    components = (
        Component.objects.filter(
            projects__products__id__in=product_ids,
            projects__is_public=True,
            is_public=True,
        )
        .distinct()
        .select_related("team")
    )

    # Build mapping: component_id -> list of product_ids it belongs to
    component_to_products: dict[str, set[str]] = {}
    for component in components:
        component_products = component.projects.filter(is_public=True, products__id__in=product_ids).values_list(
            "products__id", flat=True
        )
        component_to_products[str(component.id)] = set(str(pid) for pid in component_products if pid)

    if not component_to_products:
        return {str(p.id): [] for p in products}

    # Step 2: Get latest SBOM for each component (single query with window function simulation)
    component_ids = list(component_to_products.keys())
    latest_sboms = (
        SBOM.objects.filter(component_id__in=component_ids)
        .order_by("component_id", "-created_at")
        .distinct("component_id")
    )

    # Fallback for databases that don't support DISTINCT ON (e.g., SQLite in tests)
    try:
        latest_sbom_list = list(latest_sboms)
    except Exception:
        # Manual deduplication for SQLite
        seen_components: set[str] = set()
        latest_sbom_list = []
        for sbom in SBOM.objects.filter(component_id__in=component_ids).order_by("component_id", "-created_at"):
            if str(sbom.component_id) not in seen_components:
                seen_components.add(str(sbom.component_id))
                latest_sbom_list.append(sbom)

    sbom_to_component = {str(sbom.id): str(sbom.component_id) for sbom in latest_sbom_list}
    sbom_ids = list(sbom_to_component.keys())

    if not sbom_ids:
        return {str(p.id): [] for p in products}

    # Step 3: Get all assessment runs for these SBOMs (batch query)
    from django.db.models import OuterRef, Subquery

    latest_run_ids = (
        AssessmentRun.objects.filter(sbom_id__in=sbom_ids)
        .values("sbom_id", "plugin_name")
        .annotate(
            latest_id=Subquery(
                AssessmentRun.objects.filter(sbom_id=OuterRef("sbom_id"), plugin_name=OuterRef("plugin_name"))
                .order_by("-created_at")
                .values("id")[:1]
            )
        )
        .values_list("latest_id", flat=True)
    )

    all_runs = list(AssessmentRun.objects.filter(id__in=latest_run_ids).select_related())

    # Step 4: Compute passing assessments per SBOM
    plugin_info = _get_plugin_display_names()
    sbom_passing: dict[str, list[PassingAssessment]] = {sbom_id: [] for sbom_id in sbom_ids}
    sbom_has_assessments: dict[str, bool] = {sbom_id: False for sbom_id in sbom_ids}

    for run in all_runs:
        sbom_id = str(run.sbom_id)
        sbom_has_assessments[sbom_id] = True
        if _is_run_passing(run):
            display_name, category = plugin_info.get(
                run.plugin_name, (run.plugin_name, AssessmentCategory.COMPLIANCE.value)
            )
            sbom_passing[sbom_id].append(
                PassingAssessment(
                    plugin_name=run.plugin_name,
                    plugin_display_name=display_name,
                    category=category,
                )
            )

    # Step 5: Aggregate per product
    result: dict[str, list[PassingAssessment]] = {}

    for product in products:
        product_id = str(product.id)
        # Find all components belonging to this product
        product_component_ids = [cid for cid, pids in component_to_products.items() if product_id in pids]

        if not product_component_ids:
            result[product_id] = []
            continue

        # Get passing plugin names for each component's latest SBOM
        component_passing_sets: list[set[str]] = []

        for component_id in product_component_ids:
            # Find the latest SBOM for this component
            sbom_id = None
            for sid, cid in sbom_to_component.items():
                if cid == component_id:
                    sbom_id = sid
                    break

            if sbom_id and sbom_has_assessments.get(sbom_id, False):
                passing_plugins = {a.plugin_name for a in sbom_passing.get(sbom_id, [])}
                component_passing_sets.append(passing_plugins)

        if not component_passing_sets:
            result[product_id] = []
            continue

        # Intersection of all components' passing assessments
        common_passing = set.intersection(*component_passing_sets) if component_passing_sets else set()

        # Build result list
        passing_assessments = []
        for plugin_name in sorted(common_passing):
            display_name, category = plugin_info.get(plugin_name, (plugin_name, AssessmentCategory.COMPLIANCE.value))
            passing_assessments.append(
                PassingAssessment(
                    plugin_name=plugin_name,
                    plugin_display_name=display_name,
                    category=category,
                )
            )

        result[product_id] = passing_assessments

    return result


def passing_assessments_to_dict(assessments: list[PassingAssessment]) -> list[dict]:
    """Convert list of PassingAssessment to dictionaries for template context."""
    return [
        {
            "plugin_name": a.plugin_name,
            "display_name": a.plugin_display_name,
            "category": a.category,
        }
        for a in assessments
    ]
