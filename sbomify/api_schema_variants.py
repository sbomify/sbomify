"""Derive a version's schemas from the version before it.

v2 renames the team vocabulary on the wire. The views underneath keep their own
names, because rewriting sixteen hundred ``.team`` accesses to serve a URL
change would be a far larger and riskier diff than the rename is worth.

That leaves the two directions needing opposite treatment, which is the whole
reason this module exists:

* A **response** schema renames its field and reads the old one. The view hands
  back an ORM row with ``team_id`` on it, and the client should see
  ``workspace_id``.
* A **request** schema keeps its field and renames the wire name. The client
  sends ``workspace_key``, and the view still reads ``payload.team_key``.

Get those backwards and the failure is quiet: a response silently full of
nulls, or a request body the view cannot read.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel, BeforeValidator, create_model

from sbomify.apps.core.schemas import ErrorCode

#: Field names renamed on the v2 wire, in both directions.
FIELD_RENAMES: dict[str, str] = {
    "team_id": "workspace_id",
    "team_key": "workspace_key",
    "team_name": "workspace_name",
    "is_default_team": "is_default_workspace",
}

#: Applied to the generated model's own name, so the v2 document says
#: WorkspaceSchema where v1 says TeamSchema.
MODEL_NAME_RENAMES: tuple[tuple[str, str], ...] = (("Team", "Workspace"),)

#: The three codes that cannot be renamed inside v1, because a response carries
#: exactly one ``error_code`` and a client may branch on the string. This is the
#: single item in the whole terminology plan that genuinely required a new
#: version rather than an additive change.
ERROR_CODE_RENAMES: dict[str, str] = {
    "NO_CURRENT_TEAM": "NO_CURRENT_WORKSPACE",
    "TEAM_NOT_FOUND": "WORKSPACE_NOT_FOUND",
    "TEAM_MISMATCH": "WORKSPACE_MISMATCH",
}

#: v2's error code enum: every v1 code, with those three renamed.
WorkspaceErrorCode = Enum(  # type: ignore[misc]
    "WorkspaceErrorCode",
    {ERROR_CODE_RENAMES.get(m.name, m.name): ERROR_CODE_RENAMES.get(m.value, m.value) for m in ErrorCode},
    type=str,
)


def _to_v2_error_code(value: Any) -> Any:
    """Map a v1 code onto its v2 spelling, leaving the other codes alone."""
    if value is None:
        return None
    raw = value.value if isinstance(value, Enum) else str(value)
    return ERROR_CODE_RENAMES.get(raw, raw)


V2ErrorCodeField = Annotated[WorkspaceErrorCode | None, BeforeValidator(_to_v2_error_code)]


#: The CycloneDX and SPDX models are generated from their specs. Three hundred
#: odd of them carry "sbom" in the name and several are self-referential, which
#: pydantic cannot rebuild through ``create_model``. They are somebody else's
#: vocabulary in any case, so this module never descends into them.
VENDORED_MARKER = "sbom_format_schemas"


def _is_vendored(model: type[BaseModel]) -> bool:
    return VENDORED_MARKER in getattr(model, "__module__", "")


def _rename_model(name: str) -> str:
    for old, new in MODEL_NAME_RENAMES:
        name = name.replace(old, new)
    return name


def _is_schema(annotation: Any) -> bool:
    """True for any pydantic model.

    Not just ``ninja.Schema``: most of the response models here subclass
    ``BaseModel`` directly, and checking only for Schema made this whole module
    a no-op that still generated a valid, entirely unrenamed document.
    """
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _base_of(model: type[BaseModel]) -> type[BaseModel]:
    """The variant subclasses its source, not a generic base.

    Subclassing the source keeps everything create_model cannot re-list:
    model_config (TeamUpdateSchema's str_strip_whitespace, which a generic
    base silently dropped, letting v2 accept the whitespace-only names v1
    rejects), validators, and for ninja Schemas the resolver machinery.
    Every field is redefined below, so requiredness and aliases still come
    from this module.
    """
    return model


class SchemaVariants:
    """Builds and caches the v2 form of each schema it is shown.

    Cached because the OpenAPI document keys components by model name: two
    separately generated variants of one schema would render as two components
    that happen to look the same, and ``$ref`` reuse would be lost.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[int, bool], type[BaseModel]] = {}
        # id() is only unique among live objects, so hold a reference to every
        # model keyed on. Without this a garbage-collected schema could have
        # its id reused and hand back the wrong variant.
        self._keyed: list[Any] = []

    def response(self, annotation: Any) -> Any:
        return self._convert(annotation, outgoing=True)

    def request(self, annotation: Any) -> Any:
        return self._convert(annotation, outgoing=False)

    def _needs_work(self, model: type[BaseModel], seen: set[int] | None = None) -> bool:
        """Does anything below this model get renamed?

        Asked before rebuilding rather than after, because ``create_model`` on a
        model that did not need it is both wasted work and, for a recursive
        schema, an outright failure inside pydantic.
        """
        if _is_vendored(model):
            return False
        seen = set() if seen is None else seen
        if id(model) in seen:
            return False
        seen.add(id(model))

        if _rename_model(model.__name__) != model.__name__:
            return True

        for name, field in model.model_fields.items():
            if name in FIELD_RENAMES or name == "error_code":
                return True
            for nested in self._nested_models(field.annotation):
                if self._needs_work(nested, seen):
                    return True
        return False

    @staticmethod
    def _nested_models(annotation: Any) -> list[type[BaseModel]]:
        found: list[type[BaseModel]] = []
        stack = [annotation]
        while stack:
            current = stack.pop()
            if _is_schema(current):
                found.append(current)
            else:
                stack.extend(get_args(current))
        return found

    def _convert(self, annotation: Any, *, outgoing: bool) -> Any:
        if _is_schema(annotation):
            if _is_vendored(annotation) or not self._needs_work(annotation):
                return annotation
            return self._variant(annotation, outgoing=outgoing)

        origin = get_origin(annotation)
        if origin is None:
            return annotation

        args = tuple(self._convert(a, outgoing=outgoing) for a in get_args(annotation))
        if args == get_args(annotation):
            return annotation
        try:
            return origin[args] if len(args) > 1 else origin[args[0]]
        except TypeError:
            # Unsubscriptable origin (a plain container, say). Nothing to
            # rewrite, so the caller keeps what it had.
            return annotation

    def _variant(self, model: type[BaseModel], *, outgoing: bool) -> type[BaseModel]:
        key = (id(model), outgoing)
        if key in self._cache:
            return self._cache[key]
        self._keyed.append(model)

        # Reserve the slot before recursing: a schema that refers to itself
        # would otherwise rebuild forever.
        self._cache[key] = model

        fields: dict[str, Any] = {}
        dropped: list[str] = []
        # A schema can need rebuilding for its own name alone, with every field
        # left untouched: TeamPatchSchema has no team_* field but still must not
        # be called Team in v2.
        changed = _rename_model(model.__name__) != model.__name__
        for name, field in model.model_fields.items():
            annotation = self._convert(field.annotation, outgoing=outgoing)
            renamed = FIELD_RENAMES.get(name, name)
            if renamed != name and renamed in model.model_fields:
                # The source already carries both names (the v1 dual-field
                # during a migration). Renaming the old one would write the
                # same key twice and silently discard whichever came second,
                # so v2 drops the deprecated duplicate. Skipping is not
                # enough now that the variant subclasses its source; the
                # field would ride in by inheritance, so it is removed after
                # the build below.
                changed = True
                dropped.append(name)
                continue
            if renamed != name or annotation is not field.annotation:
                changed = True
            if renamed != name and outgoing:
                # The variant subclasses its source, so the old name would
                # survive by inheritance next to the renamed field. Outgoing
                # only: a request variant redefines the old name itself, since
                # that is the attribute the view reads off the payload.
                dropped.append(name)

            if name == "error_code" and ErrorCode in (field.annotation, *get_args(field.annotation)):
                # Only when the field is typed as the core enum. The compliance
                # app carries its own ErrorResponse whose error_code is a plain
                # str in the DomainError vocabulary (lowercase "not_found");
                # forcing the uppercase enum onto it made every compliance
                # error 500 on v2 while v1 served it fine.
                annotation = V2ErrorCodeField
                changed = True

            # Copy the original FieldInfo and override only the names. Building
            # a fresh one and re-listing its attributes silently drops whatever
            # was not re-listed: max_length and pattern on ChangePlanRequest,
            # min_length on the two name fields, and any default_factory. On a
            # request schema that means v2 accepting input v1 rejects.
            new_field = copy.copy(field)
            new_field.annotation = annotation
            new_field.serialization_alias = renamed
            if outgoing:
                # The view still produces the old attribute; the wire gets the
                # new name.
                new_field.validation_alias = name
                fields[renamed] = (annotation, new_field)
            else:
                # The wire carries the new name; the view still reads the old
                # attribute off the parsed payload.
                new_field.validation_alias = renamed
                fields[name] = (annotation, new_field)

        if not changed:
            # Nothing in this schema or anything below it moved. Returning the
            # original keeps one component in the document instead of two that
            # differ only by identity.
            self._cache[key] = model
            return model

        variant = create_model(
            _rename_model(model.__name__),
            __base__=_base_of(model),
            # Built in the source model's namespace so pydantic resolves any
            # string annotation the same way the original did. Created here
            # instead, a forward reference like "ComponentSummarySchema" is an
            # undefined name and the model never finishes building.
            __module__=model.__module__,
            **fields,
        )
        variant.__doc__ = model.__doc__
        for name in dropped:
            variant.__pydantic_fields__.pop(name, None)
        if dropped:
            variant.model_rebuild(force=True)
        self._cache[key] = variant
        return variant
