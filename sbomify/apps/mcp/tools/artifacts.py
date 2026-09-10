"""Artifact inspection tools: BOMs of every kind, their packages, documents, assessments."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal, require
from ..limits import enforce_parse_size, untrusted
from ._base import clamp_page, mcp_tool, not_found, resolve_workspace, run_db
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


def _bounded(value: Any, *, limit: int = 1024) -> Any:
    """Recursively truncate the strings inside a plugin-produced structure.

    ``result_summary`` is plugin JSON derived from the uploaded SBOM, so its
    keys and values are as supplier-controlled as a package name. Truncating in
    place keeps the shape an agent expects while bounding how much injected text
    any one field can carry.

    Keys are bounded as well as values: a dict keyed on something taken from the
    artifact (a package name, a licence id) would otherwise carry unbounded
    attacker text straight past the value-side cap.
    """
    if isinstance(value, str):
        return untrusted(value, limit=limit)
    if isinstance(value, dict):
        return {
            (untrusted(key, limit=limit) if isinstance(key, str) else key): _bounded(item, limit=limit)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_bounded(item, limit=limit) for item in value]
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


def _extract_packages(payload: dict[str, Any], artifact_format: str) -> list[dict[str, Any]]:
    """Normalise CycloneDX components / SPDX packages into one shape.

    Returns ``{name, version, purl, licenses}`` per package so an agent can
    compare across formats without knowing which it is looking at.
    """
    packages: list[dict[str, Any]] = []

    if artifact_format.lower() == "cyclonedx":
        for entry in payload.get("components", []) or []:
            if not isinstance(entry, dict):
                continue
            licenses = [_license_label(lic) for lic in entry.get("licenses", []) or [] if isinstance(lic, dict)]
            packages.append(
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
            packages.append(
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
            packages.append(
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

    return packages


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "list_artifacts", "sbom:read")
    async def list_artifacts(
        principal: Principal,
        component_id: str,
        bom_type: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List the BOM artifacts uploaded for a component, newest first.

        Covers every BOM kind the component carries, not SBOMs alone: each row
        reports its own `bom_type`. Pass `bom_type` to narrow to one kind, one
        of sbom, cbom, aibom, hbom, vex, saasbom, obom, mbom. Documents are the
        other half of the artifact surface, listed by `list_documents`.
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
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List the packages a BOM artifact declares, with optional name filtering.

        Real BOMs routinely contain thousands of packages, so results are always
        paginated. To check whether a specific dependency is present, pass
        `name_filter` (case-insensitive substring) rather than paging through
        everything.

        Works for both CycloneDX and SPDX; results are normalised to
        `{name, version, purl, licenses}`.
        """

        def query() -> dict[str, Any]:
            from botocore.exceptions import BotoCoreError, ClientError

            from sbomify.apps.sboms.utils import SBOMDataError, get_sbom_data_bytes

            obj = _get_artifact(principal, artifact_id)
            try:
                # Fetch as bytes so the size can be checked before parsing —
                # a multi-hundred-MB artifact must fail with a message, not an
                # OOM that takes the worker down with it.
                _, raw = get_sbom_data_bytes(artifact_id)
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

            packages = _extract_packages(payload, obj.format)
            if name_filter:
                needle = name_filter.casefold()
                packages = [p for p in packages if needle in (p.get("name") or "").casefold()]

            safe_page, safe_size = clamp_page(page, page_size, default_size=50)
            start = (safe_page - 1) * safe_size
            window = packages[start : start + safe_size]

            result = serializers.paginated(
                [serializers.compact(p) for p in window],
                page=safe_page,
                page_size=safe_size,
                total=len(packages),
            )
            result["format"] = obj.format
            return result

        return await run_db(query)

    @mcp_tool(mcp, "list_documents", "document:read")
    async def list_documents(
        principal: Principal,
        component_id: str,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List the documents attached to a component, newest first."""

        def query() -> dict[str, Any]:
            from sbomify.apps.documents.models import Document

            component = _lookup_component(principal, component_id)
            require(principal, "document:read", component)
            safe_page, safe_size = clamp_page(page, page_size)
            queryset = Document.objects.filter(component=component).order_by("-created_at")
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

        Reports the latest run per plugin. Use this to answer "is this artifact
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
                    for run in runs
                ],
            }

        return await run_db(query)
