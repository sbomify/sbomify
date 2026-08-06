"""Spotlight: the search bar as the fastest way to get anywhere in the app.

Navigation first. A person typing in the search bar usually wants to *go*
somewhere — settings, tokens, a wizard — and only sometimes wants to find a
specific product. So app destinations rank above assets, and assets fill the
tail rather than the head.

Everything navigable lives in ``data/spotlight_destinations.json``. Adding a
feature to the palette means appending one object there; nothing in this
module needs to change. The file's own header documents the shape, and
``test_spotlight.py`` fails loudly on a URL name that does not resolve, so a
typo cannot ship as a dead entry.

Matching is deliberately dumb: substring against the title and a keyword list,
scored by where the match lands. Nothing here needs a search engine — the
corpus is a few dozen fixed strings, and a person typing "tok" wants "API
tokens" immediately, not a ranked relevance model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from django.urls import NoReverseMatch, reverse

_DATA_FILE = Path(__file__).resolve().parent / "data" / "spotlight_destinations.json"

# Sections in the order a person scanning the palette should meet them:
# where to go, what to make, what to change, what to do. Assets come last —
# per the brief, surfacing them is the lowest-priority job of this bar.
SECTION_ORDER = (
    "navigate",
    "create",
    "settings",
    "actions",
    "advisories",
    "findings",
    "releases",
    "documents",
    "assets",
)
SECTION_LABELS = {
    "navigate": "Go to",
    "create": "Create",
    "settings": "Settings",
    "actions": "Actions",
    "advisories": "Advisories",
    "findings": "Affected components",
    "releases": "Releases",
    "documents": "Documents",
    "assets": "Products & components",
}

# Score bands. The gaps are wide enough that a section never outranks a
# better match in another section by accident.
_SCORE_TITLE_EXACT = 100
_SCORE_TITLE_PREFIX = 80
_SCORE_TITLE_SUBSTRING = 60
_SCORE_KEYWORD_PREFIX = 40
_SCORE_KEYWORD_SUBSTRING = 25
# Assets sit below every destination match by construction: a product named
# "Settings" must not outrank the Settings page for someone typing "settings".
ASSET_BASE_SCORE = 10


@dataclass(frozen=True)
class Destination:
    """One navigable place in the app."""

    title: str
    url_name: str
    section: str
    icon: str
    keywords: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    args: tuple[str, ...] = ()
    fragment: str = ""
    query: tuple[tuple[str, str], ...] = ()

    def visible_to(self, role: str) -> bool:
        """Whether a member with this role may see the destination.

        An empty ``roles`` means everyone. A blank role (no workspace in
        session) sees only unrestricted entries, which is the safe default:
        a palette entry is a hint that a feature exists.
        """
        return not self.roles or role in self.roles

    def resolve(self, *, team_key: str = "") -> str | None:
        """The concrete URL, or None when it cannot be built.

        Returns None rather than raising so one bad entry degrades to a
        missing row instead of a 500 on every keystroke.
        """
        kwargs = {}
        for arg in self.args:
            if arg == "team_key":
                if not team_key:
                    return None
                kwargs["team_key"] = team_key
            else:  # pragma: no cover - guarded by the registry test
                return None
        try:
            url = reverse(self.url_name, kwargs=kwargs)
        except NoReverseMatch:
            return None
        if self.query:
            url = f"{url}?{urlencode(dict(self.query))}"
        if self.fragment:
            url = f"{url}#{self.fragment}"
        return url


@lru_cache(maxsize=1)
def load_destinations() -> tuple[Destination, ...]:
    """The registry, parsed once per process.

    Cached because the file is static: a change ships with a deploy, and
    re-reading it per keystroke would put disk I/O on the search path.
    """
    raw = json.loads(_DATA_FILE.read_text())
    destinations = []
    for entry in raw.get("destinations", []):
        destinations.append(
            Destination(
                title=entry["title"],
                url_name=entry["url_name"],
                section=entry.get("section", "navigate"),
                icon=entry.get("icon", "fa-arrow-right"),
                keywords=tuple(entry.get("keywords", ())),
                roles=tuple(entry.get("roles", ())),
                args=tuple(entry.get("args", ())),
                fragment=entry.get("fragment", ""),
                query=tuple((entry.get("query") or {}).items()),
            )
        )
    return tuple(destinations)


def _score(destination: Destination, query: str) -> int:
    """How well this destination answers the query. 0 means no match."""
    title = destination.title.lower()
    if title == query:
        return _SCORE_TITLE_EXACT
    if title.startswith(query):
        return _SCORE_TITLE_PREFIX
    if query in title:
        return _SCORE_TITLE_SUBSTRING

    best = 0
    for keyword in destination.keywords:
        keyword = keyword.lower()
        if keyword.startswith(query):
            best = max(best, _SCORE_KEYWORD_PREFIX)
        elif query in keyword:
            best = max(best, _SCORE_KEYWORD_SUBSTRING)
    return best


def search_destinations(query: str, *, role: str = "", team_key: str = "", limit: int = 8) -> list[dict[str, Any]]:
    """Ranked app destinations for a query.

    Ties break on the section order, so "Go to" beats "Settings" at equal
    match quality; then on title *length*, because the shorter title is the
    closer match ("plug" should land on Plugins, not Plugin summary); then
    alphabetically for a stable result across keystrokes — a palette that
    reshuffles under the cursor is worse than a slightly worse-ranked one.
    """
    query = (query or "").strip().lower()
    if not query:
        return []

    scored: list[tuple[int, int, int, str, Destination, str]] = []
    for destination in load_destinations():
        if not destination.visible_to(role):
            continue
        score = _score(destination, query)
        if not score:
            continue
        url = destination.resolve(team_key=team_key)
        if url is None:
            continue
        section_rank = SECTION_ORDER.index(destination.section) if destination.section in SECTION_ORDER else 99
        scored.append((-score, section_rank, len(destination.title), destination.title, destination, url))

    scored.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return [
        {
            "title": destination.title,
            "url": url,
            "section": destination.section,
            "section_label": SECTION_LABELS.get(destination.section, destination.section.title()),
            "icon": destination.icon,
            "score": -negative_score,
        }
        for negative_score, _rank, _length, _title, destination, url in scored[:limit]
    ]
