"""Record the OIDC trusted-publishing setup screencast.

Drives the full lifecycle:
    Dashboard → Components → open a component → scroll to the
    Trusted Publishers section → add a GitHub repository binding →
    expand the GitHub Actions workflow snippet → SIMULATE the
    Actions runner exchanging an OIDC JWT for a sbomify token →
    upload a CycloneDX SBOM with that short-lived token → reload
    the component page so the viewer sees the new SBOM land in the
    SBOMs table.

Prerequisite: ``pied_piper_with_sboms`` seeds a Component the
screencast can click into. The GitHub REST call that
``services.create_binding`` would normally make is patched (no
network), as is the JWKS lookup used by ``verify_github_oidc_token``
(so a locally-signed token verifies).
"""

from __future__ import annotations

import json
import time
from typing import Any

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client
from playwright.sync_api import Page

from conftest import (
    PIED_PIPER_COMPONENTS,
    auto_dismiss_toasts,
    dismiss_toasts,
    hover_and_click,
    mock_vuln_trends,
    navigate_to_components,
    pace,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.oidc.github_api import ResolvedRepository

DEMO_REPOSITORY = "acme/widget"
# Fictitious, fixed IDs so the recording shows the same "owner_id=… ·
# repo_id=…" subline every time — and so no real GitHub account/repo is
# embedded in the screencast. Deterministic values also keep the frame
# stable across re-records (real IDs would shift on transfer / rename).
_FAKE_OWNER_ID = 10000001
_FAKE_REPO_ID = 200000002

# Minimal CycloneDX 1.6 payload — same shape as the existing
# ``test_validate_cyclonedx_sbom_1_4`` test fixture, bumped to 1.6.
# Small enough to upload fast, valid enough to pass schema validation
# in the artifact endpoint.
_MINIMAL_CDX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.6",
    "version": 1,
    "metadata": {
        "component": {
            "type": "application",
            "name": "widget",
            "version": "1.0.0-oidc-demo",
        },
    },
}


@pytest.fixture
def mock_github_resolve(mocker):
    """Stub the GitHub REST lookup so the recording doesn't hit github.com.

    Returns a ``ResolvedRepository`` with deterministic immutable IDs.
    Patching at the ``services`` import site (not ``github_api``)
    matches the existing OIDC test suite — the service uses the
    symbol via ``from sbomify.apps.oidc.github_api import
    resolve_repository``, so the bound name lives in ``services``.
    """
    return mocker.patch(
        "sbomify.apps.oidc.services.resolve_repository",
        return_value=ResolvedRepository(
            repository=DEMO_REPOSITORY,
            repository_owner=DEMO_REPOSITORY.split("/")[0],
            repository_id=_FAKE_REPO_ID,
            repository_owner_id=_FAKE_OWNER_ID,
        ),
    )


# ---------------------------------------------------------------------------
# JWT-side fixtures duplicated from sbomify/apps/oidc/tests/conftest.py so
# the screencast doesn't depend on the test app's conftest being discoverable
# (pytest only picks one conftest per file; screencasts/conftest.py wins).
# ---------------------------------------------------------------------------


@pytest.fixture
def rsa_keypair() -> dict[str, Any]:
    """Fresh RSA keypair for signing the simulated GitHub OIDC JWT."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    def _b64(i: int) -> str:
        b = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "screencast-kid-1",
        "alg": "RS256",
        "use": "sig",
        "n": _b64(public_numbers.n),
        "e": _b64(public_numbers.e),
    }
    return {
        "private_pem": private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        "jwk": jwk,
    }


@pytest.fixture
def mock_github_jwks(mocker, rsa_keypair: dict[str, Any]) -> Any:
    """Patch the JWKS HTTP fetch so the synthetic JWT verifies."""
    from unittest.mock import MagicMock

    from django.core.cache import cache

    cache.delete("sbomify:trusted:oidc:github:jwks")
    cache.delete("sbomify:trusted:oidc:github:jwks:last_refresh")
    mock_response = MagicMock()
    mock_response.json.return_value = {"keys": [rsa_keypair["jwk"]]}
    mock_response.raise_for_status.return_value = None
    return mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=mock_response)


@pytest.fixture
def mock_sbom_s3(mocker) -> Any:
    """Stub the S3 client used by the CycloneDX upload endpoint.

    The test container has no MinIO reachable on ``test-s3.localhost``,
    so a real upload would 400 with a connection error. The screencast
    just needs the SBOM row to land so it appears in the SBOMs table —
    return a deterministic filename without making any network call.
    """
    fake_s3 = mocker.MagicMock()
    fake_s3.upload_sbom.return_value = "screencast_oidc_demo_" + DEMO_REPOSITORY.replace("/", "_") + ".json"
    return mocker.patch("sbomify.apps.sboms.apis.S3Client", return_value=fake_s3)


# ---------------------------------------------------------------------------
# On-screen narration overlay — tells the viewer which step of the
# "imagine a GitHub Actions runner doing this" sequence is happening,
# because the API calls themselves are invisible. All content is
# controlled by this script (no user input), but we still use
# ``textContent`` to set the dynamic parts and only DOM-construct the
# static structure — keeps automated security linters happy.
# ---------------------------------------------------------------------------


def show_overlay(page: Page, title: str, body_lines: list[str]) -> None:
    page.evaluate(
        """(payload) => {
            let el = document.getElementById('oidc-demo-overlay');
            if (!el) {
                el = document.createElement('div');
                el.id = 'oidc-demo-overlay';
                el.style.cssText = `
                    position: fixed; top: 64px; right: 16px; z-index: 10000;
                    min-width: 360px; max-width: 480px;
                    padding: 14px 18px;
                    background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%);
                    color: #fff; font-family: ui-sans-serif, system-ui, sans-serif;
                    box-shadow: 0 12px 32px rgba(0,0,0,0.35);
                    border-radius: 10px; border: 1px solid rgba(255,255,255,0.08);
                `;
                document.body.appendChild(el);
            }
            // Clear previous content
            while (el.firstChild) el.removeChild(el.firstChild);

            // Header row: icon + title
            const header = document.createElement('div');
            header.style.cssText = 'display:flex; align-items:center; gap:8px;' +
                ' font-weight:600; font-size:13px; margin-bottom:6px;' +
                ' letter-spacing:0.02em;';
            const icon = document.createElement('span');
            icon.style.cssText = 'font-size:16px;';
            icon.textContent = '\\uD83E\\uDD16';  // robot face
            const titleSpan = document.createElement('span');
            titleSpan.textContent = payload.title;
            header.appendChild(icon);
            header.appendChild(titleSpan);
            el.appendChild(header);

            // Body lines (each rendered as its own paragraph)
            for (const line of payload.body_lines) {
                const p = document.createElement('div');
                p.style.cssText = 'font-size:12px; font-family:ui-monospace, monospace;' +
                    ' opacity:0.92; line-height:1.5;';
                p.textContent = line;
                el.appendChild(p);
            }
        }""",
        {"title": title, "body_lines": body_lines},
    )


def hide_overlay(page: Page) -> None:
    page.evaluate("document.getElementById('oidc-demo-overlay')?.remove()")


@pytest.mark.django_db(transaction=True)
def oidc_trusted_publishing(
    recording_page: Page,
    pied_piper_with_sboms: dict,
    mock_github_resolve,
    mock_github_jwks,
    mock_sbom_s3,
    rsa_keypair: dict[str, Any],
) -> None:
    page = recording_page

    auto_dismiss_toasts(page)
    mock_vuln_trends(page)
    start_on_dashboard(page)

    # ── 1. Navigate to Components ────────────────────────────────────────
    navigate_to_components(page)

    # ── 2. Click into the first Pied Piper component ─────────────────────
    target_component_name = PIED_PIPER_COMPONENTS[0]
    component = pied_piper_with_sboms["components"][target_component_name]
    component_name = page.locator(f"span.text-text:text-is('{target_component_name}')")
    component_name.wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    hover_and_click(page, component_name)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 3. Scroll the Trusted Publishers section into view ───────────────
    section = page.locator("#trusted-publishers-section")
    section.wait_for(state="visible", timeout=15_000)
    section.scroll_into_view_if_needed()
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 4. Fill the repository field ─────────────────────────────────────
    repo_input = page.locator("#id_repository")
    repo_input.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, repo_input)
    pace(page, 300)
    type_text(repo_input, DEMO_REPOSITORY)
    pace(page, 800)

    # ── 5. Click "Add publisher" ─────────────────────────────────────────
    add_btn = page.locator("#trusted-publishers-section button[type='submit']:has-text('Add publisher')")
    hover_and_click(page, add_btn)

    # ── 6. Wait for the binding row to land + linger on the result ───────
    page.locator(f"#trusted-publishers-section table code:has-text('{DEMO_REPOSITORY}')").wait_for(
        state="visible", timeout=10_000
    )
    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    pace(page, 2000)

    # ── 7. Expand the workflow YAML so the viewer sees the contract ──────
    disclosure = page.locator("#trusted-publishers-section summary:has-text('Configure your GitHub Actions workflow')")
    disclosure.scroll_into_view_if_needed()
    pace(page, 600)
    hover_and_click(page, disclosure)
    pace(page, 2500)

    # ── 8. Simulate "GitHub Actions runs and uploads" ────────────────────
    # The screencast can't actually trigger a GitHub Actions job, so the
    # next three steps do what that runner would do — mint an OIDC JWT,
    # exchange it for a sbomify token, upload an SBOM — and surface an
    # on-screen overlay so the viewer sees each phase happen.

    show_overlay(
        page,
        "GitHub Actions runner (simulated)",
        [
            "Step 1 / 3 — minting GitHub OIDC JWT",
            f"audience: {settings.OIDC_GITHUB_AUDIENCE}",
        ],
    )
    pace(page, 2200)

    now = int(time.time())
    oidc_jwt = pyjwt.encode(
        {
            "iss": settings.OIDC_GITHUB_ISSUER,
            "aud": settings.OIDC_GITHUB_AUDIENCE,
            "iat": now,
            "exp": now + 300,
            "sub": f"repo:{DEMO_REPOSITORY}:ref:refs/heads/main",
            "repository": DEMO_REPOSITORY,
            "repository_owner": DEMO_REPOSITORY.split("/")[0],
            "repository_id": _FAKE_REPO_ID,
            "repository_owner_id": _FAKE_OWNER_ID,
            "ref": "refs/heads/main",
            "workflow_ref": f"{DEMO_REPOSITORY}/.github/workflows/sbom.yml@refs/heads/main",
        },
        rsa_keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": rsa_keypair["jwk"]["kid"]},
    )

    show_overlay(
        page,
        "GitHub Actions runner (simulated)",
        [
            "Step 2 / 3 — POST /api/v1/auth/oidc/github/exchange",
            "→ trading OIDC JWT for short-lived sbomify token",
        ],
    )
    pace(page, 1600)

    # Use Django's in-process test Client so the request doesn't have to
    # cross the docker network and trip the host-header middleware.
    # Functionally identical to what a real ``curl`` from a GitHub Actions
    # runner would do — same URL, same headers, same body shape.
    api_client = Client()
    exchange_resp = api_client.post(
        "/api/v1/auth/oidc/github/exchange",
        data=json.dumps({"component_id": component.id}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {oidc_jwt}",
    )
    assert exchange_resp.status_code == 200, f"Exchange failed: {exchange_resp.status_code} {exchange_resp.content!r}"
    sbomify_token = exchange_resp.json()["access_token"]

    show_overlay(
        page,
        "GitHub Actions runner (simulated)",
        [
            f"Step 3 / 3 — POST /api/v1/sboms/artifact/cyclonedx/{component.id}",
            "→ uploading CycloneDX SBOM with sbomify token",
        ],
    )
    pace(page, 1600)

    upload_resp = api_client.post(
        f"/api/v1/sboms/artifact/cyclonedx/{component.id}",
        data=json.dumps(_MINIMAL_CDX),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sbomify_token}",
    )
    assert upload_resp.status_code in (200, 201), f"Upload failed: {upload_resp.status_code} {upload_resp.content!r}"

    show_overlay(
        page,
        "Done",
        ["SBOM uploaded — reloading the component to show it landed."],
    )
    pace(page, 1800)

    # ── 9. Reload + scroll to the SBOMs table to reveal the new SBOM ─────
    hide_overlay(page)
    page.reload()
    page.wait_for_load_state("networkidle")
    auto_dismiss_toasts(page)
    pace(page, 1500)

    sboms_heading = page.locator("h4:has-text('SBOMs')").first
    sboms_heading.wait_for(state="visible", timeout=10_000)
    sboms_heading.scroll_into_view_if_needed()
    pace(page, 1000)

    # The newly-uploaded SBOM carries the metadata-supplied component name.
    new_sbom_row = page.locator("a:has-text('widget')").first
    new_sbom_row.wait_for(state="visible", timeout=10_000)
    pace(page, 3000)
