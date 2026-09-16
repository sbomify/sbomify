import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from sbomify.apps.teams.models import ContactEntity, ContactProfile, Team


@pytest.mark.django_db
def test_cannot_create_profile_without_entities(authenticated_page: Page, team_with_business_plan: Team) -> None:
    page = authenticated_page
    page.goto(reverse("teams:team_settings_tab", args=[team_with_business_plan.key, "contact-profiles"]))
    expect(page.get_by_text("No contact profiles yet", exact=True)).to_be_visible()
    page.get_by_role("button", name="Add profile", exact=True).click()
    page.locator('.profile-form input[name="name"]').fill("Empty profile")

    expect(page.locator('.profile-form button[type="submit"]')).to_be_disabled()
    assert not ContactProfile.objects.filter(team=team_with_business_plan, name="Empty profile").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("incomplete_entity", [False, True])
def test_delete_empty_or_incomplete_profile(
    authenticated_page: Page, team_with_business_plan: Team, incomplete_entity: bool
) -> None:
    profile = ContactProfile.objects.create(team=team_with_business_plan, name="Empty profile")
    if incomplete_entity:
        ContactEntity.objects.create(profile=profile, is_author=True)

    page = authenticated_page
    page.goto(reverse("teams:team_settings_tab", args=[team_with_business_plan.key, "contact-profiles"]))
    page.get_by_role("button", name="Profile actions").click()
    page.get_by_role("menuitem", name="Delete profile", exact=True).click()
    page.get_by_role("button", name="Delete Profile", exact=True).click()

    expect(page.get_by_text("No contact profiles yet", exact=True)).to_be_visible()
    assert not ContactProfile.objects.filter(pk=profile.pk).exists()
