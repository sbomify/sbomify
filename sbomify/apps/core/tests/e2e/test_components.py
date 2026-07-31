import pytest
from playwright.sync_api import Page

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentsListSnapshot:
    def test_components_list_snapshot(
        self,
        authenticated_page: Page,
        dashboard,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/components/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentDetailsPrivateSnapshot:
    def test_component_details_private_sbom_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/component/{sbom_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_component_details_private_document_snapshot(
        self,
        authenticated_page: Page,
        document_component_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/component/{document_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentDetailsPublicSnapshot:
    def test_component_details_public_sbom_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        # The /public/component/ view forbids PRIVATE components (403), so the
        # component must be public for the public page to render. Scoped to the
        # public test so the private snapshot keeps exercising a private component.
        sbom_component_details.visibility = Component.Visibility.PUBLIC
        sbom_component_details.save(update_fields=["visibility"])

        authenticated_page.goto(f"/public/component/{sbom_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_component_details_public_document_snapshot(
        self,
        authenticated_page: Page,
        document_component_details,
        snapshot,
        width: int,
    ) -> None:
        # See note above: the public view 403s PRIVATE components, so flip this
        # one public for the public-page snapshot only.
        document_component_details.visibility = Component.Visibility.PUBLIC
        document_component_details.save(update_fields=["visibility"])

        authenticated_page.goto(f"/public/component/{document_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentArtifactsSnapshot:
    """The View-all artifacts page introduced with the component redesign."""

    def test_component_artifacts_page_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/component/{sbom_component_details.id}/artifacts/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentVexDetailsSnapshot:
    """The canonical /vex/ artifact page with its suppressed-vulnerabilities card."""

    def test_component_vex_details_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        import hashlib

        from sbomify.apps.sboms.models import SBOM

        vex = SBOM.objects.create(
            id=hashlib.md5(b"test-vex-artifact").hexdigest()[:12],
            name="triage-vex.json",
            component=sbom_component_details,
            format="cyclonedx",
            format_version="1.6",
            version="triage-1",
            sbom_filename="",
            source="sbomify-triage",
            bom_type=SBOM.BomType.VEX,
        )

        authenticated_page.goto(f"/components/{sbom_component_details.id}/vex/{vex.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentCbomDetailsSnapshot:
    """The canonical /cbom/ artifact page (crypto inventory collapses when empty)."""

    def test_component_cbom_details_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        import hashlib

        from sbomify.apps.sboms.models import SBOM

        cbom = SBOM.objects.create(
            id=hashlib.md5(b"test-cbom-artifact").hexdigest()[:12],
            name="crypto-cbom.json",
            component=sbom_component_details,
            format="cyclonedx",
            format_version="1.7",
            version="cbom-1",
            sbom_filename="",
            source="test",
            bom_type=SBOM.BomType.CBOM,
        )

        authenticated_page.goto(f"/components/{sbom_component_details.id}/cbom/{cbom.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestWorkspaceCryptoSnapshot:
    """The workspace cryptography dashboard, populated from persisted PQC runs."""

    def test_workspace_crypto_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        import hashlib

        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM

        cbom = SBOM.objects.create(
            id=hashlib.md5(b"e2e-crypto-cbom").hexdigest()[:12],
            name="crypto-inventory.cdx.json",
            component=sbom_component_details,
            format="cyclonedx",
            format_version="1.6",
            version="crypto-1",
            sbom_filename="",
            bom_type=SBOM.BomType.CBOM,
        )
        AssessmentRun.objects.create(
            sbom=cbom,
            plugin_name="pqc-readiness",
            plugin_version="1.0.0",
            plugin_config_hash="e2e",
            category="compliance",
            status="completed",
            run_reason="manual",
            result={
                "metadata": {
                    "pqc_overall": "at_risk",
                    "certificates": {"count": 2, "expired": 1, "expiring_soon": 1, "soonest_not_valid_after": None},
                },
                "findings": [
                    {
                        "title": "RSA-2048 — Quantum-vulnerable",
                        "metadata": {"pqc_status": "quantum_vulnerable", "asset_name": "RSA-2048"},
                    },
                    {
                        "title": "ECDSA-P256 — Quantum-vulnerable",
                        "metadata": {"pqc_status": "quantum_vulnerable", "asset_name": "ECDSA-P256"},
                    },
                    {
                        "title": "ML-KEM-768 — Quantum-safe",
                        "metadata": {"pqc_status": "quantum_safe", "asset_name": "ML-KEM-768"},
                    },
                ],
            },
        )

        authenticated_page.goto(f"/workspaces/{sbom_component_details.team.key}/crypto/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
