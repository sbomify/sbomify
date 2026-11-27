"""A provider spec for exercising the authorization-code flow and its refresh.

Vanta connects with client credentials and Slack's token never expires, so no
registered provider walks the whole of the consent-and-refresh path. This one
is Vanta's spec on that path, rotating its refresh token on every use, which
is the hardest case the refresh code has to get right. The deployment
settings it reads come from the ``rotating_credentials`` fixture.
"""

from __future__ import annotations

from dataclasses import replace

from sbomify.apps.integrations.providers.vanta import VANTA

ROTATING = replace(
    VANTA,
    grant="authorization_code",
    authorize_url_setting="ROTATING_AUTHORIZE_URL",
    client_id_setting="ROTATING_CLIENT_ID",
    client_credential_setting="ROTATING_CLIENT_SECRET",
)
