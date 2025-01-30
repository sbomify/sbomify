import json
from collections import Counter
from typing import Literal

from django.db import connection

from teams.models import Team

from .models import SBOM, Component, Product, ProductProject, Project, ProjectComponent
from .schemas import ComponentUploadInfo, DBSBOMLicense, StatsResponse


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

    query_params = {}
    if team:
        query_params["team_id"] = team.id

    if item_id:
        query_params["item_id"] = item_id

    # Return empty stats if no team and no item_id provided
    if not team and not item_id:
        result.total_products = None
        result.total_projects = None
        result.total_components = None
        result.license_count = {}
        result.component_uploads = []
        return result

    # Get item counts
    if item_type is None:
        sql = f"""
        SELECT product_count, project_count, component_count
        FROM (
            SELECT COUNT(*) AS product_count
            FROM {Product._meta.db_table}
            WHERE team_id = %(team_id)s
        ) AS products,
        (
            SELECT COUNT(*) AS project_count
            FROM {Project._meta.db_table}
            WHERE team_id = %(team_id)s
        ) AS projects,
        (
            SELECT COUNT(*) AS component_count
            FROM {Component._meta.db_table}
            WHERE team_id = %(team_id)s
        ) AS components
        """  # nosec B608

    elif item_type == "product":
        sql = f"""
        SELECT NULL as product_count, project_count, component_count
        FROM (
            SELECT COUNT(*) AS project_count
            FROM {Project._meta.db_table} p
            INNER JOIN {ProductProject._meta.db_table} pp ON p.id = pp.project_id
            WHERE pp.product_id = %(item_id)s
        ) AS projects,
        (
            SELECT COUNT(*) AS component_count
            FROM {Component._meta.db_table} c
            INNER JOIN {ProjectComponent._meta.db_table} pc ON c.id = pc.component_id
            INNER JOIN {ProductProject._meta.db_table} pp ON pc.project_id = pp.project_id
            WHERE pp.product_id = %(item_id)s
        ) AS components
        """  # nosec B608

    elif item_type == "project":
        sql = f"""
        SELECT NULL as product_count, NULL as project_count, component_count
        FROM (
            SELECT COUNT(*) AS component_count
            FROM {Component._meta.db_table} c
            INNER JOIN {ProjectComponent._meta.db_table} pc ON c.id = pc.component_id
            WHERE pc.project_id = %(item_id)s
        ) AS components
        """  # nosec B608

    elif item_type == "component":
        sql = """
        SELECT NULL as product_count, NULL as project_count, NULL as component_count
        """  # nosec B608

    # Get latest component uploads
    uploads_sql = f"""
    SELECT c.id, c.name, s.id, s.name, s.version, s.created_at
    FROM {Component._meta.db_table} c
    INNER JOIN {SBOM._meta.db_table} s ON c.id=s.component_id
    """  # nosec B608

    where_or_and = "AND" if team else "WHERE"

    uploads_sql += f"""
    {f"INNER JOIN {ProjectComponent._meta.db_table} pc ON c.id=pc.component_id "
     f"INNER JOIN {ProductProject._meta.db_table} pp ON pc.project_id=pp.project_id "
     f"INNER JOIN {Product._meta.db_table} p ON pp.product_id=p.id"
     if item_type == "product" else ""}

    {f"INNER JOIN {ProjectComponent._meta.db_table} pc ON c.id=pc.component_id "
     f"INNER JOIN {Project._meta.db_table} p ON pc.project_id=p.id"
     if item_type == "project" else ""}

    {" WHERE c.team_id=%(team_id)s" if team else ""}
    {f" {where_or_and} c.id=%(item_id)s" if item_type == "component" else ""}
    {f" {where_or_and} p.id=%(item_id)s" if item_type == "project" else ""}
    {f" {where_or_and} pp.product_id=%(item_id)s" if item_type == "product" else ""}
    ORDER BY s.created_at DESC
    LIMIT 10;
    """  # nosec B608

    latest_component_sbom_licenses_sql = f"""
    WITH latest_sboms AS (
        SELECT
        ROW_NUMBER() OVER (PARTITION BY s.component_id ORDER BY s.component_id, s.created_at desc) AS row_num,
        s.packages_licenses
        FROM {SBOM._meta.db_table} s
        {f"INNER JOIN {Component._meta.db_table} c ON s.component_id=c.id "
         if item_type == "component" else ""}
        {f"INNER JOIN {Component._meta.db_table} c ON s.component_id=c.id "
         f"INNER JOIN {ProjectComponent._meta.db_table} pc ON c.id=pc.component_id "
         f"INNER JOIN {Project._meta.db_table} p ON pc.project_id=p.id"
         if item_type == "project" else ""}
        {f"INNER JOIN {Component._meta.db_table} c ON s.component_id=c.id "
         f"INNER JOIN {ProjectComponent._meta.db_table} pc ON c.id=pc.component_id "
         f"INNER JOIN {ProductProject._meta.db_table} pp ON pc.project_id=pp.project_id "
         f"INNER JOIN {Product._meta.db_table} p ON pp.product_id=p.id"
         if item_type == "product" else ""}

        {f" WHERE s.component_id IN (SELECT id FROM {Component._meta.db_table} WHERE team_id=%(team_id)s)"
         if team else ""}
        {f" {where_or_and} c.id=%(item_id)s" if item_type == "component" else ""}
        {f" {where_or_and} p.id=%(item_id)s" if item_type == "project" else ""}
        {f" {where_or_and} pp.product_id=%(item_id)s" if item_type == "product" else ""}
    )
    SELECT packages_licenses FROM latest_sboms WHERE row_num=1;
    """  # nosec B608

    with connection.cursor() as cursor:
        # Get item counts
        cursor.execute(sql, query_params)

        result.total_products, result.total_projects, result.total_components = cursor.fetchone()

        cursor.execute(uploads_sql, query_params)

        # Latest component uploads
        result.component_uploads = []

        for row in cursor.fetchall():
            ci = ComponentUploadInfo()

            ci.component_id, ci.component_name, ci.sbom_id, ci.sbom_name, ci.sbom_version, ci.sbom_created_at = row
            result.component_uploads.append(ci)

        # Get latest component sbom licenses and then calculate count of each standard license present.
        cursor.execute(latest_component_sbom_licenses_sql, query_params)
        all_licenses = []
        for licenses_dict in cursor.fetchall():
            if not licenses_dict[0]:
                continue
            licenses_list = json.loads(licenses_dict[0]).values()

            for package_licenses in licenses_list:
                for l_dict in package_licenses:
                    l_item = DBSBOMLicense(**l_dict)

                    if l_item.id:
                        all_licenses.append(l_item.id)
                    elif l_item.name:
                        all_licenses.append(l_item.name)

        result.license_count = dict(Counter(all_licenses))

    return result
