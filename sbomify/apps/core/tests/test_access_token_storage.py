"""A stored access token is a hash, and no form or log line carries a usable token."""

import hashlib
import logging
from collections.abc import Callable, Iterator
from importlib import import_module
from time import time
from types import SimpleNamespace

import jwt
import pytest
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import IntegrityError, connection, models, transaction
from django.test import Client, RequestFactory
from django.test.utils import isolate_apps
from django.urls import reverse

from sbomify.apps.access_tokens.admin import AccessTokenAdmin
from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import (
    TOKEN_TYPE_OIDC,
    TOKEN_TYPE_PAT,
    create_personal_access_token,
    get_user_and_token_record,
)
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.oidc.permissions import request_is_oidc_authed
from sbomify.apps.sboms.utils import make_download_token, verify_download_token
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _stored_values() -> list[str]:
    """Every value in the token table, read past the ORM."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM access_tokens")
        return [str(value) for row in cursor.fetchall() for value in row]


def _oidc_token(user: AbstractBaseUser) -> str:
    return create_personal_access_token(user, expires_at=time() + 900, token_type=TOKEN_TYPE_OIDC)


def _from_tokens_page(client: Client, member: Member) -> str:
    url = reverse("teams:team_tokens", kwargs={"team_key": member.team.key})
    return str(client.post(url, {"description": "CI"}).context["new_encoded_access_token"])


def _from_ci_dialog(client: Client, member: Member) -> str:
    url = reverse("teams:ci_token", kwargs={"team_key": member.team.key})
    return str(client.post(url).json()["token"])


def _from_repository_setup(client: Client, member: Member) -> str:
    url = reverse("core:repository_setup_token", kwargs={"workspace_key": member.team.key})
    return str(client.post(url).json()["token"])


@pytest.mark.parametrize("mint", [_from_tokens_page, _from_ci_dialog, _from_repository_setup])
def test_the_database_holds_the_token_hash_and_never_the_token(
    mint: Callable[[Client, Member], str], sample_team_with_owner_member: Member
) -> None:
    member = sample_team_with_owner_member
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)

    token = mint(client, member)

    stored = _stored_values()
    assert not any(token in value for value in stored)
    assert _sha256(token) in stored
    user, record = get_user_and_token_record(token)
    assert user == member.user
    assert record is not None
    with pytest.raises(AttributeError):
        record.encoded_token


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="missing"),
        pytest.param({"token_hash": "g" * 64}, id="not-hex"),
        pytest.param({"token_hash": _sha256("token").upper()}, id="uppercase"),
        pytest.param({"token_hash": _sha256("token")[:12]}, id="fingerprint"),
        pytest.param({"token_hash": _sha256("token")[:63]}, id="63-characters"),
    ],
)
def test_the_table_refuses_a_token_hash_that_is_not_a_sha256(
    sample_user: AbstractBaseUser, fields: dict[str, str]
) -> None:
    """A mint path that forgets the hash would otherwise store a row no token can match."""
    with pytest.raises(IntegrityError, match="access_token_stores_a_hash"), transaction.atomic():
        AccessToken.objects.create(user=sample_user, description="t", **fields)


def test_an_oidc_row_read_back_from_the_database_is_still_oidc(sample_user: AbstractBaseUser) -> None:
    """The OIDC scope check runs on a row that no longer holds the JWT to decode."""
    token = _oidc_token(sample_user)
    AccessToken.objects.create(user=sample_user, encoded_token=token, token_type=TOKEN_TYPE_OIDC, description="oidc")
    _, record = get_user_and_token_record(token)
    assert record is not None

    request = RequestFactory().get("/")
    request.access_token_record = AccessToken.objects.get(pk=record.pk)
    assert request_is_oidc_authed(request) is True


@pytest.mark.parametrize(("claimed", "stored"), [(TOKEN_TYPE_OIDC, TOKEN_TYPE_PAT), (TOKEN_TYPE_PAT, TOKEN_TYPE_OIDC)])
def test_a_token_whose_stored_type_disagrees_with_its_signed_claim_is_refused(
    sample_user: AbstractBaseUser, claimed: str, stored: str
) -> None:
    token = _oidc_token(sample_user) if claimed == TOKEN_TYPE_OIDC else create_personal_access_token(sample_user)
    AccessToken.objects.create(user=sample_user, encoded_token=token, token_type=stored, description="t")

    assert get_user_and_token_record(token) == (None, None)


def test_the_admin_form_renders_neither_the_token_nor_its_hash(sample_user: AbstractBaseUser) -> None:
    token = create_personal_access_token(sample_user)
    record = AccessToken.objects.create(user=sample_user, encoded_token=token, description="CI")
    stored = AccessToken.objects.get(pk=record.pk)

    form_class = AccessTokenAdmin(AccessToken, admin.site).get_form(RequestFactory().get("/"), stored)
    html = str(form_class(instance=stored))

    assert token not in html
    assert _sha256(token) not in html


@pytest.fixture
def sboms_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """The sbomify logger does not propagate, so caplog's root handler would see nothing."""
    logger = logging.getLogger("sbomify.apps.sboms.utils")
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def test_a_rejected_download_token_is_logged_by_fingerprint(sboms_log: pytest.LogCaptureFixture) -> None:
    token = make_download_token("sbom-id", "1")
    tampered = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"

    assert verify_download_token(tampered) is None
    assert verify_download_token(token, max_age=-1) is None

    assert len(sboms_log.records) == 2
    assert tampered not in sboms_log.text and token not in sboms_log.text
    assert _sha256(tampered)[:12] in sboms_log.text
    assert _sha256(token)[:12] in sboms_log.text


@isolate_apps("sbomify.apps.access_tokens")
def test_the_migration_keeps_every_existing_token_working(sample_user: AbstractBaseUser) -> None:
    """Tests build the schema from the models, so the old column comes back for the backfill to read."""
    # importlib because a migration module name starts with a digit.
    migration = import_module("sbomify.apps.access_tokens.migrations.0012_store_token_hash")

    class StoredToken(models.Model):
        encoded_token = models.CharField(max_length=1000)
        token_type = models.CharField(max_length=4)

        class Meta:
            app_label = "access_tokens"
            db_table = "access_tokens"
            managed = False

    class Registry:
        @staticmethod
        def get_model(app_label: str, model_name: str) -> type[models.Model]:
            return StoredToken

    tokens = {
        "pat": create_personal_access_token(sample_user),
        "oidc": _oidc_token(sample_user),
        # Minted before tokens carried a salt or a type claim, with an integer subject.
        "legacy": jwt.encode(
            {"iss": settings.JWT_ISSUER, "sub": sample_user.pk}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        ),
        "junk": "not-a-jwt",
    }
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE access_tokens ADD COLUMN encoded_token varchar(1000)")
        for name, token in tokens.items():
            row = AccessToken.objects.create(user=sample_user, encoded_token=f"placeholder {name}", description=name)
            cursor.execute("UPDATE access_tokens SET encoded_token = %s WHERE id = %s", [token, row.pk])
    migration.hash_stored_tokens(Registry(), SimpleNamespace(connection=connection))

    for name in ("pat", "oidc", "legacy"):
        assert get_user_and_token_record(tokens[name])[0] == sample_user, name
    assert dict(AccessToken.objects.values_list("description", "token_type")) == {
        "pat": TOKEN_TYPE_PAT,
        "oidc": TOKEN_TYPE_OIDC,
        "legacy": TOKEN_TYPE_PAT,
        "junk": TOKEN_TYPE_PAT,
    }
