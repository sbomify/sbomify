import logging
import tempfile
from pathlib import Path

from diffimg import diff as diffimg_diff
from playwright.sync_api import Page

logger = logging.getLogger(__name__)

_E2E_DIR = Path(__file__).parent

BASELINE_DIR = _E2E_DIR / "__snapshots__"
DIFF_DIR = _E2E_DIR / "__diffs__"

BROWSER_WIDTH = 1920
BROWSER_HEIGHT = 1080


def diff_images(
    new_image_path: str | Path,
    original_image_path: str | Path,
    diff_img_file: str | Path,
) -> float:
    new_path = Path(new_image_path)
    if not new_path.exists():
        raise FileNotFoundError(f"New image not found: {new_path}")

    original_path = Path(original_image_path)
    if not original_path.exists():
        raise FileNotFoundError(f"Original image not found: {original_path}")

    diff_img_file = Path(diff_img_file)

    return diffimg_diff(
        new_path.as_posix(),
        original_path.as_posix(),
        diff_img_file=diff_img_file.as_posix(),
        ignore_alpha=True,
    )


def assert_screenshot(
    baseline_image_path: str | Path,
    current_image_path: str | Path,
    threshold: float = 0.0,
    delete_diff_images: bool = True,
) -> None:
    with tempfile.NamedTemporaryFile(
        dir=DIFF_DIR.as_posix(),
        prefix="screenshot-diff-",
        suffix=".jpg",
        delete=False,
    ) as tmp_file:
        diff_img_file = tmp_file.name

    image_diff = round(
        diff_images(
            baseline_image_path,
            current_image_path,
            diff_img_file=diff_img_file,
        ),
        3,
    )

    assert image_diff <= threshold, (
        f"Screenshots differ: {image_diff:.3%} different "
        f"(threshold: {threshold:.3%}). "
        f"See the image diff by: {diff_img_file}"
    )

    if delete_diff_images:
        Path(diff_img_file).unlink()
        Path(current_image_path).unlink()


def get_or_create_baseline_screenshot(page: Page, name: str, width: int) -> Path:
    baseline_path = BASELINE_DIR / f"{name}.jpg"

    if baseline_path.exists():
        return baseline_path

    return take_screenshot(page, name, width=width, path=baseline_path)


def take_screenshot(
    page: Page,
    name: str,
    width: int,
    path: Path | None = None,
    wait_timeout: float = 0.5,
) -> Path:
    page.set_viewport_size({"width": width, "height": BROWSER_HEIGHT})
    # Wait for the page height to be stable
    page.wait_for_timeout(int(wait_timeout * 1000))

    page.set_viewport_size({"width": width, "height": page.evaluate("document.body.parentNode.scrollHeight")})
    # Wait for the page height to be stable
    page.wait_for_timeout(int(wait_timeout * 1000))

    if path:
        output_path = path
    else:
        output_path = DIFF_DIR / f"{name}.jpg"

    page.screenshot(path=output_path.as_posix(), type="jpeg", full_page=True)

    page.set_viewport_size({"width": BROWSER_WIDTH, "height": BROWSER_HEIGHT})

    return output_path
