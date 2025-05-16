from collections import Counter
from typing import Literal

from teams.models import Team

from .models import SBOM, Component, Product, Project
from .schemas import ComponentUploadInfo, StatsResponse


def get_stats_for_team(
    team: Team | None = None,
    item_type: Literal["product", "project", "component"] | None = None,
    item_id: str | None = None,
) -> StatsResponse:
    """Get statistics for a team's products, projects, components and licenses.

    Args:
        team (Team): The team to get statistics for, or None if item_type and item_id are provided.
        item_type (Literal["ALL", "product", "project", "component"]): Filter results by item type.
            "ALL" returns stats for all item types.
        item_id (str, optional): ID of specific item to get stats for. Required if item_type is not 'ALL'.

    Returns:
        StatsResponse: Object containing:
            - total_products: Count of team's products (null if item_type is "product")
            - total_projects: Count of team's projects (filtered by product if item_type is "product")
            - total_components: Count of team's components (filtered by product if item_type is "product")
            - component_uploads: List of latest 10 component SBOM uploads
            - license_count: Dictionary mapping license IDs/names to their frequency
    """
    result = StatsResponse()

    # Return empty stats if no team and no item_id provided
    if not team and not item_id:
        result.total_products = None
        result.total_projects = None
        result.total_components = None
        result.license_count = {}
        result.component_uploads = []
        return result

    # Base querysets
    products_qs = Product.objects
    projects_qs = Project.objects
    components_qs = Component.objects
    sboms_qs = SBOM.objects

    # Apply team filter if provided
    if team:
        products_qs = products_qs.filter(team=team)
        projects_qs = projects_qs.filter(team=team)
        components_qs = components_qs.filter(team=team)
        sboms_qs = sboms_qs.filter(component__team=team)

    # Get item counts based on type
    if item_type is None:
        result.total_products = products_qs.count()
        result.total_projects = projects_qs.count()
        result.total_components = components_qs.count()
    elif item_type == "product":
        result.total_products = None
        result.total_projects = Project.objects.filter(productproject__product_id=item_id).count()
        result.total_components = (
            Component.objects.filter(projectcomponent__project__productproject__product_id=item_id).distinct().count()
        )
    elif item_type == "project":
        result.total_products = None
        result.total_projects = None
        result.total_components = Component.objects.filter(projectcomponent__project_id=item_id).distinct().count()
    elif item_type == "component":
        result.total_products = None
        result.total_projects = None
        result.total_components = None

    # Get latest component uploads
    uploads_qs = SBOM.objects.select_related("component")

    if item_type == "product":
        uploads_qs = uploads_qs.filter(component__projectcomponent__project__productproject__product_id=item_id)
    elif item_type == "project":
        uploads_qs = uploads_qs.filter(component__projectcomponent__project_id=item_id)
    elif item_type == "component":
        uploads_qs = uploads_qs.filter(component_id=item_id)

    # Get the latest SBOM for each component (manual approach for DB compatibility)
    all_sboms_ordered = uploads_qs.order_by("component_id", "-created_at")
    latest_sboms_dict = {}
    for sbom in all_sboms_ordered:
        if sbom.component_id not in latest_sboms_dict:
            latest_sboms_dict[sbom.component_id] = sbom

    latest_sboms_list = list(latest_sboms_dict.values())
    # Further sort this list by created_at descending to maintain original intent for the top 10 overall
    latest_sboms_list.sort(key=lambda s: s.created_at, reverse=True)

    # Process component uploads
    result.component_uploads = []
    for sbom in latest_sboms_list[:10]:  # Limit to 10 latest uploads
        ci = ComponentUploadInfo(
            component_id=sbom.component.id,
            component_name=sbom.component.name,
            sbom_id=sbom.id,
            sbom_name=sbom.name,
            sbom_version=sbom.version,
            sbom_created_at=sbom.created_at,
        )
        result.component_uploads.append(ci)

    # Get license counts
    all_licenses_found = []

    LICENSE_NORMALIZATION_MAP = {
        # SPDX IDs are preferred, so mainly map common name variations to SPDX IDs
        "Apache 2.0": "Apache-2.0",
        "Apache 2.0 License": "Apache-2.0",
        "Apache-2.0 license": "Apache-2.0",
        "Apache License, Version 2.0": "Apache-2.0",
        "MIT License": "MIT",
        "MIT license": "MIT",
        "The MIT License": "MIT",
        "BSD": "BSD-3-Clause",  # Or BSD-2-Clause, be specific if possible or choose a common default
        "BSD License": "BSD-3-Clause",
        "New BSD License": "BSD-3-Clause",
        "BSD 3-Clause": "BSD-3-Clause",
        "BSD 3-Clause License": "BSD-3-Clause",
        "BSD 2-Clause": "BSD-2-Clause",
        "BSD 2-Clause License": "BSD-2-Clause",
        "ISC License": "ISC",
        "ISC license": "ISC",
        "Mozilla Public License 2.0": "MPL-2.0",
        "Eclipse Public License 1.0": "EPL-1.0",
        "Eclipse Public License 2.0": "EPL-2.0",
        "GNU General Public License v2.0 only": "GPL-2.0-only",
        "GNU General Public License v3.0 only": "GPL-3.0-only",
        "GNU Lesser General Public License v2.1 only": "LGPL-2.1-only",
        "GNU Lesser General Public License v3.0 only": "LGPL-3.0-only",
        # Specific verbose names to common IDs
        "new BSD License": "BSD-3-Clause",
        "[The BSD 3-Clause License]": "BSD-3-Clause",
        "pytest-django is released under the BSD (3-clause) license": "BSD-3-Clause",
        # Add other common variations as needed
    }

    for sbom_instance in latest_sboms_list:  # Iterate through all relevant SBOMs for the component/item
        if sbom_instance.packages_licenses and isinstance(sbom_instance.packages_licenses, dict):
            # packages_licenses is Dict[str, List[Dict[str, str | None]]]
            # e.g., {"package_name": [{"id": "MIT", "name": "MIT License"}, ...]}
            for package_license_list in sbom_instance.packages_licenses.values():
                if isinstance(package_license_list, list):
                    for license_dict in package_license_list:
                        if isinstance(license_dict, dict):
                            # Extract license by ID preferably, then by name
                            license_id = license_dict.get("id")
                            license_name = license_dict.get("name")

                            chosen_license = None
                            if license_id:
                                chosen_license = str(license_id)  # Ensure it's a string
                            elif license_name:
                                chosen_license = str(license_name)  # Ensure it's a string

                            if chosen_license:
                                # Normalize before appending
                                chosen_license = LICENSE_NORMALIZATION_MAP.get(chosen_license, chosen_license)
                                all_licenses_found.append(chosen_license)

        # Optional: Consider licenses from sbom_instance.licenses if it's a simple list
        # This part is commented out because sbom.licenses is overwritten by a complex analysis dict
        # by the process_sbom_licenses task, making it unsuitable for simple license name/id aggregation here.
        # if sbom_instance.licenses and isinstance(sbom_instance.licenses, list):
        #     for lic in sbom_instance.licenses:
        #         if isinstance(lic, str):
        #             all_licenses_found.append(lic)
        #         elif isinstance(lic, dict):
        #             # Handle cases where sbom.licenses might store dicts like {"id": "..."} or {"name": "..."}
        #             license_id = lic.get('id')
        #             license_name = lic.get('name')
        #             chosen_license_top_level = license_id if license_id else license_name
        #             if chosen_license_top_level:
        #                 all_licenses_found.append(str(chosen_license_top_level))

    result.license_count = dict(Counter(all_licenses_found))

    return result
