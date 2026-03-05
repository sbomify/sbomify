"""
TEA conformance tests using libtea's conformance suite.

Runs the full 26-check conformance suite against sbomify's TEA endpoints
via live_server, validating spec compliance end-to-end.

Skipped by default. Run explicitly with:
    RUN_TEA_CONFORMANCE=1 uv run pytest sbomify/apps/tea/tests/test_conformance.py -v -s
"""

import os

import pytest

if os.environ.get("RUN_TEA_CONFORMANCE") != "1":
    pytest.skip("Set RUN_TEA_CONFORMANCE=1 to run", allow_module_level=True)

from libtea.conformance import CheckStatus, run_conformance

from sbomify.apps.tea.mappers import TEA_API_VERSION


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
    def test_conformance_suite(self, live_server, tea_conformance_data):
        team, product, release, component, sbom = tea_conformance_data

        # live_server binds to 0.0.0.0 but middleware only allows named hosts.
        # Use TEA_CONFORMANCE_HOST (default: localhost) for the Host header.
        host = os.environ.get("TEA_CONFORMANCE_HOST", "localhost")
        port = live_server.url.rsplit(":", 1)[-1]
        base_url = f"http://{host}:{port}/public/{team.key}/tea/v{TEA_API_VERSION}"

        result = run_conformance(
            base_url=base_url,
            product_uuid=str(product.uuid),
            product_release_uuid=str(release.uuid),
            component_uuid=str(component.uuid),
            component_release_uuid=str(sbom.uuid),
            artifact_uuid=str(sbom.uuid),
            allow_private_ips=True,
        )

        failures = [c for c in result.checks if c.status == CheckStatus.FAIL]
        assert not failures, format_failures(failures)

        # Sanity: ensure checks actually ran
        assert len(result.checks) > 0, "No conformance checks were executed"
