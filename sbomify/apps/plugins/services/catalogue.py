"""Describe the plugin catalogue for the page frame that renders before it."""

from django.db.models import Count

from sbomify.apps.core.services.results import ServiceResult

from ..models import RegisteredPlugin


def get_catalogue_shape() -> ServiceResult[dict[str, int | list[int]]]:
    """Describe the plugins page before its content arrives.

    The page frame loads its summary and its plugin list over HTMX, so the
    skeletons it renders first have to be told how many cards and rows to draw.
    Those counts come from the plugin catalogue, which is workspace independent:
    a workspace changes which plugins are enabled, never which exist. One
    grouped count over a small table, and no plan or membership lookup, which is
    what the page deliberately defers.

    ``stat_cards`` is the summary bar: the two fixed totals plus one card per
    category. ``section_rows`` is the list below it, one entry per category card
    holding that category's plugin count, so the placeholder draws the cards and
    rows that actually arrive rather than a generic two.
    """
    categories = RegisteredPlugin.objects.filter(is_enabled=True).values("category").annotate(total=Count("id"))
    section_rows = sorted((row["total"] for row in categories), reverse=True)
    return ServiceResult.success(
        {
            "stat_cards": 2 + len(section_rows),
            "section_rows": section_rows,
        }
    )
