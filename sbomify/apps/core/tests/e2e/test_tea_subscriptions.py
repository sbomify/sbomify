"""Remote artifacts from a TEA subscription on the release page, in a real browser.

The release's artifacts list shows what it pins from another TEA server with
what has happened to it upstream, and its Add Artifact dialog pins one.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.tea import pins, sync
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaSubscription
from sbomify.apps.tea.tests.fakes import FakeServer, artifact


@pytest.mark.django_db(transaction=True)
def test_the_release_artifacts_list_pins_a_remote_artifact_and_shows_what_changed(
    authenticated_page: Page, team_with_business_plan
) -> None:
    team = team_with_business_plan
    component = Component.objects.create(
        team=team, name="requests", component_type=Component.ComponentType.TEA_SUBSCRIPTION
    )
    subscription = TeaSubscription.objects.create(
        component=component,
        api_base_url="https://tea.example.com/tea/v1.0.0",
        spec_version="1.0.0",
        remote_component_uuid="remote-component",
    )
    server = FakeServer("remote-component")
    server.publish("r1", "2.32.3", days_ago=3, artifacts=[artifact("pinned"), artifact("other")])
    sync.check(subscription.pk, force=True, client_for=lambda _: server)
    product = Product.objects.create(team=team, name="Router")
    product.components.add(component)
    release = Release.objects.create(product=product, name="4.1.0")
    pins.pin(release, TeaRemoteArtifact.objects.get(uuid="pinned"))
    server.publish("r1", "2.32.3", days_ago=3, artifacts=[artifact("pinned", sha="b"), artifact("other")])
    sync.check(subscription.pk, force=True, client_for=lambda _: server)
    page = authenticated_page

    page.goto(reverse("core:release_details", args=[product.pk, release.pk]))

    expect(page.get_by_text("Changed since pinned")).to_be_visible()
    page.get_by_role("button", name="Add Artifact", exact=True).first.click()
    dialog = page.get_by_role("dialog")
    dialog.locator("tr", has_text="other.cdx.json").click(position={"x": 8, "y": 8})
    dialog.get_by_role("button", name="Add to Release").click()
    expect(page.get_by_role("link", name="other.cdx.json", exact=True)).to_be_visible()
    assert release.artifacts.filter(remote_artifact__uuid="other").exists()
