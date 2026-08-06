"""Risk categories for SPDX licence ids.

Procurement reads these as a risk signal, so the file is held to two rules: an
id that is not confidently classifiable stays absent, and an id that IS listed
must actually exist in SPDX. A typo would otherwise be dead config that silently
categorises nothing.
"""

from __future__ import annotations

import pytest

from sbomify.apps.licensing.loader import SPDX_CATEGORIES, SPDX_SYMBOLS, get_license_list

VALID_CATEGORIES = {
    "public-domain",
    "permissive",
    "weak-copyleft",
    "strong-copyleft",
    "network-copyleft",
    "proprietary",
}


def test_every_mapped_id_is_a_real_spdx_id():
    """A typo maps nothing and fails silently, so it is asserted rather than
    trusted."""
    unknown = sorted(k for k in SPDX_CATEGORIES if k not in SPDX_SYMBOLS)

    assert unknown == [], f"not SPDX ids: {unknown}"


def test_every_category_is_one_of_the_declared_set():
    unexpected = sorted(set(SPDX_CATEGORIES.values()) - VALID_CATEGORIES)

    assert unexpected == []


def test_an_id_appears_under_exactly_one_category():
    """The file is category-keyed, so a duplicate id would silently take
    whichever category the loader saw last."""
    from collections import Counter

    import yaml

    from sbomify.apps.licensing import loader
    from sbomify.apps.licensing.loader import os as loader_os  # noqa: F401

    path = loader.os.path.join(loader.os.path.dirname(loader.__file__), "data", "spdx_categories.yaml")
    with open(path) as f:
        by_category = yaml.safe_load(f)

    counts = Counter(i for ids in by_category.values() for i in (ids or []))

    assert [i for i, n in counts.items() if n > 1] == []


@pytest.mark.parametrize(
    ("license_id", "category"),
    [
        ("MIT", "permissive"),
        ("Apache-2.0", "permissive"),
        ("BSD-3-Clause", "permissive"),
        ("LGPL-2.1-only", "weak-copyleft"),
        ("MPL-2.0", "weak-copyleft"),
        ("GPL-3.0-only", "strong-copyleft"),
        ("GPL-2.0-or-later", "strong-copyleft"),
        ("AGPL-3.0-only", "network-copyleft"),
        ("CC0-1.0", "public-domain"),
        ("Elastic-2.0", "proprietary"),
    ],
)
def test_the_well_known_licences_land_in_the_right_bucket(license_id, category):
    """The ones a reviewer would spot immediately if they were wrong."""
    assert SPDX_CATEGORIES[license_id] == category


def test_gpl_and_lgpl_are_not_conflated():
    """Linking exception or not is the whole distinction; collapsing them would
    make the risk view wrong in the direction that matters."""
    assert SPDX_CATEGORIES["GPL-3.0-only"] != SPDX_CATEGORIES["LGPL-3.0-only"]


class TestTheLicenceList:
    def test_a_categorised_licence_carries_its_category(self):
        entry = next(x for x in get_license_list() if x["key"] == "MIT")

        assert entry["category"] == "permissive"

    def test_an_uncategorised_licence_omits_the_key(self):
        """Absent rather than None or 'unknown', so a caller can tell "we did
        not classify this" from a classification we made."""
        uncategorised = [x for x in get_license_list() if x["origin"] == "SPDX" and x["key"] not in SPDX_CATEGORIES]

        assert uncategorised, "expected some SPDX ids to stay unmapped"
        assert all("category" not in x for x in uncategorised)

    def test_the_custom_licences_still_carry_theirs(self):
        """non_spdx.yaml already had categories; this must not disturb them."""
        custom = [x for x in get_license_list() if x["origin"] != "SPDX"]

        assert custom
        assert all(x.get("category") for x in custom)


def test_a_licence_listed_both_as_spdx_and_custom_is_categorised_on_both():
    """get_license_list() emits the SPDX and custom entries separately, so an
    id present in both needs a category in both places or the SPDX copy shows
    as unclassified beside a classified twin. BUSL-1.1 and SSPL-1.0 are the
    real cases."""
    from sbomify.apps.licensing.loader import CUSTOM_SYMBOLS

    dual = [k for k in CUSTOM_SYMBOLS if k in SPDX_SYMBOLS]

    assert dual, "expected some ids in both sets"
    missing = sorted(k for k in dual if k not in SPDX_CATEGORIES)
    assert missing == [], f"SPDX copy left uncategorised: {missing}"
