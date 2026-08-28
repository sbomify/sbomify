"""Build a second API version out of the first, without a second set of views.

A ninja ``Router`` cannot attach to two ``NinjaAPI`` objects: the second
``add_router`` raises ``ConfigError: Router@'/x' has already been attached``.
The usual answer is to turn every module-level ``router = Router()`` into a
factory, which here would mean editing fifteen files and re-indenting roughly
a hundred and ninety decorators.

An ``Operation`` already carries everything it was declared with, including the
original response annotation under ``response_models[status]``, so a fresh
Router can be built from a finished one instead. The views stay exactly where
they are and keep serving both versions; only the paths and the response models
differ, and both of those arrive here as functions.
"""

from __future__ import annotations

import functools
import inspect
import re
from typing import Any, Callable

from ninja import Router
from ninja.constants import NOT_SET
from pydantic import BaseModel

PathRewriter = Callable[[str], str]
ResponseRewriter = Callable[[str, int, Any], Any]


def rename_path_params(
    view: Callable[..., Any],
    renames: dict[str, str],
    convert_request: Callable[[Any], Any] | None = None,
) -> Callable[..., Any]:
    """Wrap ``view`` so ninja sees the new parameter names and it sees the old.

    ninja builds its request parser from the signature, so a path that says
    ``{workspace_key}`` needs a signature that says ``workspace_key``. The view
    keeps its own name: the wrapper translates on the way in, which is what
    lets one view serve a path parameter that is spelled differently per
    version.

    ``convert_request`` gets each parameter's annotation and may return a
    replacement. Request bodies reach a view through its signature rather than
    through ``response=``, so this is the only place a version can swap the
    schema a payload is parsed with.
    """
    # eval_str resolves the annotations in the view's own module. The wrapper
    # below is defined here, so its __globals__ cannot see the view's imports,
    # and a string annotation would reach pydantic as an undefined name.
    try:
        signature = inspect.signature(view, eval_str=True)
    except (NameError, TypeError):
        signature = inspect.signature(view)
    parameters, back = [], {}
    for name, parameter in signature.parameters.items():
        if convert_request is not None and parameter.annotation is not inspect.Parameter.empty:
            converted = convert_request(parameter.annotation)
            if converted is not parameter.annotation:
                parameter = parameter.replace(annotation=converted)
        if name in renames:
            back[renames[name]] = name
            parameters.append(parameter.replace(name=renames[name]))
        else:
            parameters.append(parameter)

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        for new_name, old_name in back.items():
            if new_name in kwargs:
                kwargs[old_name] = kwargs.pop(new_name)
        return _dump_models(view(*args, **kwargs))

    wrapper.__signature__ = signature.replace(parameters=parameters)  # type: ignore[attr-defined]
    # Built from the final parameter list, not the original signature: the loop
    # above may have renamed a parameter AND swapped its annotation through
    # convert_request, and both facts must agree everywhere they are readable.
    # ninja itself parses __signature__, so a stale __annotations__ would not
    # break routing, only lie to anything else that introspects the view.
    annotations = {
        parameter.name: parameter.annotation
        for parameter in parameters
        if parameter.annotation is not inspect.Parameter.empty
    }
    if signature.return_annotation is not inspect.Signature.empty:
        annotations["return"] = signature.return_annotation
    wrapper.__annotations__ = annotations
    return wrapper


def _dump_models(result: Any) -> Any:
    """Turn a returned pydantic instance into a dict the clone can validate.

    The shared views return instances of the v1 classes; the clone's response
    model is a different class built by create_model, and pydantic refuses to
    revalidate a foreign model instance. Dumped to a dict, the v1 field names
    line up with the variant's validation aliases and everything revalidates.
    Python mode, so datetimes stay datetimes for the second validation.
    """
    if isinstance(result, tuple) and len(result) == 2:
        return (result[0], _dump_models(result[1]))
    if isinstance(result, BaseModel):
        return result.model_dump()
    if isinstance(result, list):
        return [_dump_models(item) for item in result]
    return result


def rewrite_params_in_path(path: str, renames: dict[str, str]) -> str:
    """Rename ``{old}`` to ``{new}`` in a path, leaving literal segments alone."""
    return re.sub(r"\{([^}:]+)([^}]*)\}", lambda m: "{" + renames.get(m.group(1), m.group(1)) + m.group(2) + "}", path)


def _declared_response(operation: Any) -> Any:
    """Recover the ``response=`` argument from a built Operation.

    ninja wraps each status in a generated model with a single ``response``
    field, so the annotation on that field is the schema the view declared.
    """
    if not operation.response_models or all(model is NOT_SET for model in operation.response_models.values()):
        # An operation declared with no response= holds {200: NOT_SET}. Mapping
        # that sentinel into a dict turned it into {200: None}, which ninja
        # reads as "empty response": the view ran, the body was discarded, and
        # every such v2 endpoint answered 200 with zero bytes.
        return NOT_SET

    recovered: dict[int | str, Any] = {}
    for status, model in operation.response_models.items():
        field = getattr(model, "model_fields", {}).get("response")
        recovered[status] = field.annotation if field is not None else None
    return recovered


def clone_router(
    source: Router,
    *,
    rewrite_path: PathRewriter | None = None,
    rewrite_response: ResponseRewriter | None = None,
    param_renames: dict[str, str] | None = None,
    convert_request: Callable[[Any], Any] | None = None,
) -> Router:
    """Return a new Router serving ``source``'s views under rewritten paths.

    ``rewrite_path`` sees each path as declared on the router, so it is the
    place to rename a path parameter or move a prefix. ``rewrite_response``
    sees ``(path, status, schema)`` and returns the schema to use, which is how
    a version swaps one schema for another without touching the view.
    """
    clone = Router(
        auth=source.auth,
        throttle=source.throttle,
        tags=source.tags,
        by_alias=source.by_alias,
        exclude_unset=source.exclude_unset,
        exclude_defaults=source.exclude_defaults,
        exclude_none=source.exclude_none,
    )

    for path, path_view in source.path_operations.items():
        new_path = rewrite_path(path) if rewrite_path else path
        if param_renames:
            new_path = rewrite_params_in_path(new_path, param_renames)
        for operation in path_view.operations:
            response = _declared_response(operation)
            if rewrite_response is not None and isinstance(response, dict):
                response = {status: rewrite_response(new_path, status, schema) for status, schema in response.items()}
            clone.add_api_operation(
                new_path,
                list(operation.methods),
                rename_path_params(operation.view_func, param_renames or {}, convert_request),
                auth=operation.auth_param,
                throttle=operation.throttle_param,
                response=response,
                # The explicit id, where one was set. The two versions are two
                # OpenAPI documents, so the same id in both cannot collide; what
                # does collide is ninja regenerating ids for the operations
                # whose authors set one precisely because the auto id repeats.
                operation_id=operation.operation_id,
                summary=operation.summary,
                description=operation.description,
                tags=operation.tags,
                deprecated=operation.deprecated,
                by_alias=operation.by_alias,
                exclude_unset=operation.exclude_unset,
                exclude_defaults=operation.exclude_defaults,
                exclude_none=operation.exclude_none,
                include_in_schema=operation.include_in_schema,
                openapi_extra=operation.openapi_extra,
                url_name=path_view.url_name,
            )

    for prefix, nested in source._routers:
        clone.add_router(
            prefix,
            clone_router(
                nested,
                rewrite_path=rewrite_path,
                rewrite_response=rewrite_response,
                param_renames=param_renames,
                convert_request=convert_request,
            ),
        )

    return clone
