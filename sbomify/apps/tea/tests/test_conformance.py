"""
TEA conformance tests using libtea's conformance suite.

Runs libtea's full conformance suite against sbomify's TEA endpoints
via live_server, validating spec compliance end-to-end.

Skipped by default. Run explicitly with:
    RUN_TEA_CONFORMANCE=1 uv run pytest sbomify/apps/tea/tests/test_conformance.py -v -s
"""

import os
from datetime import UTC, datetime

import pytest

if os.environ.get("RUN_TEA_CONFORMANCE") != "1":
    pytest.skip("Set RUN_TEA_CONFORMANCE=1 to run", allow_module_level=True)

from libtea.conformance import CheckStatus, run_conformance

from sbomify.apps.core.models import ComponentRelease, Product, Release
from sbomify.apps.core.services.cle import (
    create_cle_event,
    create_component_cle_event,
    create_component_release_cle_event,
    create_release_cle_event,
)
from sbomify.apps.sboms.models import ProductIdentifier
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaRemoteRelease
from sbomify.apps.tea.pins import pin


def _give_every_check_something_to_read(team, product, release, component, component_release):
    """Data for the checks that otherwise skip: an identifier to search by, a second
    product to page through, and two lifecycle events on each object."""
    ProductIdentifier.objects.create(
        product=product, team=team, identifier_type=ProductIdentifier.IdentifierType.PURL, value="pkg:pypi/tea-check"
    )
    Product.objects.create(name="second product", team=team, is_public=True)
    for create, subject in (
        (create_cle_event, product),
        (create_release_cle_event, release),
        (create_component_cle_event, component),
        (create_component_release_cle_event, component_release),
    ):
        for month, version in ((1, "1.0.0"), (6, "2.0.0")):
            assert create(subject, "released", datetime(2025, month, 1, tzinfo=UTC), version=version).ok


def _pin_a_remote_artifact(team, product, make_subscription):
    """A release whose collection carries an artifact published on another TEA server, as a subscription pins it.

    Its own release, so the collection stays at version 1: sbomify keeps only a collection's latest version.
    """
    release = Release.objects.create(product=product, name="v2.0.0-remote")
    subscription = make_subscription(team)
    product.components.add(subscription.component)
    remote_release = TeaRemoteRelease.objects.create(subscription=subscription, uuid="remote-release", version="1.0")
    remote = TeaRemoteArtifact.objects.create(
        release=remote_release,
        uuid="6f1c6a7e-4c1b-4bd0-9a43-3b1f3c1c2a10",
        version=2,
        name="remote.cdx.json",
        snapshot={
            "uuid": "6f1c6a7e-4c1b-4bd0-9a43-3b1f3c1c2a10",
            "name": "remote.cdx.json",
            "type": "BOM",
            "version": 2,
            "createdDate": "2025-01-01T00:00:00Z",
            "formats": [
                {
                    "mediaType": "application/vnd.cyclonedx+json",
                    "url": "https://cdn.example.com/remote.cdx.json",
                    "checksums": [{"algType": "SHA-256", "algValue": "a" * 64}],
                }
            ],
        },
        snapshot_fingerprint="fp",
    )
    pin(release, remote)
    return release


def format_failures(failures):
    """Format failed checks into a readable assertion message."""
    lines = [f"{len(failures)} conformance check(s) failed:"]
    for check in failures:
        lines.append(f"  - {check.name}: {check.message}")
        if check.details:
            lines.append(f"    {check.details}")
    return "\n".join(lines)


@pytest.mark.django_db(transaction=True)
class TestTEAConformance:
    def test_conformance_suite(self, live_server, tea_conformance_data, make_subscription):
        team, product, _, component, sbom = tea_conformance_data
        release = _pin_a_remote_artifact(team, product, make_subscription)

        # live_server binds to 0.0.0.0 but middleware only allows named hosts.
        # Use TEA_CONFORMANCE_HOST (default: localhost) for the Host header.
        host = os.environ.get("TEA_CONFORMANCE_HOST", "localhost")
        port = live_server.url.rsplit(":", 1)[-1]
        # libtea reads the spec version to test from the /v<version> suffix.
        base_url = f"http://{host}:{port}/public/{team.key}/tea/v{TEA_API_VERSION}"
        # Uploading the SBOM created this release; its UUID is not the SBOM's.
        component_release = ComponentRelease.objects.get(component=component, version=sbom.version)
        _give_every_check_something_to_read(team, product, release, component, component_release)

        result = run_conformance(
            base_url=base_url,
            tei=f"tei://example.com/uuid/{product.uuid}",
            product_uuid=str(product.uuid),
            product_release_uuid=str(release.uuid),
            component_uuid=str(component.uuid),
            component_release_uuid=str(component_release.uuid),
            artifact_uuid=str(sbom.uuid),
            allow_private_ips=True,
        )

        failures = [c for c in result.checks if c.status == CheckStatus.FAIL]
        assert not failures, format_failures(failures)
        skipped = {c.name for c in result.checks if c.status == CheckStatus.SKIP}
        assert not skipped, sorted(skipped)

        # Sanity: ensure checks actually ran
        assert len(result.checks) > 0, "No conformance checks were executed"
