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
