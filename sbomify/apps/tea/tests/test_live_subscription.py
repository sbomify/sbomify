"""TEA subscriptions end to end, over HTTP, through libtea's real client.

One workspace serves TEA 1.0 from a live server; a second subscribes to its
component, pins it into a release, and serves the pin from its own TEA API.
A second test reads the sbomify servers themselves, once they serve TEA 1.0.

Skipped by default, like the conformance suite. Run explicitly with:
    RUN_TEA_CONFORMANCE=1 uv run pytest sbomify/apps/tea/tests/test_live_subscription.py -v
    RUN_LIVE_TEA=1 uv run pytest sbomify/apps/tea/tests/test_live_subscription.py -v
"""

import os

import pytest
from django.test import Client, override_settings

from sbomify.apps.core.models import ComponentRelease, Product, Release
from sbomify.apps.tea import pins
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaSubscription
from sbomify.apps.tea.services import remote
from sbomify.apps.tea.services.subscriptions import Subscribe, subscribe
from sbomify.apps.teams.models import Workspace


@pytest.mark.skipif(os.environ.get("RUN_TEA_CONFORMANCE") != "1", reason="Set RUN_TEA_CONFORMANCE=1 to run")
@pytest.mark.django_db(transaction=True)
@override_settings(TEA_SUBSCRIPTION_ALLOW_PRIVATE_HOSTS=True)
def test_a_workspace_subscribes_to_another_over_tea(live_server, tea_conformance_data):
    publisher, _, _, component, sbom = tea_conformance_data
    host = os.environ.get("TEA_CONFORMANCE_HOST", "localhost")
    port = live_server.url.rsplit(":", 1)[-1]
    base_url = f"http://{host}:{port}/public/{publisher.key}/tea/v{TEA_API_VERSION}"
    component_release = ComponentRelease.objects.get(component=component, version=sbom.version)
    subscriber = Workspace.objects.create(name="subscriber", tea_enabled=True, is_public=True)

    subscription = subscribe(
        subscriber,
        Subscribe(
            server=remote.connect(base_url),
            component_uuid=str(component.uuid),
            release_uuids=[str(component_release.uuid)],
        ),
    )

    assert subscription.status == TeaSubscription.Status.OK, subscription.last_error
    assert subscription.remote_name == component.name
    watched = subscription.releases.get(uuid=str(component_release.uuid))
    remote_artifact = TeaRemoteArtifact.objects.get(release=watched, uuid=str(sbom.uuid))
    assert remote_artifact.state == TeaRemoteArtifact.State.CURRENT

    product = Product.objects.create(team=subscriber, name="uses the remote", is_public=True)
    product.components.add(subscription.component)
    subscription.component.visibility = subscription.component.Visibility.PUBLIC
    subscription.component.save()
    cut = Release.objects.create(product=product, name="1.0")
    pins.pin(cut, remote_artifact)

    collection = Client().get(
        f"/tea/v{TEA_API_VERSION}/productRelease/{cut.uuid}/collection/latest", {"workspace_key": subscriber.key}
    )

    (served,) = [a for a in collection.json()["artifacts"] if a["uuid"] == str(sbom.uuid)]
    assert served["version"] == remote_artifact.version


@pytest.mark.skipif(os.environ.get("RUN_LIVE_TEA") != "1", reason="Set RUN_LIVE_TEA=1 to read the sbomify servers")
@pytest.mark.parametrize("domain", ["library.sbomify.com", "pypi.sbomify.com"])
def test_the_sbomify_servers_speak_tea_1(domain):
    server = remote.connect(domain)

    assert server.spec_version.startswith("1.")
    assert remote.list_products(server).items
