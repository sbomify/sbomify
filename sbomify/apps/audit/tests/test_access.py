"""Who may read the audit log, and the shapes it is read in."""

from __future__ import annotations

import csv
import io
import json

import pytest
from django.urls import reverse

from sbomify.apps.audit.recorder import Target, record
from sbomify.apps.core.tests.shared_fixtures import get_api_headers, setup_authenticated_client_session
from sbomify.apps.teams.models import Member
from sbomify.apps.teams.settings_tabs import visible_tabs

from .conftest import events

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def seeded(enterprise, sample_user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        record("product.created", workspace=enterprise, actor=sample_user, target=Target("product", "p1", "Rocket"))
        record("member.deleted", workspace=enterprise, actor=sample_user, target=Target("member", "m1", "=cmd|x"))
    return enterprise


def _events_url(workspace, **params) -> str:
    url = reverse("audit:events", kwargs={"workspace_key": workspace.key})
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{url}?{query}" if query else url


def test_tab_is_for_owners_and_admins_only():
    keys = lambda role: {tab.key for tab in visible_tabs(role, billing_enabled=True)}  # noqa: E731
    assert "audit-log" in keys("owner")
    assert "audit-log" in keys("admin")
    assert "audit-log" not in keys("member")
    assert "audit-log" not in keys("operator")


def test_owner_sees_events(owner_client, seeded):
    response = owner_client.get(_events_url(seeded), **HX)
    assert response.status_code == 200
    body = response.content.decode()
    assert "Rocket" in body
    assert "Product created" in body
    assert "Member removed" in body


def test_filters_narrow_the_list(owner_client, seeded):
    body = owner_client.get(_events_url(seeded, action="member"), **HX).content.decode()
    assert "Member removed" in body
    assert "Product created" not in body


def test_member_cannot_read(client, seeded, member_user):
    setup_authenticated_client_session(client, seeded, member_user)
    response = client.get(_events_url(seeded), **HX)
    assert response.status_code == 403
    export = client.get(reverse("audit:export", kwargs={"workspace_key": seeded.key}))
    assert export.status_code == 403


def test_business_plan_is_offered_the_upgrade(client, team_with_business_plan, sample_user):
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)
    response = client.get(_events_url(team_with_business_plan), **HX)
    assert response.status_code == 200
    assert "Available on Enterprise" in response.content.decode()


def test_csv_export_is_complete_safe_and_audited(owner_client, seeded, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = owner_client.get(reverse("audit:export", kwargs={"workspace_key": seeded.key}))
        content = b"".join(response.streaming_content).decode()
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "no-store" in response["Cache-Control"]

    rows = list(csv.DictReader(io.StringIO(content)))
    assert {row["action"] for row in rows} == {"product.created", "member.deleted"}
    # A value a spreadsheet would run as a formula is written as text.
    assert next(r for r in rows if r["action"] == "member.deleted")["target_label"].startswith("'")

    [exported] = events(seeded, action="audit_log.exported")
    assert exported.metadata["format"] == "csv"


def test_api_lists_with_a_cursor(client, seeded, make_token):
    headers = get_api_headers(make_token())
    url = reverse("api-2:list_audit_events", kwargs={"workspace_key": seeded.key})
    first = client.get(f"{url}?limit=1", **headers).json()
    assert len(first["items"]) == 1
    assert first["items"][0]["action"] == "member.deleted"
    assert first["next_cursor"] is not None

    second = client.get(f"{url}?limit=1&cursor={first['next_cursor']}", **headers).json()
    assert [item["action"] for item in second["items"]] == ["product.created"]
    assert second["next_cursor"] is None


def test_api_jsonl_export(client, seeded, make_token):
    url = reverse("api-2:export_audit_events", kwargs={"workspace_key": seeded.key})
    response = client.get(f"{url}?format=jsonl&action=product", **get_api_headers(make_token()))
    assert response.status_code == 200
    lines = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
    assert [line["action"] for line in lines] == ["product.created"]
    assert lines[0]["target"]["label"] == "Rocket"


def test_api_refuses_a_member_token(client, seeded, member_user, make_token):
    url = reverse("api-2:list_audit_events", kwargs={"workspace_key": seeded.key})
    response = client.get(url, **get_api_headers(make_token(user=member_user)))
    assert response.status_code == 403


def test_api_refuses_a_token_scoped_away_from_the_audit_log(client, seeded, make_token):
    url = reverse("api-2:list_audit_events", kwargs={"workspace_key": seeded.key})
    response = client.get(url, **get_api_headers(make_token(["product:read"])))
    assert response.status_code == 403


def test_api_on_business_plan_is_payment_required(client, team_with_business_plan, sample_user):
    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.access_tokens.utils import create_personal_access_token

    token = AccessToken.objects.create(
        user=sample_user,
        encoded_token=create_personal_access_token(sample_user),
        team=team_with_business_plan,
        description="t",
    )
    url = reverse("api-2:list_audit_events", kwargs={"workspace_key": team_with_business_plan.key})
    assert client.get(url, **get_api_headers(token)).status_code == 402


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("get", "api-2:list_audit_events"),
        ("get", "api-2:export_audit_events"),
        ("get", "api-2:get_audit_retention"),
        ("put", "api-2:set_audit_retention"),
    ],
)
def test_api_does_not_tell_an_outsider_which_plan_a_workspace_is_on(
    client, django_user_model, enterprise, team_with_business_plan, method, route
):
    outsider = django_user_model.objects.create_user(username="outsider", email="outsider@example.com", password="x")
    client.force_login(outsider)

    def status(workspace) -> int:
        url = reverse(route, kwargs={"workspace_key": workspace.key})
        body = json.dumps({"retention_days": 90}) if method == "put" else None
        return getattr(client, method)(url, body, content_type="application/json").status_code

    assert {"enterprise": status(enterprise), "business": status(team_with_business_plan)} == {
        "enterprise": 403,
        "business": 403,
    }


def test_api_refuses_a_plain_member_before_mentioning_the_plan(client, django_user_model, team_with_business_plan):
    member = django_user_model.objects.create_user(username="bizmember", email="bizmember@example.com", password="x")
    Member.objects.create(team=team_with_business_plan, user=member, role="member")
    client.force_login(member)
    url = reverse("api-2:list_audit_events", kwargs={"workspace_key": team_with_business_plan.key})
    assert client.get(url).status_code == 403


@pytest.mark.parametrize(("days", "status"), [(29, 422), (3651, 422), (90, 200)])
def test_api_retention_bounds(client, enterprise, make_token, days, status):
    url = reverse("api-2:set_audit_retention", kwargs={"workspace_key": enterprise.key})
    response = client.put(
        url, json.dumps({"retention_days": days}), content_type="application/json", **get_api_headers(make_token())
    )
    assert response.status_code == status
    enterprise.refresh_from_db()
    assert enterprise.audit_log_retention_days == (days if status == 200 else 365)


def test_retention_change_is_itself_audited(owner_client, enterprise, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = owner_client.post(
            reverse("audit:retention", kwargs={"workspace_key": enterprise.key}), {"retention_days": 730}
        )
    assert response.status_code == 200
    [event] = events(enterprise, action="workspace.updated")
    assert event.metadata["changes"]["audit_log_retention_days"] == {"from": 365, "to": 730}


def test_multi_word_target_types_read_as_words(owner_client, enterprise, sample_user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        record("access_token.created", workspace=enterprise, actor=sample_user, target=Target("access_token", "1", "CI"))
    body = owner_client.get(_events_url(enterprise), **HX).content.decode()
    assert "Access token" in body
    assert "Accesstoken" not in body


@pytest.mark.asyncio
async def test_export_streams_under_asgi():
    from sbomify.apps.audit.services import batched_async

    lines = iter(f"{n}\n" for n in range(1200))
    chunks = [chunk async for chunk in batched_async(lines)]
    assert len(chunks) == 3
    assert "".join(chunks).count("\n") == 1200
