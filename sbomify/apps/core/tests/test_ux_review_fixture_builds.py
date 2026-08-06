"""The trust-center UX fixture, checked outside the screenshot generator.

The generator is gated behind RUN_UX_REVIEW=1 and skipped in CI, which is
right for a screenshot tool but meant it rotted silently: 28 of its 32 cases
had been erroring at fixture setup and nothing reported it.

This builds the same fixture with no browser and no screenshots, so the
generator's setup is covered by an ordinary CI run.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.models import LATEST_RELEASE_NAME, Release
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403

pytestmark = pytest.mark.django_db


def test_the_trust_center_fixture_builds(trust_center_product):
    """Guards the collision between the fixture's own latest release and the
    one the SBOM/document signals create. Adding both used to raise
    "A product can only have one latest release"."""
    assert trust_center_product.pk is not None


def test_the_product_ends_up_with_exactly_one_latest_release(trust_center_product):
    latest = Release.objects.filter(product=trust_center_product, is_latest=True)

    assert latest.count() == 1
    assert latest.get().name == LATEST_RELEASE_NAME


def test_the_versioned_releases_are_all_present(trust_center_product):
    """The screenshots are of a populated product; an empty release list would
    still pass the checks above."""
    names = set(Release.objects.filter(product=trust_center_product, is_latest=False).values_list("name", flat=True))

    assert {"v1.0.0", "v1.1.0", "v2.0.0", "v2.1.0-beta"} <= names
