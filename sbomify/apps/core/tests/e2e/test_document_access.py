"""Snapshot coverage for the two public document-access pages.

The request-access form and the NDA signing page had no referee at all, so each
gained one here before the component-library migration touched them.

Both need a workspace the signed-in user does not belong to: a member already
has access, and the request view redirects them to the public workspace page
instead of rendering the form.
"""

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Team


@pytest.fixture
def gated_workspace() -> Team:
    """A workspace the signed-in user is not a member of. The key is derived
    from the pk by hand, as the team helpers do: nothing sets it on create."""
    team = Team.objects.create(name="Gated Workspace")
    team.key = number_to_random_token(team.pk)
    team.save(update_fields=["key"])
    return team


@pytest.fixture
def gated_workspace_with_nda(gated_workspace, document_component_details):  # noqa: F811
    """The same workspace with a company-wide NDA, which is what turns on the
    NDA notice on the request form and makes the signing page reachable."""
    nda = Document.objects.get(component=document_component_details)
    gated_workspace.branding_info = {"company_nda_document_id": nda.id}
    gated_workspace.save(update_fields=["branding_info"])
    return gated_workspace


@pytest.fixture
def pending_nda_request(gated_workspace_with_nda, sample_user):  # noqa: F811
    return AccessRequest.objects.create(team=gated_workspace_with_nda, user=sample_user)


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestRequestAccessSnapshot:
    def test_request_access_snapshot(
        self,
        authenticated_page: Page,
        gated_workspace,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/workspace/{gated_workspace.key}/access-request")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_request_access_nda_snapshot(
        self,
        authenticated_page: Page,
        gated_workspace_with_nda,
        snapshot,
        width: int,
    ) -> None:
        # The NDA notice only renders on this branch.
        authenticated_page.goto(f"/workspace/{gated_workspace_with_nda.key}/access-request")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSignNdaSnapshot:
    def test_sign_nda_snapshot(
        self,
        authenticated_page: Page,
        pending_nda_request,
        snapshot,
        width: int,
    ) -> None:
        team = pending_nda_request.team

        authenticated_page.goto(f"/workspace/{team.key}/access-request/{pending_nda_request.id}/sign-nda")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
