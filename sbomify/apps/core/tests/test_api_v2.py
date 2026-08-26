"""v2 serves the same views under the vocabulary the product uses.

Every check here has a failure mode that produces a working API. A schema that
silently keeps its v1 fields still serialises; a request body parsed with the
wrong variant still returns 200 with the field unset; a v1 route that quietly
stops resolving looks like a client bug. So these assert the difference between
the two documents rather than that either one merely builds.
"""

from __future__ import annotations

import re

import pytest
from django.test import Client
from django.urls import reverse
from ninja import Schema

from sbomify.api_schema_variants import ERROR_CODE_RENAMES, VENDORED_MARKER, SchemaVariants
from sbomify.apis import api, api_v2
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse

TEAM_FIELDS = ("team_id", "team_key", "team_name", "is_default_team")


@pytest.fixture(scope="module")
def v1_schema() -> dict:
    return api.get_openapi_schema()


@pytest.fixture(scope="module")
def v2_schema() -> dict:
    return api_v2.get_openapi_schema()


def _operations(schema: dict) -> list[dict]:
    return [
        op for item in schema["paths"].values() for op in item.values() if isinstance(op, dict) and "responses" in op
    ]


def _ours(schemas: dict) -> list[str]:
    """Our own schemas, excluding the CycloneDX and SPDX models."""
    return [name for name in schemas if VENDORED_MARKER not in name]


class TestBothVersionsMount:
    def test_v1_and_v2_are_routed(self):
        assert reverse("api-1:openapi-json")
        assert reverse("api-2:openapi-json")

    def test_no_operation_was_lost(self, v1_schema, v2_schema):
        assert len(_operations(v1_schema)) == len(_operations(v2_schema))

    def test_v2_drops_exactly_the_duplicated_artifact_path(self, v1_schema, v2_schema):
        """/sboms/{id} and /sboms/sbom/{id} were two shapes for one resource."""
        assert len(v2_schema["paths"]) == len(v1_schema["paths"]) - 1


class TestV2SaysWorkspace:
    def test_no_path_says_team(self, v2_schema):
        assert [p for p in v2_schema["paths"] if re.search("team", p, re.I)] == []

    def test_v1_still_does(self, v1_schema):
        """The rename is the reason v2 exists; v1 must not have moved."""
        assert [p for p in v1_schema["paths"] if re.search("team", p, re.I)]

    def test_no_parameter_says_team(self, v2_schema):
        offenders = [
            (path, parameter["name"])
            for path, item in v2_schema["paths"].items()
            for operation in item.values()
            if isinstance(operation, dict)
            for parameter in operation.get("parameters", [])
            if "team" in parameter["name"].lower()
        ]
        assert offenders == []

    def test_no_schema_of_ours_is_named_team(self, v2_schema):
        assert [n for n in _ours(v2_schema["components"]["schemas"]) if "Team" in n] == []

    def test_no_property_is_named_team(self, v2_schema):
        offenders = {
            name: [p for p in (schema.get("properties") or {}) if p in TEAM_FIELDS]
            for name, schema in v2_schema["components"]["schemas"].items()
        }
        assert {n: v for n, v in offenders.items() if v} == {}

    def test_the_renamed_schemas_are_present(self, v2_schema):
        names = set(_ours(v2_schema["components"]["schemas"]))
        assert {"WorkspaceSchema", "WorkspacePatchSchema", "WorkspaceUpdateSchema"} <= names


class TestVendoredSchemasAreLeftAlone:
    """CycloneDX and SPDX models carry "sbom" in the name and are not ours.

    They are also self-referential, which is a second reason not to rebuild
    them: create_model cannot, and the failure is a stack overflow deep inside
    pydantic rather than anything legible.
    """

    def test_same_vendored_count_in_both(self, v1_schema, v2_schema):
        count = lambda s: len([n for n in s["components"]["schemas"] if VENDORED_MARKER in n])  # noqa: E731
        assert count(v1_schema) == count(v2_schema) > 0

    def test_no_vendored_schema_was_renamed(self, v1_schema, v2_schema):
        v1 = {n for n in v1_schema["components"]["schemas"] if VENDORED_MARKER in n}
        v2 = {n for n in v2_schema["components"]["schemas"] if VENDORED_MARKER in n}
        assert v1 == v2

    def test_our_schema_count_did_not_grow(self, v1_schema, v2_schema):
        """A variant built twice would show up as a second component."""
        assert len(_ours(v1_schema["components"]["schemas"])) == len(_ours(v2_schema["components"]["schemas"]))


class TestErrorCodes:
    """The one item in the terminology plan that genuinely needed a new version.

    A response carries a single ``error_code`` and a client may branch on the
    string, so there is no way to serve both spellings at once.
    """

    @pytest.fixture(scope="class")
    def v2_error(self):
        return SchemaVariants().response(ErrorResponse)

    @pytest.mark.parametrize(("v1_code", "v2_code"), sorted(ERROR_CODE_RENAMES.items()))
    def test_a_renamed_code_maps(self, v2_error, v1_code, v2_code):
        body = v2_error.model_validate({"detail": "x", "error_code": v1_code}).model_dump(by_alias=True)
        assert body["error_code"].value == v2_code

    def test_an_unrelated_code_is_untouched(self, v2_error):
        body = v2_error.model_validate({"detail": "x", "error_code": ErrorCode.NOT_FOUND}).model_dump(by_alias=True)
        assert body["error_code"].value == "NOT_FOUND"

    def test_v1_codes_are_frozen(self):
        for old in ERROR_CODE_RENAMES:
            assert ErrorCode(old).value == old


class TestTheTwoDirections:
    """A response renames the field; a request renames the wire name.

    Swapping these is the mistake this module exists to avoid, and neither
    direction fails loudly: a response comes back full of nulls, and a request
    reaches the view with the field unset.
    """

    def test_a_response_reads_the_old_attribute(self):
        from sbomify.apps.teams.schemas import MemberSchema

        variant = SchemaVariants().response(MemberSchema)
        source = {
            "id": 7,
            "user": {"id": 1, "username": "jo", "email": "a@b.c", "first_name": "J", "last_name": "O"},
            "role": "owner",
            "is_default_team": True,
            "is_me": False,
        }
        body = variant.model_validate(source).model_dump(by_alias=True)
        assert body["is_default_workspace"] is True
        assert "is_default_team" not in body

    def test_a_request_keeps_the_attribute_the_view_reads(self):
        from sbomify.apps.billing.schemas import ChangePlanRequest

        variant = SchemaVariants().request(ChangePlanRequest)
        properties = variant.model_json_schema(mode="validation")["properties"]
        assert "workspace_key" in properties
        assert "team_key" not in properties


class TestNothingIsLostInTranslation:
    """A variant is built from the original field, not from a list of its parts.

    Rebuilding a FieldInfo and re-listing what to copy drops whatever was not
    listed. On a request schema that means v2 accepting input v1 rejects, and
    nothing about it looks wrong: the endpoint works, the document validates,
    and the constraint is simply gone.
    """

    @pytest.mark.parametrize(
        ("module", "name"),
        [
            ("sbomify.apps.billing.schemas", "ChangePlanRequest"),
            ("sbomify.apps.teams.schemas", "TeamPatchSchema"),
            ("sbomify.apps.teams.schemas", "TeamUpdateSchema"),
            ("sbomify.apps.teams.schemas", "TeamDomainSchema"),
        ],
    )
    def test_validation_constraints_survive(self, module, name):
        import importlib

        model = getattr(importlib.import_module(module), name)
        variant = SchemaVariants().request(model)
        for field_name, field in model.model_fields.items():
            if not field.metadata:
                continue
            converted = variant.model_fields.get(field_name)
            assert converted is not None, f"{name}.{field_name} vanished"
            assert converted.metadata == field.metadata, f"{name}.{field_name} lost {field.metadata}"

    def test_a_default_factory_survives(self):
        """No converted schema uses one today, so this guards the next one."""
        from pydantic import Field as PydanticField

        class WithFactory(Schema):
            team_id: str
            tags: list[str] = PydanticField(default_factory=list)

        variant = SchemaVariants().response(WithFactory)
        assert variant.model_fields["tags"].default_factory is list


@pytest.mark.django_db
class TestDeprecationHeaders:
    """RFC 9745 and RFC 8594 describe a resource, so they go on the version.

    A client that never opens the docs still sees the date and the replacement
    on every call it already makes.
    """

    def test_v1_announces_its_sunset(self, client: Client):
        response = client.get("/api/v1/products")
        assert response.headers["Sunset"]
        assert response.headers["Deprecation"].startswith("@")
        assert 'rel="successor-version"' in response.headers["Link"]

    def test_v2_announces_nothing(self, client: Client):
        response = client.get("/api/v2/products")
        assert "Sunset" not in response.headers
        assert "Deprecation" not in response.headers

    def test_a_non_api_page_is_untouched(self, client: Client):
        response = client.get("/")
        assert "Sunset" not in response.headers


class TestTheDocsSayWhichIsWhich:
    def test_every_v1_operation_is_flagged(self, v1_schema):
        operations = _operations(v1_schema)
        assert operations and all(op.get("deprecated") for op in operations)

    def test_no_v2_operation_is(self, v2_schema):
        assert not any(op.get("deprecated") for op in _operations(v2_schema))
