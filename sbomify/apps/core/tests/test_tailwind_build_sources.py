"""The production CSS build compiles only the classes it can see in the folders the Dockerfile copies."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
APPS = REPO_ROOT / "sbomify" / "apps"


def _css_build_stage() -> str:
    # The dev frontend mounts ./sbomify over its copies, so only the production stage matters.
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    return dockerfile.split(" AS js-build-prod\n", 1)[1].split("\nFROM ", 1)[0]


def test_the_css_build_copies_every_folder_tailwind_scans():
    """Tailwind's @source globs cover every app's templates and js. A folder the
    js-build-prod stage leaves out compiles none of its utilities, and nothing
    fails: the class is simply absent from the production stylesheet."""
    copies = _css_build_stage()
    missing = [
        str(folder.relative_to(REPO_ROOT))
        for kind in ("templates", "js")
        for folder in sorted(APPS.glob(f"*/{kind}"))
        if f"COPY {folder.relative_to(REPO_ROOT)}/ " not in copies
    ]
    assert missing == []
