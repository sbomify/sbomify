"""Keycloak URL settings are read from the environment.

Each case imports ``sbomify.settings`` in a subprocess with a controlled
environment: the in-process settings were evaluated once at startup, and
``override_settings`` would only prove the view reads a value the test itself
put there. That is how ``KEYCLOAK_PUBLIC_URL`` went unset in production while
the logout tests passed.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

SERVER_URL = "http://keycloak.internal:8080/"


def _public_url(env: dict[str, str]) -> str:
    child_env = {k: v for k, v in os.environ.items() if k != "KEYCLOAK_PUBLIC_URL"}
    child_env.update(env)
    result = subprocess.run(
        [sys.executable, "-c", "import sbomify.settings as s; print(s.KEYCLOAK_PUBLIC_URL)"],
        capture_output=True,
        text=True,
        env=child_env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_public_url_read_from_environment() -> None:
    env = {"KEYCLOAK_SERVER_URL": SERVER_URL, "KEYCLOAK_PUBLIC_URL": "https://sso.example.com/"}
    assert _public_url(env) == "https://sso.example.com/"


@pytest.mark.parametrize("public_url", [None, ""], ids=["unset", "empty"])
def test_public_url_falls_back_to_server_url(public_url: str | None) -> None:
    env = {"KEYCLOAK_SERVER_URL": SERVER_URL}
    if public_url is not None:
        env["KEYCLOAK_PUBLIC_URL"] = public_url
    assert _public_url(env) == SERVER_URL


def _setting(name: str, env: dict[str, str]) -> str:
    child_env = {k: v for k, v in os.environ.items() if not k.startswith(("KEYCLOAK_", "OIDC_"))}
    child_env.update(env)
    result = subprocess.run(
        [sys.executable, "-c", f"import sbomify.settings as s; print(repr(s.{name}))"],
        capture_output=True,
        text=True,
        env=child_env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


PROVIDER_URL = "SOCIALACCOUNT_PROVIDERS['openid_connect']['APPS'][0]['settings']['server_url']"


@pytest.mark.parametrize("discovery_url", [None, ""], ids=["unset", "empty"])
def test_discovery_url_defaults_to_keycloak_realm(discovery_url: str | None) -> None:
    env = {"KEYCLOAK_SERVER_URL": SERVER_URL, "KEYCLOAK_REALM": "acme"}
    if discovery_url is not None:
        env["OIDC_DISCOVERY_URL"] = discovery_url
    expected = f"{SERVER_URL}realms/acme/.well-known/openid-configuration"
    assert _setting(PROVIDER_URL, env) == repr(expected)
    assert _setting("OIDC_DISCOVERY_URL", env) == repr("")


def test_discovery_url_override_reaches_provider() -> None:
    url = "https://tenant.auth0.com/.well-known/openid-configuration"
    env = {"KEYCLOAK_SERVER_URL": SERVER_URL, "OIDC_DISCOVERY_URL": url}
    assert _setting(PROVIDER_URL, env) == repr(url)


def test_logout_url_read_from_environment() -> None:
    url = "https://tenant.auth0.com/oidc/logout"
    assert _setting("OIDC_LOGOUT_URL", {"OIDC_LOGOUT_URL": url}) == repr(url)
    assert _setting("OIDC_LOGOUT_URL", {}) == repr("")


APP = "SOCIALACCOUNT_PROVIDERS['openid_connect']['APPS'][0]"


@pytest.mark.parametrize(
    "env,client_id,secret",
    [
        ({"KEYCLOAK_CLIENT_ID": "kc", "KEYCLOAK_CLIENT_SECRET": "kc-secret"}, "kc", "kc-secret"),
        ({"OIDC_CLIENT_ID": "okta", "OIDC_CLIENT_SECRET": "okta-secret"}, "okta", "okta-secret"),
        (
            {"KEYCLOAK_CLIENT_ID": "kc", "KEYCLOAK_CLIENT_SECRET": "kc-secret", "OIDC_CLIENT_ID": "okta"},
            "okta",
            "kc-secret",
        ),
        ({"KEYCLOAK_CLIENT_ID": "kc", "OIDC_CLIENT_ID": "", "OIDC_CLIENT_SECRET": ""}, "kc", ""),
        ({}, "sbomify", ""),
    ],
    ids=["keycloak-names", "oidc-names", "oidc-wins-per-variable", "empty-oidc-falls-back", "defaults"],
)
def test_client_credentials_accept_both_names(env: dict[str, str], client_id: str, secret: str) -> None:
    assert _setting("KEYCLOAK_CLIENT_ID", env) == repr(client_id)
    assert _setting("KEYCLOAK_CLIENT_SECRET", env) == repr(secret)
    assert _setting(f"{APP}['client_id']", env) == repr(client_id)
    assert _setting(f"{APP}['secret']", env) == repr(secret)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),
        ("", False),
        ("false", False),
        ("true", True),
        ("True", True),
        ("1", True),
        ("example.com", ["example.com"]),
        (" Example.com, @corp.example.org ,", ["example.com", "corp.example.org"]),
    ],
)
def test_trust_email_reaches_allauth(value: str | None, expected: bool | list[str]) -> None:
    env = {} if value is None else {"OIDC_TRUST_EMAIL": value}
    assert _setting(f"{APP}['settings']['verified_email']", env) == repr(expected)
