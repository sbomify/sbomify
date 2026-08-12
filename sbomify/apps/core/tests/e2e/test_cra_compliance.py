"""Snapshot coverage for the CRA compliance surface.

The wizard steps, the scope screening and the CRA list had no e2e referee
before the component-library migration. The fixture below builds the same
shape an operator reaches through the product page: a screened product with
components and a live assessment.
"""

import hashlib
from typing import Generator

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403

# Imported at module scope on purpose. The compliance services pull in
# trestle, whose pydantic-v1 layer subclasses ``datetime.date`` at import
# time; the autouse freezegun fixture has replaced that class by the time a
# fixture body runs, and the import then dies on a metaclass conflict.
# Collection happens before any clock is frozen, so importing here is safe.
from sbomify.apps.compliance.models import CRAScopeScreening  # noqa: E402
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment  # noqa: E402


@pytest.fixture
def cra_billing_session(browser_context) -> None:
    """Put the Business plan key on the browser session's current workspace.

    ``CRAProductListView`` reads the plan from the session rather than the
    team row, and the shared session helper does not write it, so without
    this the list page only ever renders its locked panel.
    """
    from django.contrib.sessions.backends.db import SessionStore
    from django.contrib.sessions.models import Session

    for row in Session.objects.all():
        store = SessionStore(session_key=row.session_key)
        current_team = store.get("current_team") or {}
        current_team["billing_plan"] = "business"
        store["current_team"] = current_team
        store.save()


@pytest.fixture
def cra_assessment(
    product_factory,  # noqa: F405
    component_factory,  # noqa: F405
    sbom_factory,  # noqa: F405
    sample_user,  # noqa: F405
    team_with_business_plan,  # noqa: F405
) -> Generator:
    """A screened product with a live CRA assessment.

    One component carries an SBOM and one does not, so step 2 renders both
    its coverage summary and its incomplete-coverage warning.
    """
    name = "CRA Test Product"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    product = product_factory(name=name, _id=_id)

    bom = component_factory("CRA BOM Component", Component.ComponentType.BOM, product=product)
    sbom_factory(bom, name="cra-sbom.json", version="1.0.0")
    component_factory("CRA Document Component", Component.ComponentType.DOCUMENT, product=product)

    CRAScopeScreening.objects.create(
        product=product,
        team=team_with_business_plan,
        created_by=sample_user,
        has_data_connection=True,
    )

    result = get_or_create_assessment(product.id, sample_user, team_with_business_plan)
    assert result.ok, result.error

    yield result.value


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
@pytest.mark.parametrize("step", [1, 2, 3, 4, 5])
class TestCRAWizardStepSnapshot:
    """Every wizard step, so the stepper rail and each step body are pinned."""

    def test_cra_wizard_step_snapshot(
        self,
        authenticated_page: Page,
        cra_assessment,
        snapshot,
        width: int,
        step: int,
    ) -> None:
        authenticated_page.goto(f"/compliance/cra/{cra_assessment.id}/step/{step}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestCRAScopeScreeningSnapshot:
    """The pre-wizard scope questions, verdict panel and actions."""

    def test_cra_scope_screening_snapshot(
        self,
        authenticated_page: Page,
        cra_assessment,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/compliance/cra/scope/{cra_assessment.product_id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestCRAProductListSnapshot:
    """The CRA list with a row in it: status badge, progress and the CTA."""

    def test_cra_product_list_snapshot(
        self,
        authenticated_page: Page,
        cra_billing_session,
        cra_assessment,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/compliance/cra/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
