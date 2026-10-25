"""The overview repaints on socket messages, from a snapshot that reflects them.

The snapshot is cached for a minute. A refresh asked for by a socket message is
about a change the cached copy cannot reflect yet, so that request rebuilds it.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.services import dashboard_page
from sbomify.apps.core.services.dashboard_page import build_dashboard_context
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace(sample_team_with_owner_member: Member):
    team = sample_team_with_owner_member.team
    # The overview redirects into plan selection until the workspace has one.
    team.has_selected_billing_plan = True
    team.save(update_fields=["has_selected_billing_plan"])
    component = Component.objects.create(name="first", team=team)
    SBOM.objects.create(name="s", component=component, format="cyclonedx")
    cache.clear()
    return team


def test_fresh_rebuilds_a_cached_snapshot_and_stores_it(workspace) -> None:
    before = build_dashboard_context(workspace.id).value
    Component.objects.create(name="added later", team=workspace)

    assert build_dashboard_context(workspace.id).value == before
    fresh = build_dashboard_context(workspace.id, fresh=True).value

    assert fresh != before
    assert build_dashboard_context(workspace.id).value == fresh


def _get(workspace, user, **headers):
    client = Client()
    setup_authenticated_client_session(client, workspace, user)
    response = client.get(reverse("core:dashboard"), **headers)
    assert response.status_code == 200
    return response


def test_a_live_refresh_reads_a_fresh_snapshot(workspace, sample_user, mocker) -> None:
    build = mocker.spy(dashboard_page, "build_dashboard_context")

    _get(workspace, sample_user, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="overview-content")

    assert build.call_args.kwargs == {"fresh": True}


def test_an_ordinary_load_uses_the_cache(workspace, sample_user, mocker) -> None:
    build = mocker.spy(dashboard_page, "build_dashboard_context")

    _get(workspace, sample_user)

    assert build.call_args.kwargs == {"fresh": False}


def test_the_overview_listens_and_keeps_the_triage_host_outside_what_it_replaces(workspace, sample_user) -> None:
    html = _get(workspace, sample_user).content.decode()

    frame = html[html.index('id="overview-content"') :]
    assert 'hx-trigger="refresh-overview from:body"' in frame
    assert 'hx-select="#overview-content"' in frame
    assert "'assessment_complete'" in frame and "'resync'" in frame
    # A refresh swaps the frame for the server's copy, in which the host is
    # empty, so the host has to sit after it to keep an open dialog.
    assert html.count('id="overview-content"') == 1
    assert html.count('id="priority-triage-host"') <= 1
