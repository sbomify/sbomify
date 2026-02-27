from pathlib import Path
from typing import Any, Generator
from urllib.parse import urlparse

import pytest
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from playwright.sync_api import Browser, BrowserContext, Locator, Page, Playwright, Route, sync_playwright

from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    setup_authenticated_client_session,
    team_with_business_plan,  # noqa: F401
)
from sbomify.apps.sboms.models import SBOM, Component, Product, ProductProject, Project, ProjectComponent
from sbomify.apps.teams.models import Member, Team

RECORDING_WIDTH = 1280
RECORDING_HEIGHT = 720
OUTPUT_DIR = Path(__file__).parent / "output"
CLICK_INDICATOR_JS = Path(__file__).parent / "click_indicator.js"
LOGO_SVG = Path(__file__).parent.parent / "sbomify" / "static" / "img" / "logo-circle.svg"

# Match the app's dark-mode background so the recording never flashes white.
APP_BG_COLOR = "#0A0A23"

# Splash screen shown while the first real page loads.  The logo SVG is read
# once at import time and embedded directly in the HTML.  Force the SVG to
# scale within its container by replacing the hardcoded dimensions.
_logo_svg_content = (
    LOGO_SVG.read_text().replace('width="257" height="257"', 'width="100%" height="100%"') if LOGO_SVG.exists() else ""
)
SPLASH_HTML = f"""\
<html style="background:{APP_BG_COLOR}">
<body style="margin:0;display:flex;justify-content:center;align-items:center;
             min-height:100vh;background:{APP_BG_COLOR}">
  <div style="opacity:0.35;width:120px;height:120px">
    {_logo_svg_content}
  </div>
</body>
</html>"""


@pytest.fixture(autouse=True)
def disable_billing(settings) -> None:
    """Disable Stripe billing so screencasts don't hit payment APIs."""
    settings.BILLING = False


def pace(page: Page, ms: int = 600) -> None:
    """Pause for a natural beat between actions."""
    page.wait_for_timeout(ms)


def hover_and_click(page: Page, locator: Locator, pause_ms: int = 250) -> None:
    """Move cursor visibly to the element center, pause, then click.

    This ensures the cursor dot and click ripple are captured by the video
    encoder — without the pause Playwright clicks happen in a single frame.
    """
    box = locator.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(pause_ms)
    locator.click()


def type_text(locator: Locator, text: str, delay: int = 80) -> None:
    """Type text character-by-character for a human-like feel."""
    locator.press_sequentially(text, delay=delay)


def rewrite_localhost_urls(page: Page) -> None:
    """Replace localhost URLs in the visible DOM with app.sbomify.com.

    Used in screencasts where the trust center public URL or CNAME target
    would otherwise show the test server address.
    """
    page.evaluate("""() => {
        const walk = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                node.textContent = node.textContent
                    .replace(/http:\\/\\/localhost:\\d+/g, 'https://app.sbomify.com')
                    .replace(/\\blocalhost\\b/g, 'app.sbomify.com');
            }
            for (const child of node.childNodes) walk(child);
        };
        walk(document.body);
    }""")


# ---------------------------------------------------------------------------
# Reusable navigation sequences
# ---------------------------------------------------------------------------


def mock_vuln_trends(page: Page) -> None:
    """Intercept the vulnerability-trends HTMX endpoint with realistic mock data."""
    page.route(
        "**/vulnerability-trends/**",
        lambda route: route.fulfill(status=200, content_type="text/html", body=MOCK_VULN_TRENDS_HTML),
    )


def mock_vuln_trends_with_flag(page: Page) -> dict[str, bool]:
    """Like mock_vuln_trends but returns a flag dict to toggle the response.

    Before the flag is set the mock returns realistic data; after it returns
    an empty div.  Useful when the workspace/account is deleted mid-recording.
    """
    deleted = {"value": False}

    def _handler(route: Route) -> None:
        if deleted["value"]:
            route.fulfill(status=200, content_type="text/html", body="<div></div>")
        else:
            route.fulfill(status=200, content_type="text/html", body=MOCK_VULN_TRENDS_HTML)

    page.route("**/vulnerability-trends/**", _handler)
    return deleted


def start_on_dashboard(page: Page, pause_ms: int = 1500) -> None:
    """Navigate to the dashboard and wait for it to load."""
    page.goto("/dashboard")
    page.wait_for_load_state("networkidle")
    pace(page, pause_ms)


def navigate_to_settings(page: Page) -> None:
    """Click the sidebar Settings link and wait for the page to load."""
    settings_link = page.get_by_role("link", name="Settings")
    hover_and_click(page, settings_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_components(page: Page) -> None:
    """Click the sidebar Components link and wait for the page to load."""
    components_link = page.get_by_role("link", name="Components")
    hover_and_click(page, components_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_projects(page: Page) -> None:
    """Click the sidebar Projects link and wait for the page to load."""
    projects_link = page.get_by_role("link", name="Projects")
    hover_and_click(page, projects_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_products(page: Page) -> None:
    """Click the sidebar Products link and wait for the page to load."""
    products_link = page.get_by_role("link", name="Products")
    hover_and_click(page, products_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_releases(page: Page) -> None:
    """Click the sidebar Releases link and wait for the page to load."""
    releases_link = page.get_by_role("link", name="Releases")
    hover_and_click(page, releases_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_trust_center_tab(page: Page) -> None:
    """Navigate to Settings, then click the Trust Center tab."""
    navigate_to_settings(page)
    trust_center_tab = page.locator("a[data-tab='trust-center']")
    hover_and_click(page, trust_center_tab)
    pace(page, 800)


# ---------------------------------------------------------------------------
# Mock HTML for the vulnerability-trends HTMX widget
# ---------------------------------------------------------------------------

MOCK_VULN_TRENDS_HTML = """\
<div class="p-6"
     x-cloak
     x-data="{ chartInstance: null, activeChart: 'timeline' }"
     x-init="$nextTick(() => { initVulnerabilityChart($el) })">
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div class="flex items-center gap-2">
            <i class="fas fa-shield-alt text-primary"></i>
            <h4 class="text-lg font-semibold text-text m-0">Vulnerability Trends</h4>
        </div>
        <div class="flex flex-wrap items-center gap-4">
            <div class="flex items-center gap-2">
                <label class="text-xs text-text-muted uppercase tracking-wider">Product</label>
                <select class="tw-form-input w-auto py-1.5 text-sm" disabled>
                    <option>All Products</option>
                </select>
            </div>
            <div class="flex items-center gap-2">
                <label class="text-xs text-text-muted uppercase tracking-wider">Time Range</label>
                <select class="tw-form-input w-auto py-1.5 text-sm" disabled>
                    <option>30 Days</option>
                </select>
            </div>
        </div>
    </div>

    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
        <div class="flex items-center gap-3 p-3 rounded-lg bg-primary/5 border border-primary/10">
            <div class="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-bug text-primary"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-text">47</span>
                <span class="block text-xs text-text-muted">Total</span>
            </div>
        </div>
        <div class="flex items-center gap-3 p-3 rounded-lg bg-red-500/5 border border-red-500/10">
            <div class="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-exclamation-circle text-red-500"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-red-600">3</span>
                <span class="block text-xs text-text-muted">Critical</span>
            </div>
        </div>
        <div class="flex items-center gap-3 p-3 rounded-lg bg-orange-500/5 border border-orange-500/10">
            <div class="w-10 h-10 rounded-full bg-orange-500/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-exclamation-triangle text-orange-500"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-orange-600">8</span>
                <span class="block text-xs text-text-muted">High</span>
            </div>
        </div>
        <div class="flex items-center gap-3 p-3 rounded-lg bg-yellow-500/5 border border-yellow-500/10">
            <div class="w-10 h-10 rounded-full bg-yellow-500/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-minus-circle text-yellow-600"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-yellow-700">15</span>
                <span class="block text-xs text-text-muted">Medium</span>
            </div>
        </div>
        <div class="flex items-center gap-3 p-3 rounded-lg bg-cyan-500/5 border border-cyan-500/10">
            <div class="w-10 h-10 rounded-full bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-info-circle text-cyan-500"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-cyan-600">21</span>
                <span class="block text-xs text-text-muted">Low</span>
            </div>
        </div>
    </div>

    <div class="flex flex-col items-center mb-4">
        <div class="inline-flex rounded-lg border border-border overflow-hidden" role="group">
            <button type="button"
                    class="px-4 py-2 text-sm font-medium transition-colors"
                    :class="activeChart === 'timeline' ? 'bg-primary text-white' : 'bg-surface text-text hover:bg-background'">
                <i class="fas fa-chart-line mr-1"></i>Timeline
            </button>
            <button type="button"
                    class="px-4 py-2 text-sm font-medium border-l border-border transition-colors"
                    :class="activeChart === 'severity' ? 'bg-primary text-white' : 'bg-surface text-text hover:bg-background'">
                <i class="fas fa-chart-bar mr-1"></i>Severity
            </button>
            <button type="button"
                    class="px-4 py-2 text-sm font-medium border-l border-border transition-colors"
                    :class="activeChart === 'providers' ? 'bg-primary text-white' : 'bg-surface text-text hover:bg-background'">
                <i class="fas fa-chart-pie mr-1"></i>Providers
            </button>
        </div>
    </div>

    <div class="h-[300px] mb-6">
        <canvas class="vulnerability-chart-canvas"
                data-labels='["Jan 27","Jan 29","Jan 31","Feb 2","Feb 4","Feb 6","Feb 8","Feb 10","Feb 12","Feb 14","Feb 16","Feb 18","Feb 20","Feb 22","Feb 24"]'
                data-critical='[1,2,1,2,1,3,2,3,2,2,3,2,3,3,3]'
                data-high='[3,4,3,5,4,5,6,5,7,6,7,6,8,7,8]'
                data-medium='[8,7,9,8,10,9,11,10,12,11,13,12,14,13,15]'
                data-low='[12,11,13,12,14,15,16,17,18,17,19,18,20,19,21]'
                data-severity-labels='["Critical","High","Medium","Low"]'
                data-severity-values='[3,8,15,21]'
                data-provider-labels='["osv","dependency_track"]'
                data-provider-values='[28,19]'></canvas>
    </div>
</div>
"""


@pytest.fixture(scope="session")
def playwright() -> Generator[Playwright, Any, None]:
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Generator[Browser, Any, None]:
    browser_instance = playwright.chromium.connect_over_cdp(settings.PLAYWRIGHT_CDP_ENDPOINT)
    yield browser_instance
    browser_instance.close()


@pytest.fixture
def browser_base_url(live_server) -> str:
    original_hostname = urlparse(live_server.url).hostname
    return live_server.url.replace(
        original_hostname,
        getattr(settings, "PLAYWRIGHT_DJANGO_HOST", original_hostname),
    )


@pytest.fixture
def deletable_team(
    sample_user: AbstractBaseUser,
    team_with_business_plan: Team,
) -> Team:
    """Unmark the team as default so the delete button is enabled."""
    Member.objects.filter(user=sample_user, team=team_with_business_plan).update(is_default_team=False)
    return team_with_business_plan


# ---------------------------------------------------------------------------
# ORM fixtures — pre-create the Pied Piper hierarchy for screencasts that
# need it as a precondition rather than the thing being demonstrated.
# ---------------------------------------------------------------------------

PIED_PIPER_COMPONENTS = [
    "Compression Core Library",
    "Web Dashboard",
    "REST API Service",
    "Data Pipeline Worker",
]

PIED_PIPER_PROJECTS = {
    "Pied Piper Frontend": ["Web Dashboard"],
    "Pied Piper Backend": ["Compression Core Library", "REST API Service", "Data Pipeline Worker"],
}

PIED_PIPER_PRODUCT_NAME = "Pied Piper Compression Engine"


@pytest.fixture
def pied_piper_product(deletable_team: Team) -> dict:
    """Create full Pied Piper hierarchy via ORM (4 components, 2 projects, 1 product).

    Returns dict with keys: product, projects (dict), components (dict).
    """
    team = deletable_team

    # Components
    components = {}
    for name in PIED_PIPER_COMPONENTS:
        components[name] = Component.objects.create(team=team, name=name)

    # Projects + assign components
    projects = {}
    for proj_name, comp_names in PIED_PIPER_PROJECTS.items():
        project = Project.objects.create(team=team, name=proj_name)
        for comp_name in comp_names:
            ProjectComponent.objects.create(project=project, component=components[comp_name])
        projects[proj_name] = project

    # Product + assign projects
    product = Product.objects.create(
        team=team,
        name=PIED_PIPER_PRODUCT_NAME,
        description="Middle-out compression platform for enterprise data optimization",
    )
    for project in projects.values():
        ProductProject.objects.create(product=product, project=project)

    return {"product": product, "projects": projects, "components": components}


@pytest.fixture
def pied_piper_with_sboms(pied_piper_product: dict) -> dict:
    """Extend pied_piper_product with a CycloneDX SBOM record per component.

    Returns same dict plus 'sboms' key.
    Note: creating SBOMs triggers a signal that auto-creates a 'latest' Release.
    """
    sboms = {}
    for name, component in pied_piper_product["components"].items():
        sbom = SBOM.objects.create(
            name=f"com.piedpiper/{component.name.lower().replace(' ', '-')}",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename=f"{component.name.lower().replace(' ', '-')}.json",
            source="api",
            component=component,
        )
        sboms[name] = sbom

    return {**pied_piper_product, "sboms": sboms}


def setup_browser_session(
    browser_base_url: str,
    sample_user: AbstractBaseUser,
    team: Team,
) -> dict[str, Any]:
    django_client = Client()
    setup_authenticated_client_session(django_client, team, sample_user)

    session = django_client.session
    session["current_team"]["has_completed_wizard"] = True
    session["current_team"]["billing_plan"] = team.billing_plan
    session.save()

    return {
        "name": "sessionid",
        "value": session.session_key,
        "domain": urlparse(browser_base_url).hostname,
        "path": "/",
        "httpOnly": True,
        "secure": False,
        "sameSite": "Lax",
    }


@pytest.fixture
def recording_context(
    browser: Browser,
    browser_base_url: str,
    sample_user: AbstractBaseUser,
    deletable_team: Team,
) -> Generator[BrowserContext, Any, None]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    context = browser.new_context(
        base_url=browser_base_url,
        viewport={"width": RECORDING_WIDTH, "height": RECORDING_HEIGHT},
        device_scale_factor=1,
        record_video_dir=str(OUTPUT_DIR),
        record_video_size={"width": RECORDING_WIDTH, "height": RECORDING_HEIGHT},
    )

    # Prevent white flash — set background color before page content loads
    context.add_init_script(f"document.documentElement.style.backgroundColor = '{APP_BG_COLOR}';")

    # Show a cursor dot + click ripple in the recording.
    # Read the file content explicitly (path= can fail with remote CDP).
    click_js = CLICK_INDICATOR_JS.read_text()
    context.add_init_script(click_js)

    session_cookie = setup_browser_session(browser_base_url, sample_user, deletable_team)
    context.add_cookies([session_cookie])

    yield context

    context.close()


@pytest.fixture
def recording_page(
    request: pytest.FixtureRequest,
    recording_context: BrowserContext,
) -> Generator[Page, Any, None]:
    page = recording_context.new_page()

    # Replace the white about:blank with a branded splash screen.  This is
    # visible while the first real navigation loads.
    page.set_content(SPLASH_HTML, wait_until="commit")

    yield page

    # Grab the video handle, close the page (finalizes recording),
    # then save to a meaningful filename.
    video = page.video
    page.close()

    final_path = OUTPUT_DIR / f"{request.node.name}.webm"
    video.save_as(str(final_path))
