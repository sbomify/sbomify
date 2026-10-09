"""Artifact inspection tools: BOMs of every kind, their packages, documents, assessments."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal, require
from ..limits import enforce_parse_size, enforce_stored_size, untrusted
from ._base import DETAIL_COLLECTION_LIMIT, clamp_page, mcp_tool, narrow, not_found, resolve_workspace, run_db
from .catalog import _lookup_component

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _get_artifact(principal: Principal, artifact_id: str) -> Any:
    """One row of the artifact table, whatever ``bom_type`` it carries.

    The table holds all eight BOM kinds, so the lookup is deliberately untyped:
    a CBOM and an SBOM are both artifacts here, and an id that names either is
    equally valid input to every tool below.
    """
    from sbomify.apps.sboms.models import SBOM

    team = resolve_workspace(principal)
    obj = SBOM.objects.filter(pk=artifact_id, component__team=team).select_related("component").first()
    if obj is None:
        raise not_found("Artifact", artifact_id)
    require(principal, "sbom:read", obj.component)
    return obj


def _bounded(value: Any, *, limit: int = 1024, depth: int = 0) -> Any:
    """Recursively truncate the strings inside a plugin-produced structure.

    ``result_summary`` is plugin JSON derived from the uploaded SBOM, so its
    keys and values are as supplier-controlled as a package name. Truncating in
    place keeps the shape an agent expects while bounding how much injected text
    any one field can carry.

    Keys are bounded as well as values: a dict keyed on something taken from the
    artifact (a package name, a licence id) would otherwise carry unbounded
    attacker text straight past the value-side cap.

    Depth is bounded for the same reason ``_cyclonedx_components`` bounds it:
    the input is supplier-controlled, and a pathologically nested summary would
    otherwise raise ``RecursionError`` rather than ``ToolError``. That lands in
    the wrapper's bare ``except Exception``, which audits with no detail by
    design, so the agent would see an opaque internal error for a document the
    server could have refused with a reason.
    """
    if depth > _MAX_SUMMARY_DEPTH:
        return "… [truncated by sbomify: nested too deeply]"
    if isinstance(value, str):
        return untrusted(value, limit=limit)
    if isinstance(value, dict):
        return {
            (untrusted(key, limit=limit) if isinstance(key, str) else key): _bounded(item, limit=limit, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_bounded(item, limit=limit, depth=depth + 1) for item in value]
    return value


def _field(entry: Any, key: str, *, limit: int = 512) -> str | None:
    """One string field from an uploaded artifact, bounded in length.

    Everything inside an SBOM is supplier-controlled and reaches the agent
    verbatim, so a package "name" is a plausible carrier for prompt injection.
    Truncating each field caps how much injected text can ride along; the
    server instructions tell the model to treat these values as data.
    """
    value = entry.get(key)
    return untrusted(value, limit=limit) if isinstance(value, str) else None


def _license_label(entry: dict[str, Any]) -> str | None:
    """The display label for one CycloneDX ``licenses[]`` entry.

    The nested ``license`` key is optional and, in real-world documents, is
    sometimes present but null or a bare string. A chained
    ``entry.get("license", {}).get("id")`` raises AttributeError on those,
    because the default only applies when the key is *absent* — so a
    syntactically valid SBOM could crash `get_sbom_packages`.
    """
    nested = entry.get("license")
    if isinstance(nested, dict):
        label = nested.get("id") or nested.get("name")
        if isinstance(label, str):
            return label
    elif isinstance(nested, str):
        return nested

    expression = entry.get("expression")
    return expression if isinstance(expression, str) else None


#: How far down a components tree to walk. Deep enough for the nesting real
#: generators emit, shallow enough that a hostile document cannot make the walk
#: the expensive part of the request.
_MAX_COMPONENT_DEPTH = 12

#: The same ceiling for a plugin summary, and for the same reason: the JSON is
#: derived from supplier-supplied SBOM content, so its nesting is theirs to
#: choose. Real summaries are two or three deep.
_MAX_SUMMARY_DEPTH = 12


def _cyclonedx_components(entries: Any, *, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Every component in a CycloneDX tree, nested ones included.

    CycloneDX lets a component carry its own ``components``, and syft emits
    exactly that for a container image: the layers hold the packages. Reading
    only the top level answered "is log4j in here?" with a confident no for a
    document that contains it, which is the worst shape a wrong answer can take
    on this tool, since the server instructions send agents to name_filter
    rather than paging.
    """
    if depth > _MAX_COMPONENT_DEPTH or not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        yield entry
        yield from _cyclonedx_components(entry.get("components"), depth=depth + 1)


def _extract_packages(payload: dict[str, Any], artifact_format: str) -> list[dict[str, Any]]:
    """Every package, as a list. See ``_iter_packages`` for the streaming form."""
    return list(_iter_packages(payload, artifact_format))


def _iter_packages(payload: dict[str, Any], artifact_format: str) -> Iterator[dict[str, Any]]:
    """Normalise CycloneDX components / SPDX packages into one shape.

    Yields ``{name, version, purl, licenses}`` per package so an agent can
    compare across formats without knowing which it is looking at.

    A generator because the caller wants one page: a maximum-sized artifact
    holds tens of thousands of packages, and building the whole list to slice
    a hundred rows out of it is a second full copy of the document in Python
    objects, on top of the parsed JSON.
    """

    if artifact_format.lower() == "cyclonedx":
        for entry in _cyclonedx_components(payload.get("components")):
            licenses = [_license_label(lic) for lic in entry.get("licenses", []) or [] if isinstance(lic, dict)]
            yield (
                {
                    "name": _field(entry, "name"),
                    "version": _field(entry, "version"),
                    "purl": _field(entry, "purl"),
                    "licenses": [untrusted(lic, limit=256) for lic in licenses if isinstance(lic, str)],
                }
            )
    elif isinstance(payload.get("@graph"), list):
        # SPDX 3.0: packages are software_Package elements in the graph
        # (mirrors sboms.schemas.SPDX3Package, minus its strict validation —
        # a stored artifact must degrade per element, not fail whole).
        for entry in payload["@graph"]:
            if not isinstance(entry, dict) or entry.get("type") != "software_Package":
                continue
            purl = None
            for ext in entry.get("externalIdentifiers", []) or []:
                if isinstance(ext, dict) and ext.get("externalIdentifierType") in ("purl", "packageURL"):
                    purl = ext.get("identifier")
                    break
            yield (
                {
                    "name": _field(entry, "name"),
                    "version": _field(entry, "software_packageVersion"),
                    "purl": untrusted(purl, limit=512) if isinstance(purl, str) else None,
                    # SPDX 3.0 carries licensing via relationships, not package
                    # fields; omitted rather than guessed.
                    "licenses": [],
                }
            )
    else:
        for entry in payload.get("packages", []) or []:
            if not isinstance(entry, dict):
                continue
            # Prefer licenseDeclared, but NOASSERTION carries no information —
            # fall through to licenseConcluded, matching SPDXPackage.license.
            declared = entry.get("licenseDeclared")
            if not isinstance(declared, str) or not declared or declared == "NOASSERTION":
                declared = entry.get("licenseConcluded")
            purl = None
            for ref in entry.get("externalRefs", []) or []:
                if isinstance(ref, dict) and ref.get("referenceType") == "purl":
                    purl = ref.get("referenceLocator")
                    break
            yield (
                {
                    "name": _field(entry, "name"),
                    "version": _field(entry, "versionInfo"),
                    "purl": untrusted(purl, limit=512) if isinstance(purl, str) else None,
                    "licenses": (
                        [untrusted(declared, limit=256)]
                        if isinstance(declared, str) and declared and declared != "NOASSERTION"
                        else []
                    ),
                }
            )


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "list_artifacts", "sbom:read")
    async def list_artifacts(
        principal: Principal,
        component_id: str,
        bom_type: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List the BOM artifacts uploaded for a component, newest first.

        Covers every BOM kind the component carries, not SBOMs alone: each row
        reports its own `bom_type`. Pass `bom_type` to narrow to one kind, one
        of sbom, cbom, aibom, hbom, vex, saasbom, obom, mbom, and `search` to
        match the artifact name or version. Documents are the other half of the
        artifact surface, listed by `list_documents`.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.sboms.models import SBOM

            # Authorize with this tool's own action, not component:read_internal:
            # the registry advertises the tool to any token granting sbom:read,
            # so demanding a second scope here would advertise-then-refuse.
            component = _lookup_component(principal, component_id)
            require(principal, "sbom:read", component)
            safe_page, safe_size = clamp_page(page, page_size)
            queryset = SBOM.objects.filter(component=component).order_by("-created_at")
            if bom_type is not None:
                # Named rather than silently ignored: an agent that asks for a
                # kind and gets every kind back would report the wrong answer
                # confidently. Listing the valid ones saves it a second guess.
                wanted = bom_type.strip().lower()
                if wanted not in set(SBOM.BomType.values):
                    raise ToolError(
                        f"Unknown bom_type {bom_type!r}; expected one of {', '.join(sorted(SBOM.BomType.values))}."
                    )
                queryset = queryset.filter(bom_type=wanted)
            queryset = narrow(queryset, search, "name", "version")
            rows, total = serializers.page_queryset(queryset, safe_page, safe_size)
            return serializers.paginated(
                [serializers.sbom(row) for row in rows],
                page=safe_page,
                page_size=safe_size,
                total=total,
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_artifact", "sbom:read")
    async def get_artifact(principal: Principal, artifact_id: str) -> dict[str, Any]:
        """Metadata for one BOM artifact: kind, format, version, hash, signing.

        Accepts any BOM kind; `bom_type` in the response says which one. Does
        not return the document itself, use `get_artifact_packages` for its
        contents.
        """

        def query() -> dict[str, Any]:
            obj = _get_artifact(principal, artifact_id)
            data = serializers.sbom(obj, detail=True)
            data["component"] = {"id": obj.component.id, "name": obj.component.name}
            return serializers.compact(data)

        return await run_db(query)

    @mcp_tool(mcp, "get_artifact_packages", "sbom:read")
    async def get_artifact_packages(
        principal: Principal,
        artifact_id: str,
        name_filter: str | None = None,
        response_format: Literal["detailed", "concise"] = "detailed",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List the packages a BOM artifact declares, with optional name filtering.

        Real BOMs routinely contain thousands of packages, so results are always
        paginated. To check whether a specific dependency is present, pass
        `name_filter` (case-insensitive substring) rather than paging through
        everything.

        Works for both CycloneDX and SPDX; results are normalised to
        `{name, version, purl, licenses}`. `response_format` "concise" returns
        the name and version alone, which is what answering "do we ship X?"
        needs and a fraction of the context.
        """

        def query() -> dict[str, Any]:
            from botocore.exceptions import BotoCoreError, ClientError

            from sbomify.apps.core import object_store
            from sbomify.apps.sboms.utils import SBOMDataError, get_sbom_data_bytes

            obj = _get_artifact(principal, artifact_id)
            try:
                # Size first, from a HEAD against the store. Checking only the
                # downloaded bytes made the cap advisory: a multi-hundred-MB
                # artifact still cost its full transfer and its full place in
                # memory before anything refused it, which is the OOM the cap
                # exists to prevent.
                if obj.sbom_filename:
                    try:
                        stored_size = object_store.StorageClient("SBOMS").get_sbom_size(obj.sbom_filename)
                    except (ClientError, BotoCoreError):
                        # Best effort. A store that cannot answer a HEAD — a
                        # least-privilege policy granting GetObject only, a
                        # backend without one — must not cost the read, because
                        # enforce_parse_size below is still the authoritative
                        # check. Only the saving is lost, never the ceiling.
                        stored_size = None
                    enforce_stored_size(stored_size, artifact_id=artifact_id)
                _, raw = get_sbom_data_bytes(artifact_id)
                # Still checked after the fetch: the store is the authority on
                # what it holds, but a key rewritten between the two calls, or a
                # backend that cannot answer a HEAD, must not slip past.
                enforce_parse_size(raw, artifact_id=artifact_id)
                payload = json.loads(raw)
            except SBOMDataError as exc:
                raise ToolError(f"Could not read artifact {artifact_id}: {exc}") from exc
            except (ClientError, BotoCoreError) as exc:
                # get_sbom_data_bytes wraps most failure modes in SBOMDataError,
                # but the S3 fetch itself re-raises botocore errors. Without
                # this they hit the wrapper's generic handler, which audits with
                # no detail — the agent would see an opaque internal error for
                # what is a retryable storage fault. Message kept generic: a
                # botocore message can carry bucket names and key paths.
                raise ToolError(f"Could not read artifact {artifact_id}: artifact storage is unavailable.") from exc
            except json.JSONDecodeError as exc:
                raise ToolError(f"Artifact {artifact_id} is not valid JSON: {exc}") from exc

            if not isinstance(payload, dict):
                # A stored artifact whose top level is a list/string/null —
                # reachable via the non-validating upload paths. Without this,
                # payload.get below raises and the agent sees an opaque error.
                raise ToolError(f"Artifact {artifact_id} is not a JSON object; cannot list its packages.")

            safe_page, safe_size = clamp_page(page, page_size, default_size=50)
            start = (safe_page - 1) * safe_size
            needle = name_filter.casefold() if name_filter else None

            # Counted while streaming, keeping only the page. The total still
            # costs a full walk — the agent needs to know what it is not seeing
            # — but at most page_size package dicts are alive at once instead
            # of one per package in the artifact.
            window: list[dict[str, Any]] = []
            total = 0
            for pkg in _iter_packages(payload, obj.format):
                if needle is not None and needle not in (pkg.get("name") or "").casefold():
                    continue
                if start <= total < start + safe_size:
                    window.append(pkg)
                total += 1

            if response_format == "concise":
                window = [{"name": pkg.get("name"), "version": pkg.get("version")} for pkg in window]

            result = serializers.paginated(
                [serializers.compact(p) for p in window],
                page=safe_page,
                page_size=safe_size,
                total=total,
            )
            result["format"] = obj.format
            return result

        return await run_db(query)

    @mcp_tool(mcp, "list_documents", "document:read")
    async def list_documents(
        principal: Principal,
        component_id: str,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List the documents attached to a component, newest first.

        `search` matches the document name and its version, case-insensitively.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.documents.models import Document

            component = _lookup_component(principal, component_id)
            require(principal, "document:read", component)
            safe_page, safe_size = clamp_page(page, page_size)
            queryset = narrow(Document.objects.filter(component=component), search, "name", "version").order_by(
                "-created_at"
            )
            rows, total = serializers.page_queryset(queryset, safe_page, safe_size)
            return serializers.paginated(
                [serializers.document(row) for row in rows],
                page=safe_page,
                page_size=safe_size,
                total=total,
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_document", "document:read")
    async def get_document(principal: Principal, document_id: str) -> dict[str, Any]:
        """Metadata for one document: type, version, filename, size, hash.

        The document half of `get_artifact`. Does not return the file itself.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.documents.models import Document

            team = resolve_workspace(principal)
            obj = Document.objects.filter(pk=document_id, component__team=team).select_related("component").first()
            if obj is None:
                raise not_found("Document", document_id)
            require(principal, "document:read", obj.component)
            data = serializers.document(obj, detail=True)
            data["component"] = {"id": obj.component.id, "name": obj.component.name}
            return serializers.compact(data)

        return await run_db(query)

    @mcp_tool(mcp, "get_assessments", "sbom:read")
    async def get_assessments(principal: Principal, artifact_id: str) -> dict[str, Any]:
        """Compliance and licence assessment results for an artifact (NTIA, etc.).

        Reports the latest run per plugin, so the result is bounded by how many
        compliance plugins exist rather than by the artifact, and is returned
        whole rather than paginated. Use this to answer "is this artifact
        compliant?". Vulnerability scan results are reported separately by
        `get_vulnerability_summary` and `list_vulnerabilities`.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.plugins.models import AssessmentRun
            from sbomify.apps.plugins.sdk.enums import AssessmentCategory

            _get_artifact(principal, artifact_id)
            # Latest per plugin resolved in the database (DISTINCT ON), like
            # every dashboard consumer — materializing the full history would
            # de-TOAST each superseded run's result blob only to discard it.
            # `result` itself is never read, so it stays deferred.
            runs = (
                AssessmentRun.objects.filter(sbom_id=artifact_id)
                .exclude(category=AssessmentCategory.SECURITY.value)
                .order_by("plugin_name", "-created_at", "-id")
                .distinct("plugin_name")
                .defer("result")
            )

            # Bounded by how many compliance plugins are registered rather than
            # by anything in the artifact, but cut anyway: "a number we control
            # today" is not the same as a bound, and this tool takes no page
            # argument to narrow with if it ever stops being small.
            rows = list(runs[: DETAIL_COLLECTION_LIMIT + 1])
            return {
                "artifact_id": artifact_id,
                "assessments": [
                    serializers.compact(
                        {
                            "plugin": run.plugin_name,
                            "category": run.category,
                            "status": run.status,
                            "skipped": run.result_skipped,
                            "created_at": run.created_at.isoformat() if run.created_at else None,
                            # result_summary, never the full `result` blob: the
                            # latter carries every individual finding and would
                            # swamp the agent's context for no benefit. Both this
                            # and error_message derive from plugin output over
                            # supplier-supplied SBOM content, so both are bounded
                            # like any other artifact-derived text.
                            "summary": _bounded(run.result_summary),
                            "error": untrusted(run.error_message, limit=2000),
                        }
                    )
                    for run in rows[:DETAIL_COLLECTION_LIMIT]
                ],
                "assessments_truncated": len(rows) > DETAIL_COLLECTION_LIMIT,
            }

        return await run_db(query)
