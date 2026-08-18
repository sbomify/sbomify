import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact


@pytest.fixture
def contact_profiles(team_with_business_plan):  # noqa: F811
    """Two workspace contact profiles: a default one with a manufacturer and
    supplier entity carrying every optional field, and a second one whose entity
    is authors only. Between them the list rows, the default badge, the entity
    card and the contact rows are all rendered."""
    default_profile = ContactProfile.objects.create(
        team=team_with_business_plan,
        name="Default Profile",
        is_default=True,
    )
    acme = ContactEntity.objects.create(
        profile=default_profile,
        name="Acme Corporation",
        email="contact@acme.example",
        phone="+1 555 123 4567",
        address="123 Main Street, Springfield",
        website_urls=["https://acme.example", "https://docs.acme.example"],
        is_manufacturer=True,
        is_supplier=True,
        is_author=True,
    )
    ContactProfileContact.objects.create(
        entity=acme,
        name="Ada Lovelace",
        email="ada@acme.example",
        phone="+1 555 987 6543",
        order=0,
        is_author=True,
        is_security_contact=True,
    )
    ContactProfileContact.objects.create(
        entity=acme,
        name="Grace Hopper",
        email="grace@acme.example",
        order=1,
        is_technical_contact=True,
    )

    authors_profile = ContactProfile.objects.create(
        team=team_with_business_plan,
        name="Engineering Team",
    )
    authors = ContactEntity.objects.create(
        profile=authors_profile,
        name="Engineering Authors",
        is_author=True,
    )
    ContactProfileContact.objects.create(
        entity=authors,
        name="Alan Turing",
        email="alan@acme.example",
        order=0,
        is_author=True,
    )

    yield [default_profile, authors_profile]


def _settings_url(team) -> str:
    return f"/workspaces/{team.key}/settings/contact-profiles"


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestContactProfilesTabSnapshot:
    """The Contacts tab of workspace settings: the card, its toolbar and the
    profile rows the list partial builds from json_script."""

    def test_contact_profiles_tab_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        contact_profiles,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(_settings_url(team_with_business_plan))
        authenticated_page.wait_for_load_state("networkidle")
        authenticated_page.wait_for_selector("text=Default Profile")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestContactProfileFormSnapshot:
    """The profile editor, opened from the row menu with its entity expanded, so
    the entity card, its role checkboxes and the contact rows are all covered."""

    def test_contact_profile_form_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        contact_profiles,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(_settings_url(team_with_business_plan))
        authenticated_page.wait_for_load_state("networkidle")
        authenticated_page.wait_for_selector("text=Default Profile")

        authenticated_page.get_by_role("button", name="Profile actions").first.click()
        authenticated_page.get_by_role("menuitem", name="Edit profile").click()
        authenticated_page.wait_for_selector(".profile-form")
        authenticated_page.wait_for_selector(".entity-card")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".entity-card").first.click()
        authenticated_page.wait_for_selector(".contact-card")
        authenticated_page.wait_for_timeout(500)

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
