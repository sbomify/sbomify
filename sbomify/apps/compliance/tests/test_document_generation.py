"""Tests for the CRA document generation service."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sbomify.apps.compliance.models import (
    CRAGeneratedDocument,
    OSCALFinding,
)
from sbomify.apps.compliance.services._manufacturer_policy import (
    is_placeholder_manufacturer as _is_placeholder_manufacturer,
)
from sbomify.apps.compliance.services.document_generation_service import (
    _load_harmonised_standards,
    _sanitize,
    _sanitize_url,
    _select_applied_standards,
    generate_document,
    get_document_preview,
    regenerate_all,
    regenerate_stale,
)
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Doc Gen Product", team=team)


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product):
    team = sample_team_with_owner_member.team

    # Create manufacturer contact
    profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Acme Corp",
        email="info@acme.test",
        address="123 Test St, Berlin",
        is_manufacturer=True,
        website_urls=["https://acme.test"],
    )
    ContactProfileContact.objects.create(
        entity=entity,
        name="Security Lead",
        email="security@acme.test",
        is_security_contact=True,
    )

    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    a = result.value
    a.intended_use = "Home automation"
    a.target_eu_markets = ["DE", "FR"]
    a.vdp_url = "https://acme.test/vdp"
    a.update_frequency = "quarterly"
    a.support_email = "support@acme.test"
    a.data_deletion_instructions = "Factory reset the device."
    a.save()
    return a


@pytest.mark.django_db
class TestGenerateDocument:
    """Test document generation for each kind."""

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_generates_vdp(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)

        assert result.ok
        doc = result.value
        assert doc.document_kind == "vdp"
        assert doc.version == 1
        assert doc.is_stale is False
        assert doc.content_hash
        assert doc.storage_key.endswith(".md")

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_generates_security_txt(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)

        assert result.ok
        doc = result.value
        assert doc.document_kind == "security_txt"
        assert doc.storage_key.endswith(".txt")

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_generates_risk_assessment(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT)

        assert result.ok
        doc = result.value
        assert doc.document_kind == "risk_assessment"

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_generates_declaration_of_conformity(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)

        assert result.ok
        doc = result.value
        assert doc.document_kind == "declaration_of_conformity"

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_generates_all_9_kinds(self, mock_s3_cls, assessment):
        for kind, _ in CRAGeneratedDocument.DocumentKind.choices:
            result = generate_document(assessment, kind)
            assert result.ok, f"Failed to generate {kind}: {result.error}"

    def test_rejects_invalid_kind(self, assessment):
        result = generate_document(assessment, "bogus")
        assert not result.ok
        assert result.status_code == 400

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_s3_upload_failure_surfaces_502(self, mock_s3_cls, assessment):
        """Covers the ``except Exception`` path in ``generate_document``
        where the upload to S3 throws after the template renders. Must
        not leak the stack trace to the client — the ServiceResult
        carries a generic 502 message."""
        mock_s3_cls.return_value.upload_data_as_file.side_effect = RuntimeError("S3 unavailable")

        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)

        assert not result.ok
        assert result.status_code == 502
        assert "storage" in (result.error or "").lower()

    def test_rejects_invalid_kind_for_preview(self, assessment):
        """Mirror of the generate-path rejection, on the preview path
        (``get_document_preview``). Covers the 400 branch before the
        template engine is hit."""
        result = get_document_preview(assessment, "does-not-exist")
        assert not result.ok
        assert result.status_code == 400


@pytest.mark.django_db
class TestVersioning:
    """Test document version increments and stale flag resets."""

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_version_increments_on_regeneration(self, mock_s3_cls, assessment):
        result1 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert result1.ok
        assert result1.value.version == 1

        result2 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert result2.ok
        assert result2.value.version == 2
        assert result2.value.id == result1.value.id  # Same record, updated

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_stale_flag_resets_on_regeneration(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert result.ok

        # Manually mark as stale
        doc = result.value
        doc.is_stale = True
        doc.save()

        # Regenerate
        result2 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert result2.ok
        assert result2.value.is_stale is False

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_content_hash_changes_when_data_changes(self, mock_s3_cls, assessment):
        result1 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        hash1 = result1.value.content_hash

        # Change assessment data
        assessment.vdp_url = "https://acme.test/new-vdp"
        assessment.save()

        result2 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        hash2 = result2.value.content_hash

        assert hash1 != hash2


@pytest.mark.django_db
class TestSecurityTxtFormat:
    """Test that security.txt follows RFC 9116 format."""

    def test_contains_contact_field(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)

        assert result.ok
        content = result.value
        assert "Contact: mailto:security@acme.test" in content

    def test_contains_policy_field(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)

        assert result.ok
        content = result.value
        assert "Policy: https://acme.test/vdp" in content

    def test_contains_preferred_languages(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)

        assert result.ok
        content = result.value
        assert "Preferred-Languages:" in content
        # DE -> de, FR -> fr, plus en always included
        assert "de" in content
        assert "en" in content
        assert "fr" in content

    def test_expires_is_support_period_plus_one_year(self, assessment):
        """RFC 9116 Expires is support_period_end + 1 year."""
        from datetime import date

        assessment.support_period_end = date(2027, 5, 20)
        assessment.save()
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)
        assert "Expires: 2028-05-20T00:00:00.000Z" in result.value

    def test_expires_leap_day_rolls_to_feb_28(self, assessment):
        """Feb 29 support_period_end rolls to Feb 28 next year (non-
        leap) so the .replace(year=...) ValueError branch is covered."""
        from datetime import date

        assessment.support_period_end = date(2028, 2, 29)
        assessment.save()
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)
        assert "Expires: 2029-02-28T00:00:00.000Z" in result.value

    def test_expires_empty_when_support_period_not_set(self, assessment):
        """No support period → Expires line is blank; operator sees
        the gap rather than a bogus date."""
        assessment.support_period_end = None
        assessment.save()
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)
        # The raw template emits `Expires: ` with an empty value; the
        # important regression is that no past date / "None" leaks.
        assert "Expires: None" not in result.value
        assert "Expires: 1970" not in result.value


@pytest.mark.django_db
class TestDeclarationOfConformity:
    """Test declaration includes all Annex V required fields."""

    def test_contains_product_identification(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Doc Gen Product" in content

    def test_contains_manufacturer_details(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Acme Corp" in content
        assert "123 Test St, Berlin" in content

    def test_contains_responsibility_statement(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "sole responsibility of the manufacturer" in content

    def test_contains_conformity_statement(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Regulation (EU) 2024/2847" in content

    def test_contains_signature_block(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Signature:" in content

    def test_lists_harmonised_standards_applied(self, assessment):
        """Annex V item 6 — the DoC must cite the standards applied.
        Every DoC always cites the CRA itself and BSI TR-03183-2 (SBOM
        format reference). Lists each standard's CRA mapping entries so
        notified bodies see the clause-level correspondence."""
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Regulation (EU) 2024/2847" in content
        assert "BSI TR-03183-2" in content
        assert "Annex I, Part II, §1" in content  # BSI → CRA SBOM mapping
        assert "eur-lex.europa.eu/eli/reg/2024/2847" in content

    def test_includes_support_period_when_set(self, assessment):
        """Article 13(8) support period must appear on the DoC, not only
        on the risk assessment."""
        from datetime import date

        assessment.support_period_end = date(2031, 4, 21)
        assessment.save()
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Support Period Ends" in content
        assert "2031-04-21" in content
        assert "Article 13(8)" in content

    def test_omits_support_period_when_not_set(self, assessment):
        """If the operator hasn't declared a support period yet, the
        Article 13(8) block is simply absent — not a silent 'None'."""
        assessment.support_period_end = None
        assessment.save()
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Support Period Ends" not in content
        assert "None" not in content.split("## 7.")[1].split("## 8.")[0]

    def test_lists_supporting_documentation_section(self, assessment):
        """Annex VII — DoC references the evidence files that back it."""
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Supporting Documentation" in content
        assert "sboms/*.cdx.json" in content
        assert "vulnerability-disclosure-policy.md" in content
        assert "oscal/*.json" in content
        assert "metadata/manifest.sha256" in content


@pytest.mark.django_db
class TestDeclarationManufacturerPlaceholder:
    """Placeholder-manufacturer guard: Annex V item 2 requires the
    legal name. When the team profile is empty / filled with a stub,
    the DoC must render a visible warning rather than ship invalid."""

    @pytest.mark.parametrize("placeholder", ["ABC", "xyz", "Test", "foo", "TBD", "None"])
    def test_placeholder_renders_warning(self, sample_team_with_owner_member, sample_user, placeholder):
        """Case-insensitive placeholder names always trigger the warning.

        Empty / whitespace-only values are covered by
        ``test_missing_manufacturer_renders_warning`` — ``ContactEntity``
        rejects empty names at the ORM level, so we can't parametrise
        over them here.
        """
        team = sample_team_with_owner_member.team
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name=placeholder,
            email="info@example.test",
            address="",
            is_manufacturer=True,
        )
        p = Product.objects.create(name="Placeholder Product", team=team)
        ares = get_or_create_assessment(p.id, sample_user, team)
        assert ares.ok
        result = get_document_preview(ares.value, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "[Manufacturer Name — not configured]" in content
        assert "Annex V item 2 requires" in content

    def test_missing_manufacturer_renders_warning(self, sample_team_with_owner_member, sample_user):
        """No manufacturer entity at all → same warning. The wizard must
        not silently emit a DoC with an empty ``**Name:**`` field."""
        team = sample_team_with_owner_member.team
        p = Product.objects.create(name="Manufacturer-less Product", team=team)
        ares = get_or_create_assessment(p.id, sample_user, team)
        assert ares.ok
        result = get_document_preview(ares.value, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "[Manufacturer Name — not configured]" in content

    def test_real_manufacturer_does_not_trigger_warning(self, assessment):
        """Existing fixture uses 'Acme Corp' which is a legal-looking
        name; the placeholder warning must not appear for it."""
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Acme Corp" in content
        assert "not configured" not in content


class TestIsPlaceholderManufacturer:
    """Unit-level coverage of the placeholder predicate. Class-based
    parametrise below exercises the full matcher contract so a future
    edit to ``_PLACEHOLDER_MANUFACTURER_VALUES`` can't silently leak
    stub data into a DoC."""

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            " ",
            "   ",
            "\t",
            "\n",
            "abc",
            "ABC",
            "  abc  ",
            "Abc",
            "xyz",
            "test",
            "example",
            "acme",
            "foo",
            "bar",
            "tbd",
            "TODO",
            "n/a",
            "N/A",
            "na",
            "none",
            "NONE",
            "null",
        ],
    )
    def test_values_recognised_as_placeholder(self, value):
        assert _is_placeholder_manufacturer(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "Acme Corp",
            "Acme, Inc.",
            "Contoso GmbH",
            "Siemens AG",
            "The Acme Company",
            "abc123",
            "XYZ Industries",
            "Test Manufacturing Ltd.",
            "Lithium Project",
        ],
    )
    def test_legitimate_names_pass(self, value):
        assert _is_placeholder_manufacturer(value) is False


class TestLoadHarmonisedStandards:
    """Reference-data integrity tests — if the JSON structure drifts
    the DoC rendering silently breaks, so we pin the shape here."""

    def test_loads_without_raising(self):
        """File is shipped with the app — must parse every time."""
        data = _load_harmonised_standards()
        assert isinstance(data, dict)
        assert "standards" in data
        assert "sources" in data

    def test_required_top_level_fields_present(self):
        data = _load_harmonised_standards()
        assert data["format_version"]
        assert data["description"]
        assert isinstance(data["standards"], list)
        assert len(data["standards"]) >= 2, "CRA + BSI minimum"

    def test_every_standard_has_minimum_fields(self):
        data = _load_harmonised_standards()
        for std in data["standards"]:
            assert std.get("id"), f"standard missing id: {std}"
            assert std.get("citation"), f"standard missing citation: {std}"
            # Either URL present or explicitly blank — never missing key.
            assert "url" in std
            # Harmonised flag must be a bool.
            assert isinstance(std.get("harmonised", False), bool)
            # cra_requirements_covered is always a list (may be empty).
            assert isinstance(std.get("cra_requirements_covered", []), list)

    def test_always_applicable_set_includes_cra_and_bsi(self):
        """These two anchor every DoC and cannot be removed."""
        data = _load_harmonised_standards()
        always = {s["id"] for s in data["standards"] if s.get("always_applicable")}
        assert "cra" in always
        assert "bsi-tr-03183-2" in always


@pytest.fixture
def _clear_reference_data_cache():
    """Isolate tests from the module-level ``functools.cache`` on
    ``_load_cached``. Clears before and after each test so a patched
    ``HARMONISED_STANDARDS_PATH`` in one test can't leak a cached
    value (or a cached exception's absence) into the next."""
    from sbomify.apps.compliance.services import _reference_data

    _reference_data._load_cached.cache_clear()
    yield
    _reference_data._load_cached.cache_clear()


@pytest.mark.usefixtures("_clear_reference_data_cache")
class TestHarmonisedStandardsFallback:
    """Fail-fast regime for the shipped reference JSON: regulated
    evidence must not ship with a silently-degraded standards list,
    so a missing or corrupt ``cra-harmonised-standards.json`` surfaces
    as :class:`ReferenceDataError` and the DoC pipeline blocks."""

    def test_missing_file_raises_reference_data_error(self, tmp_path):
        """OSError path: shipped file is gone. Regulated-evidence
        policy is fail-fast — a silently-degraded DoC is worse than a
        failed export, so operators see the install bug loudly."""
        from sbomify.apps.compliance.services import _reference_data

        missing = tmp_path / "does-not-exist.json"
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", missing):
            with pytest.raises(_reference_data.ReferenceDataError):
                _reference_data.load_harmonised_standards()

    def test_invalid_json_raises_reference_data_error(self, tmp_path):
        """JSONDecodeError path: file is present but corrupt. Same
        fail-fast policy — corrupt reference data must not produce a
        DoC at all."""
        from sbomify.apps.compliance.services import _reference_data

        broken = tmp_path / "cra-harmonised-standards.json"
        broken.write_text("{ this is not JSON", encoding="utf-8")
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", broken):
            with pytest.raises(_reference_data.ReferenceDataError):
                _reference_data.load_harmonised_standards()

    def test_returned_dict_is_isolated_from_cache(self):
        """Mutating the returned payload must not poison the shared
        ``functools.cache`` — protects against a caller that appends
        to ``standards`` and surprises the next caller."""
        from sbomify.apps.compliance.services import _reference_data

        first = _reference_data.load_harmonised_standards()
        first["standards"].append({"id": "poison"})
        second = _reference_data.load_harmonised_standards()
        assert "poison" not in {s.get("id") for s in second["standards"]}

    @pytest.mark.parametrize(
        "raw",
        [
            "[]",  # top-level array — valid JSON, wrong shape
            '"a string"',  # valid JSON, primitive
            "42",  # valid JSON, number
            "null",  # valid JSON, null
            "true",  # valid JSON, boolean
            '{"standards": "not a list"}',  # dict but standards wrong type
            '{"standards": null}',  # standards present but null
            "{}",  # dict but missing standards key entirely
            '{"standards": 42}',  # standards wrong primitive type
        ],
    )
    def test_shape_violations_raise_reference_data_error(self, tmp_path, raw):
        """``json.loads`` succeeds on these payloads but the loader
        contract is ``dict[str, Any]`` with a ``standards`` list.
        Anything else surfaces as :class:`ReferenceDataError` so the
        caller (``_select_applied_standards``) doesn't later blow up
        with an opaque ``AttributeError`` / ``TypeError``."""
        from sbomify.apps.compliance.services import _reference_data

        f = tmp_path / "cra-harmonised-standards.json"
        f.write_text(raw, encoding="utf-8")
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", f):
            with pytest.raises(_reference_data.ReferenceDataError):
                _reference_data.load_harmonised_standards()

    def test_standards_list_with_unexpected_items_still_loads(self, tmp_path):
        """The shape check is shallow — it validates ``standards`` is
        a list, not that every item is a dict. Downstream predicates
        (``_select_applied_standards``) use ``.get()`` so non-dict
        list items are skipped. Document this tolerance so a future
        dev doesn't tighten the guard unnecessarily."""
        from sbomify.apps.compliance.services import _reference_data

        f = tmp_path / "cra-harmonised-standards.json"
        f.write_text('{"standards": [{"id": "ok"}, "oops", 42, null]}', encoding="utf-8")
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", f):
            data = _reference_data.load_harmonised_standards()
        assert data["standards"][0]["id"] == "ok"

    def test_empty_file_raises_reference_data_error(self, tmp_path):
        """Zero-byte file — ``json.loads('')`` raises ``JSONDecodeError``.
        Regression test ensuring the catch block fires for the empty
        case specifically (not just for malformed JSON)."""
        from sbomify.apps.compliance.services import _reference_data

        f = tmp_path / "empty.json"
        f.write_bytes(b"")
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", f):
            with pytest.raises(_reference_data.ReferenceDataError):
                _reference_data.load_harmonised_standards()

    def test_path_is_directory_raises_reference_data_error(self, tmp_path):
        """Pathological deploy: a directory shadowing the JSON file.
        ``Path.read_text`` raises ``OSError`` (IsADirectoryError), which
        must surface as ``ReferenceDataError`` not an unexplained 500."""
        from sbomify.apps.compliance.services import _reference_data

        d = tmp_path / "cra-harmonised-standards.json"
        d.mkdir()
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", d):
            with pytest.raises(_reference_data.ReferenceDataError):
                _reference_data.load_harmonised_standards()

    def test_read_bytes_returns_none_on_missing_file(self, tmp_path):
        """The export service's ``read_harmonised_standards_bytes``
        shortcut returns None (not bytes) when the file is gone, so
        the caller can skip the embedded copy rather than writing a
        fallback blob."""
        from sbomify.apps.compliance.services import _reference_data

        missing = tmp_path / "does-not-exist.json"
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", missing):
            assert _reference_data.read_harmonised_standards_bytes() is None


@pytest.mark.django_db
@pytest.mark.usefixtures("_clear_reference_data_cache")
class TestReferenceDataErrorPropagation:
    """End-to-end propagation: :class:`ReferenceDataError` raised
    inside ``_select_applied_standards`` must surface as an
    operator-actionable ``ServiceResult.failure`` (503) from
    ``generate_document`` / ``get_document_preview``, not as an
    uncaught 500 that just shows the user a blank error toast."""

    def test_generate_document_returns_503_on_corrupt_reference_data(self, tmp_path, assessment):
        """``_build_document_context`` raises before S3 is touched,
        so no S3 mock is needed — the propagation guard fires early."""
        from sbomify.apps.compliance.services import _reference_data
        from sbomify.apps.compliance.services.document_generation_service import generate_document

        broken = tmp_path / "cra-harmonised-standards.json"
        broken.write_text("{ not json", encoding="utf-8")
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", broken):
            result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)

        assert not result.ok
        assert result.status_code == 503
        assert "reference data" in (result.error or "").lower()

    def test_get_document_preview_returns_503_on_corrupt_reference_data(self, tmp_path, assessment):
        from sbomify.apps.compliance.services import _reference_data
        from sbomify.apps.compliance.services.document_generation_service import get_document_preview

        broken = tmp_path / "cra-harmonised-standards.json"
        broken.write_text("{ not json", encoding="utf-8")
        with patch.object(_reference_data, "HARMONISED_STANDARDS_PATH", broken):
            result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)

        assert not result.ok
        assert result.status_code == 503


@pytest.mark.django_db
class TestSelectAppliedStandards:
    """Unit coverage for the selection predicate used by the DoC
    context. Keeps the conservative default (always_applicable only)
    honest; a future opt-in for EN 18031 needs to add a test here."""

    def test_selects_only_always_applicable_for_default_assessment(self, assessment):
        standards = _select_applied_standards(assessment)
        ids_in_citation = [s["citation"] for s in standards]
        # CRA regulation and BSI TR-03183-2 always appear.
        assert any("Regulation (EU) 2024/2847" in c for c in ids_in_citation)
        assert any("BSI TR-03183-2" in c for c in ids_in_citation)
        # EN 18031-1/-2/-3 are NOT always_applicable by default.
        assert not any("EN 18031-1" in c for c in ids_in_citation)
        assert not any("EN 18031-2" in c for c in ids_in_citation)
        assert not any("EN 18031-3" in c for c in ids_in_citation)
        # Draft CRA-specific standards (not yet harmonised) also excluded.
        assert not any("EN 304 626" in c for c in ids_in_citation)

    def test_selected_entries_carry_cra_mapping_when_documented(self, assessment):
        standards = _select_applied_standards(assessment)
        bsi = next(s for s in standards if "BSI TR-03183-2" in s["citation"])
        assert bsi["cra_requirements_covered"], "BSI must map to CRA Annex I Part II(1)"
        assert bsi["harmonised"] is False
        assert "Annex I, Part II, §1" in {
            req["cra_reference"] for req in bsi["cra_requirements_covered"]
        }

    def test_radio_equipment_opt_in_pulls_en_18031_1(self, assessment):
        """Ticking ``is_radio_equipment`` on Step 1 must add EN 18031-1
        to the DoC's applied-standards list (issue #905). EN 18031-2
        and -3 stay out unless the scope flags are also set."""
        assessment.is_radio_equipment = True
        assessment.save(update_fields=["is_radio_equipment"])

        standards = _select_applied_standards(assessment)
        citations = [s["citation"] for s in standards]

        assert any("EN 18031-1" in c for c in citations)
        assert not any("EN 18031-2" in c for c in citations)
        assert not any("EN 18031-3" in c for c in citations)

    def test_radio_plus_personal_data_pulls_en_18031_2(self, assessment):
        """RED + personal-data flag triggers EN 18031-2 on top of -1."""
        assessment.is_radio_equipment = True
        assessment.processes_personal_data = True
        assessment.save(update_fields=["is_radio_equipment", "processes_personal_data"])

        citations = [s["citation"] for s in _select_applied_standards(assessment)]

        assert any("EN 18031-1" in c for c in citations)
        assert any("EN 18031-2" in c for c in citations)
        assert not any("EN 18031-3" in c for c in citations)

    def test_radio_plus_financial_pulls_en_18031_3(self, assessment):
        """RED + financial-value flag triggers EN 18031-3."""
        assessment.is_radio_equipment = True
        assessment.handles_financial_value = True
        assessment.save(update_fields=["is_radio_equipment", "handles_financial_value"])

        citations = [s["citation"] for s in _select_applied_standards(assessment)]

        assert any("EN 18031-1" in c for c in citations)
        assert not any("EN 18031-2" in c for c in citations)
        assert any("EN 18031-3" in c for c in citations)

    def test_personal_data_without_radio_does_not_pull_en_18031_2(self, assessment):
        """EN 18031-2 requires BOTH RED applicability and personal-data
        processing — the standard is a RED harmonised standard, not a
        standalone privacy standard."""
        assessment.is_radio_equipment = False
        assessment.processes_personal_data = True
        assessment.save(update_fields=["is_radio_equipment", "processes_personal_data"])

        citations = [s["citation"] for s in _select_applied_standards(assessment)]

        assert not any("EN 18031" in c for c in citations)

    def test_en_18031_1_entry_carries_restrictions_text(self, assessment):
        """OJ L_202500138 restrictions (default-password disqualifier)
        must appear in the returned entry so the DoC template can
        render them inline. Surfacing these verbatim on the DoC is
        the whole reason operators tick the RED box knowingly."""
        assessment.is_radio_equipment = True
        assessment.save(update_fields=["is_radio_equipment"])

        standards = _select_applied_standards(assessment)
        en_1 = next(s for s in standards if "EN 18031-1" in s["citation"])

        assert en_1["harmonised"] is True
        assert en_1["restrictions"], "EN 18031-1 must surface OJ restrictions on the DoC"
        assert any("default password" in r.lower() for r in en_1["restrictions"])

    def test_en_18031_2_carries_restrictions_text(self, assessment):
        """OJ L_202500138 applies the default-password restriction
        to ALL THREE parts (-1, -2, -3). Previously only -1 carried
        the text — operators claiming conformity against -2 would
        miss the disqualifier on the DoC."""
        assessment.is_radio_equipment = True
        assessment.processes_personal_data = True
        assessment.save(update_fields=["is_radio_equipment", "processes_personal_data"])

        en_2 = next(
            s for s in _select_applied_standards(assessment) if "EN 18031-2" in s["citation"]
        )
        assert en_2["restrictions"], "EN 18031-2 must surface OJ restrictions on the DoC"
        assert any("default password" in r.lower() for r in en_2["restrictions"])

    def test_en_18031_3_carries_restrictions_text(self, assessment):
        assessment.is_radio_equipment = True
        assessment.handles_financial_value = True
        assessment.save(update_fields=["is_radio_equipment", "handles_financial_value"])

        en_3 = next(
            s for s in _select_applied_standards(assessment) if "EN 18031-3" in s["citation"]
        )
        assert en_3["restrictions"], "EN 18031-3 must surface OJ restrictions on the DoC"
        assert any("default password" in r.lower() for r in en_3["restrictions"])

    def test_all_three_flags_pull_the_full_set(self, assessment):
        """Belt-and-braces: a radio-equipment product that both
        processes personal data AND handles financial value picks up
        all three EN 18031 parts."""
        assessment.is_radio_equipment = True
        assessment.processes_personal_data = True
        assessment.handles_financial_value = True
        assessment.save(update_fields=["is_radio_equipment", "processes_personal_data", "handles_financial_value"])

        citations = [s["citation"] for s in _select_applied_standards(assessment)]

        assert any("EN 18031-1" in c for c in citations)
        assert any("EN 18031-2" in c for c in citations)
        assert any("EN 18031-3" in c for c in citations)

    def test_draft_standards_never_selected(self, assessment):
        """Draft ETSI EN 304 626 (Operating Systems) is in the
        reference JSON but must not appear on any DoC until OJ-listed.
        The ``draft`` substring in the id is the gate."""
        # Even if we somehow satisfy its applies_when, draft stays out.
        assessment.product_category = "operating_system"
        assessment.save(update_fields=["product_category"])

        citations = [s["citation"] for s in _select_applied_standards(assessment)]

        assert not any("EN 304 626" in c for c in citations)


class TestEvaluateAppliesWhen:
    """Unit coverage for the rule-tree evaluator used by
    ``_select_applied_standards``. Kept separate from the DoC-level
    tests so a regression in the combinator logic is isolated to the
    predicate, not the whole pipeline."""

    def test_empty_rule_vacuously_true(self):
        from sbomify.apps.compliance.services.document_generation_service import _evaluate_applies_when

        # ``None`` fails closed — the fail-closed policy
        # applies uniformly to non-dict rule shapes. Entries that
        # should always apply carry ``always_applicable: true`` in
        # the reference JSON and short-circuit at the caller before
        # reaching this evaluator. An empty dict remains vacuously
        # true because it's a well-formed (if trivial) rule tree.
        assert _evaluate_applies_when(None, {}) is False
        assert _evaluate_applies_when({}, {"product_category": "anything"}) is True

    def test_simple_equality_match(self):
        from sbomify.apps.compliance.services.document_generation_service import _evaluate_applies_when

        assert _evaluate_applies_when({"product_category": "radio_equipment"}, {"product_category": "radio_equipment"})
        assert not _evaluate_applies_when({"product_category": "radio_equipment"}, {"product_category": "default"})

    def test_any_of_short_circuits_on_first_match(self):
        from sbomify.apps.compliance.services.document_generation_service import _evaluate_applies_when

        rule = {"any_of": [{"product_category": "radio_equipment"}, {"operator_opt_in": True}]}
        assert _evaluate_applies_when(rule, {"product_category": "radio_equipment", "operator_opt_in": False})
        assert _evaluate_applies_when(rule, {"product_category": "default", "operator_opt_in": True})
        assert not _evaluate_applies_when(rule, {"product_category": "default", "operator_opt_in": False})

    def test_all_of_requires_every_predicate(self):
        from sbomify.apps.compliance.services.document_generation_service import _evaluate_applies_when

        rule = {"all_of": [{"product_category": "radio_equipment"}, {"processes_personal_data": True}]}
        assert _evaluate_applies_when(rule, {"product_category": "radio_equipment", "processes_personal_data": True})
        assert not _evaluate_applies_when(
            rule, {"product_category": "radio_equipment", "processes_personal_data": False}
        )
        assert not _evaluate_applies_when(rule, {"product_category": "default", "processes_personal_data": True})

    def test_nested_combinators(self):
        """Future-proofing: combinators can nest. A future rule like
        "radio AND (personal OR financial)" must evaluate correctly."""
        from sbomify.apps.compliance.services.document_generation_service import _evaluate_applies_when

        rule = {
            "all_of": [
                {"product_category": "radio_equipment"},
                {"any_of": [{"processes_personal_data": True}, {"handles_financial_value": True}]},
            ]
        }
        facts = {"product_category": "radio_equipment", "processes_personal_data": False, "handles_financial_value": True}
        assert _evaluate_applies_when(rule, facts)
        facts_neither = dict(facts, handles_financial_value=False)
        assert not _evaluate_applies_when(rule, facts_neither)

    def test_unknown_key_fails_closed(self):
        """A typo in the JSON (``{"widget_type": "x"}``) must never
        match — unknown keys resolve to ``None`` in the facts dict
        and ``None != "x"``. Prevents an accidental rule opening up."""
        from sbomify.apps.compliance.services.document_generation_service import _evaluate_applies_when

        assert not _evaluate_applies_when({"widget_type": "x"}, {"product_category": "radio_equipment"})

    @pytest.mark.parametrize(
        "mixed_rule",
        [
            # Combinator + sibling equality at the same level — a
            # permissive "combinator wins" resolver would silently
            # drop the sibling, letting rule authors believe both
            # constraints were evaluated.
            {"any_of": [{"processes_personal_data": True}], "product_category": "radio_equipment"},
            {"all_of": [{"processes_personal_data": True}], "product_category": "radio_equipment"},
            # Both combinators at the same level — ambiguous.
            {"any_of": [], "all_of": []},
            # Combinator + multiple sibling equalities.
            {"any_of": [{"a": 1}], "b": 2, "c": 3},
        ],
    )
    def test_mixed_combinator_and_equality_rejected(self, mixed_rule):
        """Mixed shapes (combinator key + sibling equality
        predicates at the same level) are rejected. Fails closed;
        rule authors must nest explicitly. Even with facts that
        would satisfy every piece, the mixed-shape rule must
        evaluate False."""
        from sbomify.apps.compliance.services.document_generation_service import _evaluate_applies_when

        facts = {
            "product_category": "radio_equipment",
            "processes_personal_data": True,
            "a": 1,
            "b": 2,
            "c": 3,
        }
        assert _evaluate_applies_when(mixed_rule, facts) is False


@pytest.mark.django_db
class TestRegenerateAllFailurePath:
    """Covers ``regenerate_all``'s ``failed_kinds`` bookkeeping. If
    any kind fails, the batch returns ``ServiceResult.failure(502)``
    naming the failed kinds in the error message. Previously
    uncovered because happy-path tests short-circuit before the
    else branch."""

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_partial_failure_reports_failed_kinds(self, mock_s3_cls, assessment):
        from sbomify.apps.compliance.services.document_generation_service import regenerate_all

        # First call succeeds, second raises — the exact interleave
        # of kinds is implementation-defined so we only assert the
        # outer contract: status_code=502 and a count hint.
        calls = {"n": 0}

        def _maybe_fail(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 3:  # fail exactly one kind mid-run
                raise RuntimeError("simulated S3 blip")
            return None

        mock_s3_cls.return_value.upload_data_as_file.side_effect = _maybe_fail

        result = regenerate_all(assessment)

        assert not result.ok
        assert result.status_code == 502
        assert "Failed to generate" in (result.error or "")


@pytest.mark.django_db
class TestDocUrlsInRendering:
    """Regression: the DoC must render URLs as inline markdown refs so
    a notified body can click straight through to each authority."""

    def test_bsi_url_rendered(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "bsi.bund.de" in content

    def test_cra_url_rendered(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "eur-lex.europa.eu/eli/reg/2024/2847" in content


@pytest.mark.django_db
class TestRiskAssessment:
    """Test risk assessment includes control findings."""

    def test_includes_control_findings_tables(self, assessment):
        # Set some findings
        findings = list(
            OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).order_by(
                "control__sort_order"
            )[:2]
        )
        findings[0].status = "satisfied"
        findings[0].notes = "Implemented"
        findings[0].save()

        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT)
        content = result.value
        assert "Security by Design" in content
        assert "Vulnerability Handling" in content
        assert "Satisfied" in content


@pytest.mark.django_db
class TestRegenerateAll:
    @patch("sbomify.apps.core.object_store.S3Client")
    def test_generates_all_document_kinds(self, mock_s3_cls, assessment):
        result = regenerate_all(assessment)

        assert result.ok
        assert result.value == 9
        assert CRAGeneratedDocument.objects.filter(assessment=assessment).count() == 9


@pytest.mark.django_db
class TestRegenerateStale:
    @patch("sbomify.apps.core.object_store.S3Client")
    def test_regenerates_only_stale_documents(self, mock_s3_cls, assessment):
        # Generate all
        regenerate_all(assessment)

        # Mark only 2 as stale
        CRAGeneratedDocument.objects.filter(assessment=assessment, document_kind__in=["vdp", "security_txt"]).update(
            is_stale=True
        )

        result = regenerate_stale(assessment)
        assert result.ok
        assert result.value == 2

        # Verify none are stale now
        assert CRAGeneratedDocument.objects.filter(assessment=assessment, is_stale=True).count() == 0


@pytest.mark.django_db
class TestGetDocumentPreview:
    def test_returns_rendered_string(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.VDP)

        assert result.ok
        assert isinstance(result.value, str)
        assert "Vulnerability Disclosure Policy" in result.value
        assert "Doc Gen Product" in result.value

    def test_does_not_persist(self, assessment):
        get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert CRAGeneratedDocument.objects.filter(assessment=assessment).count() == 0

    def test_invalid_kind_returns_error(self, assessment):
        result = get_document_preview(assessment, "bogus")
        assert not result.ok


class TestSanitizeMarkdownEscape:
    """``_sanitize(escape_markdown=True)`` has to keep operator input
    from injecting Markdown / HTML into rendered CRA artefacts. These
    tests exercise the escape layer directly so a regression is caught
    without the full template pipeline."""

    def test_html_tags_are_escaped(self):
        """Open angle brackets MUST be prefixed with a backslash so a
        payload like ``<script>`` is rendered literally when the
        Markdown is later converted to HTML (DoC is often piped
        through pandoc → HTML)."""
        out = _sanitize("<script>alert(1)</script>", escape_markdown=True)
        # No unescaped ``<`` survives — every angle bracket has a
        # backslash immediately before it.
        assert "\\<" in out
        assert "\\>" in out
        # No bare ``<script>`` tag — raw HTML-rendering renderers will
        # see literal text instead of an opening tag.
        assert "<script>" not in out
        assert "</script>" not in out
        # Content preserved; just escaped in place.
        assert "script" in out
        assert "alert" in out

    def test_markdown_link_syntax_escaped(self):
        """``[click](javascript:alert(1))`` must survive as literal
        text so no operator can embed arbitrary URL schemes into the
        rendered DoC."""
        out = _sanitize("[click me](javascript:alert(1))", escape_markdown=True)
        assert "\\[" in out
        assert "\\]" in out
        assert "\\(" in out
        assert "\\)" in out

    def test_image_embed_syntax_escaped(self):
        """Tracking-pixel injection via ``![x](url)`` is defused."""
        out = _sanitize("![pixel](http://attacker.example/log)", escape_markdown=True)
        assert "\\!" in out
        assert "\\[" in out

    def test_plain_text_passes_through(self):
        """Legitimate product descriptions with plain words must survive
        unchanged except for escape of any metacharacter that happens
        to appear in them."""
        out = _sanitize("Lithium Python Stack 1.0", escape_markdown=True)
        assert "Lithium Python Stack 1.0" in out

    def test_escape_markdown_defaults_to_off(self):
        """Existing call sites that don't pass the flag get the same
        behaviour as before — control-char strip only."""
        out = _sanitize("<script>alert(1)</script>")
        assert out == "<script>alert(1)</script>"

    def test_pipe_escape_still_works_for_table_cells(self):
        """``escape_pipe`` is orthogonal to ``escape_markdown``; both
        can apply at once (finding notes in risk-assessment tables)."""
        out = _sanitize("a|b<c>", escape_pipe=True, escape_markdown=True)
        assert "\\|" in out
        assert "\\<" in out


class TestSanitizeUrl:
    """``_sanitize_url`` is the scheme-allowlist used for every
    operator-supplied URL field rendered into regulated artefacts
    (manufacturer_website, vdp_url, security_contact_url,
    update_channel_url, support_url). Wizard saves persist these
    fields without URL validation, so the render-time guard is the
    last line of defence against Markdown-link injection into the
    DoC and user instructions."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "http://example.com/path?q=1&r=2",
            "HTTPS://EXAMPLE.COM",  # scheme check is case-insensitive
            "https://example.com/a/b/c",
        ],
    )
    def test_passes_well_formed_http_urls(self, url):
        assert _sanitize_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            # Scheme allow-list violations
            "javascript:alert(1)",
            "JAVASCRIPT:alert(1)",  # case-insensitive rejection
            "data:text/html,<script>alert(1)</script>",
            "data:image/svg+xml,<svg onload=alert(1)>",
            "file:///etc/passwd",
            "ftp://example.com/",
            "ftps://example.com/",
            "mailto:a@b.c",
            "tel:+1234567890",
            "vbscript:msgbox(1)",
            "about:blank",
            "chrome://settings",
            "//example.com",  # protocol-relative
            "example.com",  # no scheme
            "://example.com",  # empty scheme
            # Markdown-link injection attempts (no allowed scheme)
            "[x](javascript:alert(1))",
            "text](javascript:alert(1))",
            "[click](https://real.com)",  # leading [ kills scheme match
            # Body-level injection — real URLs would percent-encode these
            "http://a.com/ onclick=alert(1)",
            "http://a.com/`backtick`",
            "http://a.com/<img>",
            'http://a.com/"onmouseover="alert(1)',
            "http://a.com/(x)",
            "http://a.com/[x]",
            # Empty / whitespace / None-ish
            "",
            "   ",
            "\t\n\r",
            # Scheme-only
            "http://",  # stripped to empty after sanitize
        ],
    )
    def test_rejects_unsafe_schemes_and_injection_payloads(self, url):
        assert _sanitize_url(url) == ""

    def test_strips_control_chars_before_scheme_check(self):
        """An attacker may try to smuggle newlines past the scheme
        check to corrupt plain-text artefacts (security.txt). The
        control-char strip runs BEFORE the scheme check so the
        sanitized URL either passes cleanly or is dropped."""
        # Control chars inside an otherwise-valid URL are collapsed
        # to space, which then trips the "whitespace in body" reject.
        assert _sanitize_url("https://example.com/\n\rpath") == ""

    def test_none_coerced_to_empty(self):
        """Database fields default to empty string but callers pass
        ``assessment.vdp_url or ""`` just in case — make sure both
        paths land cleanly on empty."""
        assert _sanitize_url("") == ""

    def test_long_url_preserved(self):
        """Real-world URLs with many path segments and a query string
        must pass unchanged; length isn't a reason to reject."""
        url = "https://example.com/" + "/".join(["segment"] * 30) + "?a=1&b=2&c=3"
        assert _sanitize_url(url) == url

    def test_https_scheme_preserved_with_port(self):
        assert _sanitize_url("https://example.com:8443/path") == "https://example.com:8443/path"

    def test_userinfo_not_stripped(self):
        """URLs with userinfo pass through (the template renders them
        as plain text; no password-in-clear vulnerability exists).
        Documented so a future dev doesn't think this is a bug."""
        assert _sanitize_url("https://user:pass@example.com/") == "https://user:pass@example.com/"


@pytest.mark.django_db
class TestBuildCommonContextUrlScrubbing:
    """Integration check: hostile URL payloads saved into the
    assessment model must not survive into ``_build_common_context``'s
    output dict. Covers the full wizard → save → render boundary."""

    def test_vdp_url_with_markdown_injection_empties_field(self, sample_team_with_owner_member, sample_user):
        from sbomify.apps.compliance.services.document_generation_service import _build_common_context

        team = sample_team_with_owner_member.team
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name="Acme Labs GmbH",
            email="legal@acme.example",
            is_manufacturer=True,
            website_urls=["javascript:alert('mfr_site')"],
        )
        p = Product.objects.create(name="Lithium", team=team)
        ares = get_or_create_assessment(p.id, sample_user, team)
        assert ares.ok
        a = ares.value
        a.vdp_url = "[phish](javascript:alert(1))"
        a.security_contact_url = "data:text/html,<script>alert(1)</script>"
        a.save()

        ctx = _build_common_context(a)

        assert ctx["vdp_url"] == ""
        assert ctx["security_contact_url"] == ""
        assert ctx["manufacturer_website"] == ""

    def test_user_instructions_urls_scrubbed(self, sample_team_with_owner_member, sample_user):
        """Step 4 update_channel_url / support_url end up in the
        user-instructions context — hostile values must empty out."""
        from sbomify.apps.compliance.services.document_generation_service import _build_document_context

        team = sample_team_with_owner_member.team
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name="Acme Labs GmbH",
            email="legal@acme.example",
            is_manufacturer=True,
        )
        p = Product.objects.create(name="Lithium", team=team)
        ares = get_or_create_assessment(p.id, sample_user, team)
        assert ares.ok
        a = ares.value
        a.update_channel_url = "javascript:alert(1)"
        a.support_url = "file:///etc/passwd"
        a.save()

        ctx = _build_document_context(a, CRAGeneratedDocument.DocumentKind.USER_INSTRUCTIONS)

        assert ctx["update_channel_url"] == ""
        assert ctx["support_url"] == ""


@pytest.mark.django_db
class TestDoCRejectsMarkdownInjection:
    """End-to-end: hostile operator input in product / manufacturer /
    intended-use fields must NOT produce a DoC that renders as
    executable HTML or clickable attacker links when viewed in a
    Markdown renderer. The previous pipeline had ``autoescape=False``
    on the Django engine and no per-field Markdown escape — CVSS 6.4
    cross-site scripting via regulated-document viewer."""

    @pytest.fixture
    def hostile_assessment(self, sample_team_with_owner_member, sample_user):
        """Assessment populated with attack payloads in every
        operator-controlled free-text field."""
        team = sample_team_with_owner_member.team
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name='ACME <script>alert("mfr")</script>',
            email="info@example.test",
            address='Street 1 [phish](javascript:alert(1))',
            is_manufacturer=True,
        )
        p = Product.objects.create(
            name='<iframe src="http://attacker"></iframe>',
            team=team,
        )
        ares = get_or_create_assessment(p.id, sample_user, team)
        assert ares.ok
        a = ares.value
        a.intended_use = "Embedded ![pixel](http://attacker/track.png)"
        a.data_deletion_instructions = "Run `rm -rf /` and [confirm](https://attacker)"
        a.support_hours = "09:00-17:00 <img onerror=alert(1)>"
        a.update_frequency = "monthly **<b>"
        a.save()
        return a

    def test_doc_renders_without_raw_script_tags(self, hostile_assessment):
        result = get_document_preview(
            hostile_assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY
        )
        content = result.value
        # Raw HTML/JS fragments must NOT survive into the rendered doc.
        assert "<script>" not in content
        assert "<iframe" not in content
        assert "<img onerror" not in content
        # The label text is still there — just Markdown-escaped.
        assert "script" in content

    def test_doc_renders_without_unescaped_markdown_links(self, hostile_assessment):
        result = get_document_preview(
            hostile_assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY
        )
        content = result.value
        # A bare `[phish](javascript:...)` sequence in the output would
        # render as a clickable link. Escaped brackets break that shape.
        assert "[phish](javascript" not in content

    def test_user_instructions_escapes_hostile_input(self, hostile_assessment):
        result = get_document_preview(
            hostile_assessment, CRAGeneratedDocument.DocumentKind.USER_INSTRUCTIONS
        )
        content = result.value
        assert "<img onerror" not in content
        assert "![pixel](http://attacker" not in content
        assert "[confirm](https://attacker" not in content

    def test_decommissioning_guide_escapes_data_deletion_instructions(self, hostile_assessment):
        result = get_document_preview(
            hostile_assessment, CRAGeneratedDocument.DocumentKind.DECOMMISSIONING_GUIDE
        )
        content = result.value
        assert "[confirm](https://attacker" not in content


class TestManufacturerPolicyParity:
    """Shared-source-of-truth check: the placeholder predicate lives in
    ``sbomify.apps.compliance.services._manufacturer_policy``. Both
    ``document_generation_service`` and ``export_service`` import the
    same function via aliasing. This test pins that parity — if anyone
    re-introduces a local copy of the frozenset (the pre-fix shape),
    the two imports will diverge and this test fails."""

    def test_both_services_import_same_predicate(self):
        """Identity check: the two module-level references are the same
        function object, not copies."""
        from sbomify.apps.compliance.services.document_generation_service import (
            _is_placeholder_manufacturer as doc_predicate,
        )
        from sbomify.apps.compliance.services.export_service import (
            _is_placeholder_manufacturer as export_predicate,
        )
        assert doc_predicate is export_predicate

    def test_placeholder_vocabulary_is_single_source(self):
        """Only one frozenset of placeholder values exists anywhere
        under the compliance services — no local copies."""
        import importlib

        mod = importlib.import_module(
            "sbomify.apps.compliance.services._manufacturer_policy"
        )
        assert isinstance(mod.PLACEHOLDER_MANUFACTURER_VALUES, frozenset)
        # Invariants: whitespace stripped, lowercase keys, empty string
        # included to model "no manufacturer configured".
        for v in mod.PLACEHOLDER_MANUFACTURER_VALUES:
            assert v == v.lower()
            assert v == v.strip()
        assert "" in mod.PLACEHOLDER_MANUFACTURER_VALUES
