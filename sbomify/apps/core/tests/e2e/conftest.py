from typing import Any, Generator
from urllib.parse import urlparse

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    setup_authenticated_client_session,
    team_with_business_plan,
)
from sbomify.apps.core.tests.e2e.utils import (
    assert_screenshot as _assert_screenshot,
    get_or_create_baseline_screenshot as _get_or_create_baseline_screenshot,
    take_screenshot as _take_screenshot,
    BROWSER_WIDTH,
    BROWSER_HEIGHT,
)


@pytest.fixture(scope="session")
def playwright() -> Generator[Playwright, Any, None]:
    with sync_playwright() as playwright_instance:
        yield playwright_instance


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict[str, Any]:
    return {
        "headless": True,
        "slow_mo": 0,
    }


@pytest.fixture(scope="session")
def browser(playwright: Playwright, browser_type_launch_args: dict[str, Any]) -> Generator[Browser, Any, None]:
    browser_instance = playwright.chromium.launch(**browser_type_launch_args)
    yield browser_instance
    browser_instance.close()


def setup_browser_session(
    live_server,
    sample_user: AbstractBaseUser,
    team_with_business_plan,
) -> dict[str, Any]:
    django_client = Client()
    setup_authenticated_client_session(django_client, team_with_business_plan, sample_user)

    session = django_client.session
    session["current_team"]["has_completed_wizard"] = True
    session.save()

    return {
        "name": "sessionid",
        "value": session.session_key,
        "domain": urlparse(live_server.url).hostname,
        "path": "/",
        "httpOnly": True,
        "secure": False,
        "sameSite": "Lax",
    }


@pytest.fixture
def browser_context(
    browser: Browser,
    live_server,
    sample_user: AbstractBaseUser,
    team_with_business_plan,
) -> Generator[BrowserContext, Any, None]:
    context = browser.new_context(
        base_url=live_server.url,
        viewport={"width": BROWSER_WIDTH, "height": BROWSER_HEIGHT},
        device_scale_factor=1,
        reduced_motion="reduce",
    )

    session_cookie = setup_browser_session(live_server, sample_user, team_with_business_plan)
    context.add_cookies([session_cookie])

    yield context

    context.close()


@pytest.fixture
def authenticated_page(
    browser_context: BrowserContext,
) -> Generator[Page, Any, None]:
    page_instance = browser_context.new_page()
    yield page_instance
    page_instance.close()


class SnapshotMixin:
    def __init__(self, test_name: str) -> None:
        self.test_name = test_name

    def assert_screenshot(
        self,
        new_image_path: str | Any,
        original_image_path: str | Any,
        threshold: float = 0.005,  # (0.5%) Ideally 0.0, but we have to run tests through Docker environment
    ) -> None:
        _assert_screenshot(new_image_path, original_image_path, threshold)

    def get_or_create_baseline_screenshot(self, page: Page, width: int) -> Any:
        return _get_or_create_baseline_screenshot(page, self.test_name, width)

    def take_screenshot(self, page: Page, width: int) -> Any:
        return _take_screenshot(page, self.test_name, width)


@pytest.fixture
def snapshot(request: pytest.FixtureRequest) -> SnapshotMixin:
    return SnapshotMixin(request.node.name)
