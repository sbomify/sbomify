"""v2 serves the same views under the vocabulary the product uses.

Every check here has a failure mode that produces a working API. A schema that
silently keeps its v1 fields still serialises; a request body parsed with the
wrong variant still returns 200 with the field unset; a v1 route that quietly
stops resolving looks like a client bug. So these assert the difference between
the two documents rather than that either one merely builds.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from django.test import Client
from django.urls import reverse
from ninja import Schema

from sbomify.api_schema_variants import ERROR_CODE_RENAMES, VENDORED_MARKER, SchemaVariants
from sbomify.apis import api, api_v2
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse

TEAM_FIELDS = ("team_id", "team_key", "team_name", "is_default_team")

# Two v2 paths keep the word, deliberately.
#
#   /components/{id}/sboms  sits beside /components/{id}/documents and returns
#       only the SBOM-model rows. Calling it /artifacts would promise the
#       document side too, so the rename here is a design question rather than
#       a mechanical one.
#   sbom-status             is the CRA regulation's own vocabulary, not ours.
SBOM_PATHS_KEPT_ON_PURPOSE = frozenset(
    {
        "/api/v2/components/{component_id}/sboms",
        "/api/v2/compliance/cra/{assessment_id}/sbom-status",
    }
)


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

    def test_both_apis_are_bound_before_either_is_mounted(self):
        """Ordering in sbomify/apis.py, load-bearing and easy to undo.

        add_router attaches its routers immediately, so mounting mutates
        module-level Router objects. If anything imported during a mount
        reaches sbomify.urls, its ``from sbomify.apis import api, api_v2`` runs
        against a half-executed module. With api_v2 defined below the mount
        that is an ImportError; python then drops sbomify.apis from
        sys.modules and the retry finds the routers already attached, failing
        with a ConfigError that names /sboms and points at the wrong line.

        Binding both names first makes the partial module importable, so a
        cycle surfaces as itself instead of as that cascade.
        """
        import inspect

        import sbomify.apis as module

        source = inspect.getsource(module).splitlines()
        line_of = lambda pattern: next(  # noqa: E731
            i for i, line in enumerate(source) if line.startswith(pattern)
        )
        first_mount = next(i for i, line in enumerate(source) if line.startswith("for _prefix, _dotted in MOUNTS:"))

        assert line_of("api = NinjaAPI(") < first_mount
        assert line_of("api_v2 = NinjaAPI(") < first_mount

    def test_no_operation_was_lost_except_the_internal_router(self, v1_schema, v2_schema):
        """Every v1 operation exists in v2, minus /internal, which is excluded.

        The internal router is auth=None by design, secured at the proxy by
        rules pinned to /api/v1/internal/*. Replaying it would publish those
        endpoints unauthenticated at a path no proxy rule matches.
        """
        internal_ops = [
            (verb, path)
            for path, item in v1_schema["paths"].items()
            if path.startswith("/api/v1/internal/")
            for verb, op in item.items()
            if isinstance(op, dict) and "responses" in op
        ]
        assert internal_ops, "the exclusion exists for these; if they moved, move the guard"
        assert len(_operations(v1_schema)) - len(internal_ops) == len(_operations(v2_schema))

    def test_v2_serves_nothing_under_internal(self, v2_schema):
        assert [p for p in v2_schema["paths"] if p.startswith("/api/v2/internal")] == []

    def test_v2_drops_the_duplicated_artifact_path_and_internal(self, v1_schema, v2_schema):
        """/sboms/{id} and /sboms/sbom/{id} were two shapes for one resource."""
        internal_paths = [p for p in v1_schema["paths"] if p.startswith("/api/v1/internal/")]
        assert len(v2_schema["paths"]) == len(v1_schema["paths"]) - 1 - len(internal_paths)


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

    def test_no_path_says_sboms_except_where_it_should(self, v2_schema):
        """The prefix rename is per-router, so a literal path elsewhere is missed.

        An artifact's releases are declared inside the core router, which mounts
        at the root. Remapping the sboms router's prefix never touched them, so
        they sat at /api/v2/sboms/{artifact_id}/releases: renamed parameter,
        unrenamed noun. Only checking for "team" let that through.
        """
        offenders = [
            path
            for path in v2_schema["paths"]
            if re.search("sbom", path, re.I) and path not in SBOM_PATHS_KEPT_ON_PURPOSE
        ]
        assert offenders == [], f"v2 paths still saying sbom: {offenders}"


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
        assert body["error_code"] == v2_code

    def test_an_unrelated_code_is_untouched(self, v2_error):
        body = v2_error.model_validate({"detail": "x", "error_code": ErrorCode.NOT_FOUND}).model_dump(by_alias=True)
        assert body["error_code"] == "NOT_FOUND"

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
        from sbomify.apps.core.schemas import ProductResponseSchema

        variant = SchemaVariants().response(ProductResponseSchema)
        source = {
            "id": "p1",
            "name": "Widget",
            "description": "",
            "team_id": "t1",
            "created_at": "2026-01-01T00:00:00Z",
            "is_public": False,
            "latest_uploads": [],
        }
        body = variant.model_validate(source).model_dump(by_alias=True, exclude_none=True)
        assert body["workspace_id"] == "t1"
        assert "team_id" not in body

    def test_a_dual_field_source_keeps_only_the_new_name(self):
        """v1 grew the workspace twin next to the deprecated team field, so a
        rename would write the same key twice; v2 drops the deprecated one."""
        from sbomify.apps.teams.schemas import MemberSchema

        variant = SchemaVariants().response(MemberSchema)
        source = {
            "id": 7,
            "user": {"id": 1, "username": "jo", "email": "a@b.c", "first_name": "J", "last_name": "O"},
            "role": "owner",
            "is_default_team": True,
            "is_default_workspace": True,
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


class TestOpenapiExtraSurvivesTheClone:
    def test_v2_csv_export_documents_its_body(self):
        from sbomify.apis import api_v2

        schema = api_v2.get_openapi_schema()
        op = schema["paths"]["/api/v2/exports/inventory.csv"]["get"]
        assert op["responses"][200]["content"]["text/csv"]["schema"] == {"type": "string"}
        assert 403 in op["responses"]


class TestV2ServesWhatTheViewsReturn:
    """The shared views return v1 class instances; v2 must accept them.

    The clone's response model is a different class, and pydantic refuses to
    revalidate a foreign model instance, so before the result-dumping wrapper
    every converted v2 endpoint answered 500 on every request while its v1
    twin worked. Reproduced, then pinned here at the operation level so the
    test needs no database.
    """

    @staticmethod
    def _operation(api_object, view_name):
        for _prefix, router in api_object._routers:
            for _path, path_view in router.path_operations.items():
                for operation in path_view.operations:
                    if operation.view_func.__name__ == view_name:
                        return operation
        raise AssertionError(f"no operation wraps {view_name}")

    def test_a_v1_instance_survives_v2_response_validation(self):
        from sbomify.apps.core.schemas import PaginatedProductsResponse

        instance = PaginatedProductsResponse(
            items=[],
            pagination={
                "total": 0,
                "page": 1,
                "page_size": 15,
                "total_pages": 0,
                "has_previous": False,
                "has_next": False,
            },
        )
        operation = self._operation(api_v2, "list_products")
        dumped = instance.model_dump()
        operation.response_models[200].model_validate({"response": dumped})

    def test_the_clone_wrapper_dumps_model_results(self):
        from sbomify.api_versioning import _dump_models
        from sbomify.apps.core.schemas import ProductResponseSchema

        instance = ProductResponseSchema(
            id="x", name="n", description="", team_id="t", created_at="2026-01-01T00:00:00Z", is_public=False
        )
        status, payload = _dump_models((200, instance))
        assert status == 200
        assert isinstance(payload, dict)
        assert payload["team_id"] == "t"

    def test_no_v2_operation_lost_its_response_declaration(self):
        """{200: None} is ninja for "discard the body": the licensing list
        returned 200 with zero bytes while v1 returned the data. A None a
        view declared itself ({204: None} on the deletes) is legitimate, so
        the check is against v1, not against None.
        """

        def none_statuses(api_object):
            found = {}
            for _prefix, router in api_object._routers:
                for _path, path_view in router.path_operations.items():
                    for operation in path_view.operations:
                        key = (operation.view_func.__name__, tuple(sorted(operation.methods)))
                        found[key] = {s for s, m in operation.response_models.items() if m is None}
            return found

        v1_nones, v2_nones = none_statuses(api), none_statuses(api_v2)
        for key, statuses in v2_nones.items():
            if key in v1_nones:
                assert statuses == v1_nones[key], f"{key}: v1 {v1_nones[key]} vs v2 {statuses}"

    def test_v2_keeps_the_exclude_flags(self):
        """sboms metadata endpoints declare exclude_none/exclude_unset; dropped
        flags made v2 emit the vendored CycloneDX model with every unset
        optional as null, which schema-validating consumers reject."""
        v1_op = self._operation(api, "patch_component_metadata")
        v2_op = self._operation(api_v2, "patch_component_metadata")
        assert (v2_op.exclude_none, v2_op.exclude_unset, v2_op.exclude_defaults) == (
            v1_op.exclude_none,
            v1_op.exclude_unset,
            v1_op.exclude_defaults,
        )
        assert v2_op.operation_id == v1_op.operation_id

    def test_v2_answers_throttles_with_retry_after(self):
        from ninja.errors import Throttled

        assert Throttled in api_v2._exception_handlers

    def test_a_source_carrying_both_names_keeps_one_field(self):
        """The v1 dual-field during the migration: renaming the old name onto
        the new one wrote the same key twice and kept whichever came second."""
        from ninja import Schema

        class Carrier(Schema):
            is_default_team: bool
            is_default_workspace: bool

        variant = SchemaVariants().response(Carrier)
        assert list(variant.model_fields) == ["is_default_workspace"]
        body = variant.model_validate({"is_default_workspace": True}).model_dump(by_alias=True)
        assert body == {"is_default_workspace": True}

    def test_request_variants_keep_the_source_model_config(self):
        """str_strip_whitespace lived in model_config, which create_model with
        a generic base dropped: v2 accepted the whitespace-only workspace
        names v1 rejects."""
        import pydantic

        from sbomify.apps.teams.schemas import TeamUpdateSchema

        variant = SchemaVariants().request(TeamUpdateSchema)
        assert variant.model_config.get("str_strip_whitespace") is True
        with pytest.raises(pydantic.ValidationError):
            variant.model_validate({"name": "   "})


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

    def test_v1_announces_deprecation_but_promises_no_date(self, client: Client):
        """Deprecation and Sunset are separate statements, split on review.

        v1 is deprecated, and v1 is not going away for a long time. A Sunset
        header is a promise of a date, so by default none is sent.
        """
        response = client.get("/api/v1/products")
        assert response.headers["Deprecation"].startswith("@")
        assert 'rel="successor-version"' in response.headers["Link"]
        assert "Sunset" not in response.headers

    def test_a_committed_sunset_date_is_announced(self, client: Client, settings):
        settings.API_V1_SUNSET = datetime(2030, 1, 1, tzinfo=UTC)
        response = client.get("/api/v1/products")
        assert response.headers["Sunset"] == "Tue, 01 Jan 2030 00:00:00 GMT"

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
