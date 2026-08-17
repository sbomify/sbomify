"""Both release detail pages expose the merged-HBOM download.

The download block used to be gated on SBOM/VEX/CBOM only, so a release pinning
just an HBOM rendered no download affordance at all — these lock the guard in.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.sboms.models import SBOM


def _release_with_hbom(team, *, is_public: bool) -> Release:
    product = Product.objects.create(name=f"P {is_public}", team=team, is_public=is_public)
    release = Release.objects.create(product=product, name="v1.0.0")
    # The public-page scenario needs a listable component: capability flags
    # come from the visibility-filtered artifact set, so a private component's
    # HBOM is deliberately not offered to an anonymous viewer.
    visibility = Component.Visibility.PUBLIC if is_public else Component.Visibility.PRIVATE
    component = Component.objects.create(name="board", team=team, visibility=visibility)
    hbom = SBOM.objects.create(
        name="board",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="board.json",
        component=component,
        bom_type=SBOM.BomType.HBOM,
    )
    ReleaseArtifact.objects.create(release=release, sbom=hbom)
    return release


@pytest.mark.django_db
def test_public_release_page_shows_hbom_download(sample_team_with_owner_member):
    release = _release_with_hbom(sample_team_with_owner_member.team, is_public=True)
    url = reverse("core:release_details_public", kwargs={"product_id": release.product.id, "release_id": release.id})

    resp = Client().get(url)

    assert resp.status_code == 200
    html = resp.content.decode()
    download_url = reverse("api-1:download_release_hbom", kwargs={"release_id": release.id})
    # Once: the Trust Center release page serves one responsive block. The
    # private page still carries a separate desktop and mobile block and so
    # renders the link twice; asserting a bare count here would track whichever
    # of the two pages was restyled most recently rather than the behaviour.
    assert html.count(download_url) == 1
    # The button's own label, not the surrounding panel heading — the heading is
    # Trust Center copy and has been reworded once already.
    assert ">HBOM<" in html.replace(" ", "").replace("\n", "")


@pytest.mark.django_db
def test_private_release_page_shows_hbom_download(authenticated_web_client, team_with_business_plan):
    release = _release_with_hbom(team_with_business_plan, is_public=False)
    url = reverse("core:release_details", kwargs={"product_id": release.product.id, "release_id": release.id})

    resp = authenticated_web_client.get(url)

    assert resp.status_code == 200
    html = resp.content.decode()
    assert html.count(reverse("api-1:download_release_hbom", kwargs={"release_id": release.id})) == 2


@pytest.mark.django_db
def test_release_without_artifacts_renders_no_download_card(sample_team_with_owner_member):
    """Regression: widening the guard must not make the card render for an empty release."""
    product = Product.objects.create(name="Empty", team=sample_team_with_owner_member.team, is_public=True)
    release = Release.objects.create(product=product, name="v1.0.0")
    url = reverse("core:release_details_public", kwargs={"product_id": product.id, "release_id": release.id})

    resp = Client().get(url)

    assert resp.status_code == 200
    assert "Download Release" not in resp.content.decode()
