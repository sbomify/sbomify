"""CRA document generation service — render Django templates, store in S3."""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.template import Context, Engine

from sbomify.apps.compliance.models import (
    CRAAssessment,
    CRAGeneratedDocument,
    OSCALFinding,
)
from sbomify.apps.compliance.services._manufacturer_policy import (
    is_placeholder_manufacturer as _is_placeholder_manufacturer,
)
from sbomify.apps.compliance.services._reference_data import (
    ReferenceDataError,
)
from sbomify.apps.compliance.services._reference_data import (
    load_harmonised_standards as _load_harmonised_standards,
)
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.services.contacts import get_manufacturer, get_security_contact

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "document_templates"


def _assessment_facts(assessment: CRAAssessment) -> dict[str, Any]:
    """Extract the facts used by ``applies_when`` rule evaluation.

    Centralised so the same fact set is built once per selection pass
    and the rule vocabulary is discoverable in one place. The keys
    here MUST match the predicate keys used in
    ``cra-harmonised-standards.json`` ``applies_when`` rules —
    ``product_category``, ``processes_personal_data``, etc.

    Note ``product_category`` is overloaded: ``CRAAssessment.product_category``
    is the CRA risk tier (Default / Class I / II / Critical), but the
    harmonised-standards rules key on product *type* ("radio_equipment",
    "operating_system"). We surface ``"radio_equipment"`` when the
    RED flag is set and fall back to the raw CRA tier otherwise.
    """
    return {
        "product_category": "radio_equipment" if assessment.is_radio_equipment else assessment.product_category,
        "processes_personal_data": bool(assessment.processes_personal_data),
        "handles_financial_value": bool(assessment.handles_financial_value),
        # Operator explicit opt-in is not a separate field today —
        # it's implied by ``is_radio_equipment``. Reserved for a
        # future "claim presumption of conformity without RED
        # classification" path (out of scope for #905).
        "operator_opt_in": False,
    }


_COMBINATORS = frozenset({"any_of", "all_of"})


def _evaluate_applies_when(rule: dict[str, Any] | None, facts: dict[str, Any]) -> bool:
    """Evaluate a single ``applies_when`` rule against assessment facts.

    Supported shapes (mutually exclusive at each level):

    - ``{"any_of": [rule, rule, ...]}`` — OR over sub-rules.
    - ``{"all_of": [rule, rule, ...]}`` — AND over sub-rules.
    - ``{"<key>": <expected>, ...}`` — equality predicate; ALL pairs
      must match (implicit AND across siblings).
    - ``{}`` — vacuously true.

    Any non-dict rule shape — including ``None``, ``[]``, scalars,
    non-list combinator payloads — fails closed and returns
    ``False``. Entries that should always apply must carry
    ``always_applicable: true`` in the reference JSON; the caller
    short-circuits on that flag before invoking this evaluator, so
    ``applies_when: null`` here is a typo rather than
    "always applies".

    Combinators and equality predicates **cannot be mixed at the
    same level**. ``{"any_of": [...], "product_category": "x"}``
    would silently drop the ``product_category`` check under a
    "combinator wins" resolution; we fail closed instead and force
    the rule author to nest the equality inside an ``all_of``. The
    JSON is code-controlled, but this is a real footgun for future
    rule writers and reviewers.

    A missing key in the facts dict fails the predicate — unknown
    predicates fail closed so a typo in the JSON doesn't silently
    open up an unintended match.
    """
    # Fail closed on any non-dict rule shape. A valid-but-malformed
    # reference JSON (``applies_when: []``, ``applies_when: "x"``,
    # ``applies_when: null``) would otherwise either short-circuit
    # to True or crash on ``.keys()``; both are unsafe for a CRA
    # DoC. Entries that should "always apply" set
    # ``always_applicable: true`` in the JSON and short-circuit at
    # the caller (see ``_select_applied_standards``) before this
    # evaluator runs — so ``None`` here is "no predicate was
    # authored" which we treat as fail-closed at the recursive
    # level. An empty dict ``{}`` remains True (vacuous) to match
    # the standard rule-tree semantics.
    if not isinstance(rule, dict):
        return False
    if not rule:
        return True
    combinator_keys = _COMBINATORS & rule.keys()
    if combinator_keys and len(rule) > 1:
        # Mixed shape — reject. Fails closed, matching the
        # "unknown predicate fails closed" policy.
        return False
    if "any_of" in rule:
        sub_rules = rule["any_of"]
        if not isinstance(sub_rules, list):
            # Non-list combinator payload — fail closed rather than
            # raising ``TypeError: 'str' object is not iterable`` or
            # worse, silently iterating the characters of a string.
            return False
        return any(_evaluate_applies_when(sub, facts) for sub in sub_rules)
    if "all_of" in rule:
        sub_rules = rule["all_of"]
        if not isinstance(sub_rules, list):
            return False
        return all(_evaluate_applies_when(sub, facts) for sub in sub_rules)
    for key, expected in rule.items():
        if facts.get(key) != expected:
            return False
    return True


def _select_applied_standards(assessment: CRAAssessment) -> list[dict[str, Any]]:
    """Select the standards applicable to this assessment.

    Always includes entries flagged ``always_applicable`` (CRA itself,
    BSI TR-03183-2). Additional entries with an ``applies_when`` rule
    tree (EN 18031-1/-2/-3) are included when the rule evaluates true
    against the assessment's facts. Draft standards (id contains
    ``draft``) are excluded regardless of the rule — presumption of
    conformity attaches to OJ-published standards only. ETSI EN
    304 626 stays hidden until promoted (issue tracked separately).

    Each returned entry carries ``harmonised`` so the DoC template
    can render "presumption of conformity" language next to true
    harmonised standards, and any ``restrictions`` text so the
    operator sees the OJ L_202500138 caveats (e.g. the default-
    password disqualifier on EN 18031-1 §6.2.5) inline with the claim.
    """
    data = _load_harmonised_standards()
    facts = _assessment_facts(assessment)
    applied: list[dict[str, Any]] = []
    for std in data.get("standards", []):
        include = bool(std.get("always_applicable")) or _evaluate_applies_when(std.get("applies_when"), facts)
        if not include:
            continue
        if "draft" in std.get("id", ""):
            continue
        applied.append(
            {
                "citation": std.get("citation", ""),
                "url": std.get("url", ""),
                "harmonised": bool(std.get("harmonised", False)),
                "cra_requirements_covered": std.get("cra_requirements_covered", []),
                "restrictions": std.get("restrictions", []),
            }
        )
    return applied


_engine = Engine(dirs=[str(_TEMPLATE_DIR)], autoescape=False)

# Map document kinds to template filenames
_TEMPLATE_MAP: dict[str, str] = {
    CRAGeneratedDocument.DocumentKind.VDP: "vdp.md.dtl",
    CRAGeneratedDocument.DocumentKind.SECURITY_TXT: "security_txt.dtl",
    CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT: "risk_assessment.md.dtl",
    CRAGeneratedDocument.DocumentKind.EARLY_WARNING: "early_warning.md.dtl",
    CRAGeneratedDocument.DocumentKind.FULL_NOTIFICATION: "full_notification.md.dtl",
    CRAGeneratedDocument.DocumentKind.FINAL_REPORT: "final_report.md.dtl",
    CRAGeneratedDocument.DocumentKind.USER_INSTRUCTIONS: "user_instructions.md.dtl",
    CRAGeneratedDocument.DocumentKind.DECOMMISSIONING_GUIDE: "decommissioning_guide.md.dtl",
    CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY: "declaration_of_conformity.md.dtl",
}

# Map EU country codes to language codes for security.txt Preferred-Languages
_COUNTRY_LANGUAGE_MAP: dict[str, str] = {
    "AT": "de",
    "BE": "nl,fr,de",
    "BG": "bg",
    "HR": "hr",
    "CY": "el",
    "CZ": "cs",
    "DK": "da",
    "EE": "et",
    "FI": "fi",
    "FR": "fr",
    "DE": "de",
    "GR": "el",
    "HU": "hu",
    "IE": "en",
    "IT": "it",
    "LV": "lv",
    "LT": "lt",
    "LU": "fr,de",
    "MT": "mt,en",
    "NL": "nl",
    "PL": "pl",
    "PT": "pt",
    "RO": "ro",
    "SK": "sk",
    "SI": "sl",
    "ES": "es",
    "SE": "sv",
}


def _sanitize(value: str, escape_pipe: bool = False, escape_markdown: bool = False) -> str:
    """Strip control characters and escape Markdown / HTML so operator-
    supplied strings can't inject content into rendered compliance docs.

    The generated DoC, VDP, user-instructions etc. are Markdown shipped
    to EU notified bodies. Any field sourced from operator input
    (product name, manufacturer name, intended use, support info, …)
    must be escaped against:

    1. Line injection into plain-text artefacts (security.txt).
       Always applied — newline / tab / control chars collapse to space.
    2. Markdown table corruption via ``|``. Enabled per call-site via
       ``escape_pipe`` (finding notes live in table cells).
    3. Markdown / HTML injection into arbitrary sections when the
       document is later rendered to HTML (``pandoc -f markdown``,
       GitLab viewer, Confluence, VS Code preview). Enabled via
       ``escape_markdown`` for every free-text field that appears in
       the body of a rendered document. Escapes the standard CommonMark
       metacharacters plus ``<`` / ``>`` so a payload like
       ``<script>alert(1)</script>`` or ``[click](javascript:…)`` is
       emitted literally instead of being evaluated.

    The DoC is a regulated legal document under CRA Article 28 — an
    operator MUST NOT be able to embed tracking pixels, phishing
    links, or executable HTML into their own declaration of conformity
    through this pipeline.
    """
    import re

    # Replace newlines/tabs/carriage returns with spaces, strip other control chars
    sanitized = re.sub(r"[\r\n\t]", " ", value)
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", sanitized)
    sanitized = re.sub(r" +", " ", sanitized).strip()
    if escape_pipe:
        sanitized = sanitized.replace("|", "\\|")
    if escape_markdown:
        # CommonMark metacharacters that can restructure rendered output
        # plus the HTML-raw characters that matter when the Markdown is
        # later converted to HTML. Order-sensitive: backslash MUST be
        # escaped first so the subsequent replacements don't double-escape.
        for char in ("\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", "!", "<", ">"):
            sanitized = sanitized.replace(char, "\\" + char)
    return sanitized


# URL schemes allowed in operator-supplied URL fields rendered into
# regulated artefacts. Anything else — javascript:, data:, file:, ftp:,
# mailto: masquerading as a URL — is dropped to empty string so the
# template emits a blank link target instead of an attacker-controlled
# protocol handler.
_SAFE_URL_SCHEMES = ("http://", "https://")


def _sanitize_url(value: str) -> str:
    """Scheme-allowlist + control-char strip for URL-ish operator input.

    Fails closed on anything that doesn't start with ``http://`` or
    ``https://`` (case-insensitive) — a crafted value like
    ``text](javascript:alert(1))`` carries no allowed scheme and is
    dropped. Also rejects URLs whose literal body contains Markdown
    metacharacters (``[``, ``]``, ``(``, ``)``, whitespace, backticks)
    that real RFC 3986 URLs would percent-encode. Legitimate URLs pass
    through untouched so the template can render them as plain text.
    """
    cleaned = _sanitize(value or "")
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    matched_scheme = next((s for s in _SAFE_URL_SCHEMES if lowered.startswith(s)), None)
    if matched_scheme is None:
        return ""
    # Require at least one character of host after the scheme. ``http://``
    # alone would render as a visible-but-broken link in the DoC.
    if len(cleaned) <= len(matched_scheme):
        return ""
    # Reject URLs carrying Markdown-active characters. Real URLs
    # percent-encode these; anything leaking through is either malformed
    # or an injection attempt.
    if any(c in cleaned for c in '[]()`<>" '):
        return ""
    return cleaned


def _build_common_context(assessment: CRAAssessment) -> dict[str, Any]:
    """Build context shared across all templates."""
    product = assessment.product

    manufacturer = get_manufacturer(assessment.team)
    security_contact = get_security_contact(assessment.team)

    # Raw manufacturer name flows through the placeholder check BEFORE
    # markdown escaping — escaping would insert backslashes and make
    # ``\ acme`` look like a legitimate name to the predicate.
    raw_manufacturer_name = _sanitize(manufacturer.name) if manufacturer else ""
    manufacturer_is_placeholder = _is_placeholder_manufacturer(raw_manufacturer_name)
    # Render a visible marker rather than silently emitting a DoC with
    # "Manufacturer: ABC" — Annex V item 2 requires the legal name. The
    # template keeps the label visible so the gap is immediately obvious
    # to whoever reviews / signs the exported package. The marker string
    # is static and intentionally contains Markdown metacharacters
    # (``[`` / ``]``), so it MUST skip markdown-escape — escaping it
    # would garble the marker itself ("\[Manufacturer Name\]").
    if manufacturer_is_placeholder or manufacturer is None:
        manufacturer_name = "[Manufacturer Name — not configured]"
    else:
        # Safe to markdown-escape now that the placeholder check passed.
        # ``manufacturer`` is non-None here per the disjunction above —
        # the explicit guard keeps mypy happy and also documents that
        # ``manufacturer_is_placeholder`` is True whenever ``manufacturer``
        # is None (guaranteed by `` _sanitize(... or "") ``).
        manufacturer_name = _sanitize(manufacturer.name, escape_markdown=True)

    return {
        # Free-text operator fields — Markdown / HTML escaping enabled
        # so a team with ``product.name = "<script>alert(1)</script>"``
        # cannot inject payload into the rendered compliance artefacts.
        "product_name": _sanitize(product.name, escape_markdown=True),
        "product_description": _sanitize(product.description or "", escape_markdown=True),
        # UUID / ISO country codes / email-constrained fields come from
        # stricter validators upstream; we still collapse control chars
        # but don't markdown-escape (they can't contain metacharacters).
        "product_uuid": str(product.uuid),
        "intended_use": _sanitize(assessment.intended_use, escape_markdown=True),
        "target_eu_markets": [_sanitize(m)[:2].upper() for m in (assessment.target_eu_markets or [])],
        "support_period_end": (assessment.support_period_end.isoformat() if assessment.support_period_end else None),
        "manufacturer_name": manufacturer_name,
        "manufacturer_is_placeholder": manufacturer_is_placeholder,
        "manufacturer_address": _sanitize(manufacturer.address, escape_markdown=True) if manufacturer else "",
        "manufacturer_email": _sanitize(manufacturer.email) if manufacturer else "",
        "manufacturer_website": (
            _sanitize_url(str(manufacturer.website_urls[0])) if manufacturer and manufacturer.website_urls else ""
        ),
        "security_contact_email": _sanitize(security_contact.email) if security_contact else "",
        "security_contact_url": _sanitize_url(assessment.security_contact_url),
        "vdp_url": _sanitize_url(assessment.vdp_url),
        "csirt_contact_email": _sanitize(assessment.csirt_contact_email),
        "csirt_country": _sanitize(assessment.csirt_country)[:2].upper(),
        "acknowledgment_timeline_days": assessment.acknowledgment_timeline_days,
        "date": date.today().isoformat(),
        "version": "1.0",
        "assessment_id": assessment.id,
    }


def _build_risk_assessment_context(assessment: CRAAssessment, base: dict[str, Any]) -> dict[str, Any]:
    """Add findings grouped by control group for risk assessment."""
    findings = (
        OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result)
        .select_related("control")
        .order_by("control__sort_order")
    )

    groups: dict[str, list[dict[str, str]]] = {
        "cra-sd": [],
        "cra-dp": [],
        "cra-av": [],
        "cra-mn": [],
        "cra-vh": [],
    }
    counts = {"satisfied": 0, "not-satisfied": 0, "not-applicable": 0, "unanswered": 0}

    for f in findings:
        gid = f.control.group_id
        if gid in groups:
            groups[gid].append(
                {
                    "title": f.control.title,
                    "status": f.get_status_display(),
                    "notes": _sanitize(f.notes, escape_pipe=True) if f.notes else "",
                    "justification": _sanitize(f.justification, escape_pipe=True) if f.justification else "",
                }
            )
        counts[f.status] = counts.get(f.status, 0) + 1

    base["sd_findings"] = groups["cra-sd"]
    base["dp_findings"] = groups["cra-dp"]
    base["av_findings"] = groups["cra-av"]
    base["mn_findings"] = groups["cra-mn"]
    base["vh_findings"] = groups["cra-vh"]
    # Use underscored keys so Django template {{ summary.not_satisfied }} resolves correctly
    base["summary"] = {
        "total": sum(counts.values()),
        "satisfied": counts["satisfied"],
        "not_satisfied": counts["not-satisfied"],
        "not_applicable": counts["not-applicable"],
        "unanswered": counts["unanswered"],
    }
    return base


def _build_security_txt_context(assessment: CRAAssessment, base: dict[str, Any]) -> dict[str, Any]:
    """Build context for security.txt template."""
    # Build Preferred-Languages from target markets
    languages: set[str] = set()
    for country in assessment.target_eu_markets:
        for lang in _COUNTRY_LANGUAGE_MAP.get(country.upper(), "").split(","):
            if lang:
                languages.add(lang)
    # Always include English
    languages.add("en")
    base["preferred_languages"] = ", ".join(sorted(languages))

    # Expires: support_period_end + 1 year, or empty
    if assessment.support_period_end:
        end = assessment.support_period_end
        try:
            expires_date = end.replace(year=end.year + 1)
        except ValueError:
            # Feb 29 → Feb 28 in non-leap year
            expires_date = end.replace(year=end.year + 1, day=28)
        base["expires"] = expires_date.strftime("%Y-%m-%dT00:00:00.000Z")
    else:
        base["expires"] = ""

    base["hiring_url"] = ""
    return base


def _build_declaration_context(assessment: CRAAssessment, base: dict[str, Any]) -> dict[str, Any]:
    """Build context for declaration of conformity."""
    base["product_category_display"] = assessment.get_product_category_display()
    base["conformity_procedure_display"] = assessment.get_conformity_assessment_procedure_display()
    # Annex V item 6 requires the DoC to list the standards and
    # specifications applied. Populate from the reference JSON so every
    # DoC cites the CRA itself, the SBOM-format reference (BSI TR-03183-2),
    # and any harmonised standards the operator has opted into.
    base["applied_standards"] = _select_applied_standards(assessment)
    # Annex V item 7 — support period is part of the declaration scope
    # and must be visible on the DoC, not only in the risk assessment.
    base["support_period_end"] = assessment.support_period_end.isoformat() if assessment.support_period_end else None
    # Annex V item 8 — signature block. Pass through the captured
    # values so the template can render filled fields (in which case
    # the underscore placeholders are dropped). Text fields are
    # markdown-escaped because they're rendered into a Markdown
    # paragraph; ``signature_image`` is a static ``data:image/png``
    # URL and goes straight through — the API layer enforces the
    # data-URL prefix and a size cap.
    base["signature_place"] = _sanitize(assessment.signature_place, escape_markdown=True)
    base["signature_name"] = _sanitize(assessment.signature_name, escape_markdown=True)
    base["signature_function"] = _sanitize(assessment.signature_function, escape_markdown=True)
    base["signature_image"] = assessment.signature_image
    base["is_signed"] = assessment.is_signed
    return base


def _build_document_context(assessment: CRAAssessment, kind: str) -> dict[str, Any]:
    """Build the full template context for a document kind."""
    base = _build_common_context(assessment)

    if kind == CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT:
        base["product_category_display"] = assessment.get_product_category_display()
        return _build_risk_assessment_context(assessment, base)

    if kind == CRAGeneratedDocument.DocumentKind.SECURITY_TXT:
        return _build_security_txt_context(assessment, base)

    if kind == CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY:
        return _build_declaration_context(assessment, base)

    if kind == CRAGeneratedDocument.DocumentKind.USER_INSTRUCTIONS:
        # Annex II "Information and instructions to the user" — rendered
        # directly to the end user of the product, so operator input
        # MUST NOT carry Markdown / HTML injection into the emitted doc.
        # URLs go through URL-shape validation upstream; plain-text
        # fields (frequency, method, hours, instructions) are escaped.
        base["update_frequency"] = _sanitize(assessment.update_frequency or "", escape_markdown=True)
        base["update_method"] = _sanitize(assessment.update_method or "", escape_markdown=True)
        base["update_channel_url"] = _sanitize_url(assessment.update_channel_url or "")
        base["support_email"] = _sanitize(assessment.support_email or "")
        base["support_url"] = _sanitize_url(assessment.support_url or "")
        base["support_phone"] = _sanitize(assessment.support_phone or "", escape_markdown=True)
        base["support_hours"] = _sanitize(assessment.support_hours or "", escape_markdown=True)
        base["data_deletion_instructions"] = _sanitize(
            assessment.data_deletion_instructions or "", escape_markdown=True
        )
        return base

    if kind == CRAGeneratedDocument.DocumentKind.DECOMMISSIONING_GUIDE:
        base["data_deletion_instructions"] = _sanitize(
            assessment.data_deletion_instructions or "", escape_markdown=True
        )
        return base

    return base


def _render_template(kind: str, context: dict[str, Any]) -> str:
    """Render a Django template by document kind."""
    template_name = _TEMPLATE_MAP.get(kind)
    if not template_name:
        raise ValueError(f"Unknown document kind: {kind}")
    template = _engine.get_template(template_name)
    return template.render(Context(context))


def generate_document(
    assessment: CRAAssessment,
    kind: str,
) -> ServiceResult[CRAGeneratedDocument]:
    """Render a Django template, upload to S3, create/update CRAGeneratedDocument."""
    valid_kinds = {c[0] for c in CRAGeneratedDocument.DocumentKind.choices}
    if kind not in valid_kinds:
        return ServiceResult.failure(f"Unknown document kind: {kind}", status_code=400)

    try:
        context = _build_document_context(assessment, kind)
    except ReferenceDataError:
        # Regulated-evidence policy: the shipped harmonised-standards
        # JSON is missing or corrupt. Surface as an operator-actionable
        # 503 instead of a bare 500 so the wizard can render a toast
        # rather than a generic server error.
        logger.exception("CRA reference data missing or corrupt; blocking document generation")
        return ServiceResult.failure(
            "CRA reference data is missing or corrupt — contact your workspace admin.",
            status_code=503,
        )
    rendered = _render_template(kind, context)
    content_bytes = rendered.encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # Storage key
    storage_key = f"compliance/{assessment.id}/{kind}"
    if kind == CRAGeneratedDocument.DocumentKind.SECURITY_TXT:
        storage_key += ".txt"
    else:
        storage_key += ".md"

    # Upload to S3
    try:
        from sbomify.apps.core.object_store import S3Client

        s3 = S3Client("DOCUMENTS")
        from django.conf import settings as django_settings

        s3.upload_data_as_file(django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, storage_key, content_bytes)
    except Exception:
        logger.exception("Failed to upload document %s to S3", kind)
        return ServiceResult.failure("Failed to upload document to storage", status_code=502)

    # Create or update record
    doc, created = CRAGeneratedDocument.objects.get_or_create(
        assessment=assessment,
        document_kind=kind,
        defaults={
            "storage_key": storage_key,
            "content_hash": content_hash,
            "version": 1,
            "is_stale": False,
        },
    )

    if not created:
        doc.version += 1
        doc.storage_key = storage_key
        doc.content_hash = content_hash
        doc.is_stale = False
        doc.save()

    return ServiceResult.success(doc)


def regenerate_all(assessment: CRAAssessment) -> ServiceResult[int]:
    """Regenerate all document kinds. Returns count on full success, failure if any fail."""
    total = len(CRAGeneratedDocument.DocumentKind.choices)
    failed_kinds: list[str] = []
    count = 0
    for kind, _ in CRAGeneratedDocument.DocumentKind.choices:
        result = generate_document(assessment, kind)
        if result.ok:
            count += 1
        else:
            failed_kinds.append(kind)
    if failed_kinds:
        return ServiceResult.failure(
            f"Failed to generate {len(failed_kinds)}/{total} documents: {', '.join(failed_kinds)}",
            status_code=502,
        )
    return ServiceResult.success(count)


def regenerate_stale(assessment: CRAAssessment) -> ServiceResult[int]:
    """Regenerate only stale documents. Returns count."""
    stale_docs = CRAGeneratedDocument.objects.filter(assessment=assessment, is_stale=True)
    count = 0
    for doc in stale_docs:
        result = generate_document(assessment, doc.document_kind)
        if result.ok:
            count += 1
    return ServiceResult.success(count)


def get_document_preview(
    assessment: CRAAssessment,
    kind: str,
) -> ServiceResult[str]:
    """Render to string without persisting — for preview in wizard."""
    valid_kinds = {c[0] for c in CRAGeneratedDocument.DocumentKind.choices}
    if kind not in valid_kinds:
        return ServiceResult.failure(f"Unknown document kind: {kind}", status_code=400)

    try:
        context = _build_document_context(assessment, kind)
    except ReferenceDataError:
        logger.exception("CRA reference data missing or corrupt; blocking document preview")
        return ServiceResult.failure(
            "CRA reference data is missing or corrupt — contact your workspace admin.",
            status_code=503,
        )
    rendered = _render_template(kind, context)
    return ServiceResult.success(rendered)
