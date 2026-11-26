from __future__ import annotations

import pytest
from django.db import connection

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.audit.models import AuditEvent
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="the append-only guards are PostgreSQL triggers"
)


@pytest.fixture
def enterprise(team_with_enterprise_plan):
    return team_with_enterprise_plan


@pytest.fixture
def owner_client(client, enterprise, sample_user):
    setup_authenticated_client_session(client, enterprise, sample_user)
    return client


@pytest.fixture
def member_user(django_user_model, enterprise):
    user = django_user_model.objects.create_user(username="plainmember", email="member@example.com", password="x")
    Member.objects.create(team=enterprise, user=user, role="member")
    return user


@pytest.fixture
def make_token(sample_user, enterprise):
    def _make(scopes: list[str] | None = None, user=None) -> AccessToken:
        holder = user or sample_user
        return AccessToken.objects.create(
            user=holder,
            encoded_token=create_personal_access_token(holder),
            team=enterprise,
            scopes=scopes,
            description="audit test token",
        )

    return _make


def events(workspace, **filters) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(workspace_id=workspace.pk, **filters).order_by("id"))
