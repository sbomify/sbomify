"""CSAF 2.0 rendering of public advisories.

The renderer is fed the trust-center projection, so these tests build the
graph the way a workspace would (products, a vulnerability, per-product
statuses with version ranges), publish it through the real service, and read
the document back over the public endpoint. Every document is validated
against the vendored OASIS schema, which is the test that matters to a
CSAF-aware consumer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema.validators import validator_for
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from sbomify.apps.core.models import Component, Product
from sbomify.apps.security_advisories.models import (
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryReference,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.advisories import cvss_entry, publish_advisory, withdraw_advisory

pytestmark = pytest.mark.django_db

SCHEMAS = Path(__file__).parent / "csaf_schemas"
CVSS_URLS = {
    "https://www.first.org/cvss/cvss-v2.0.json": "cvss-v2.0.json",
    "https://www.first.org/cvss/cvss-v3.0.json": "cvss-v3.0.json",
    "https://www.first.org/cvss/cvss-v3.1.json": "cvss-v3.1.json",
}
VECTOR = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"


def validate_csaf(document: dict) -> None:
    """Raise if the document does not satisfy the CSAF 2.0 schema. Never touches the network."""
    schema = json.loads((SCHEMAS / "csaf_json_schema.json").read_text())
    registry = Registry()
    for url, filename in CVSS_URLS.items():
        contents = json.loads((SCHEMAS / filename).read_text())
        registry = registry.with_resource(url, Resource.from_contents(contents, default_specification=DRAFT7))
    validator_for(schema)(schema, registry=registry).validate(document)


def _csaf(workspace_key: str, advisory_id: str) -> str:
    return f"/api/v1/advisories/public/{workspace_key}/{advisory_id}/csaf"


def _listed_product(team, name: str, component: str) -> Product:
    product = Product.objects.create(name=name, team=team, is_public=True)
    product.components.add(Component.objects.create(name=component, team=team, visibility=Component.Visibility.PUBLIC))
    return product


@pytest.fixture
def gateway(team):
    return _listed_product(team, "Acme Gateway", "gateway-core")


@pytest.fixture
def vault(team):
    return _listed_product(team, "Acme Vault", "vault-core")


@pytest.fixture
def rich_advisory(team, sample_user, gateway, vault):
    """One CVE, affected in the gateway with a fix, not reachable in the vault."""
    advisory = SecurityAdvisory.objects.create(
        team=team,
        title="Log4Shell in Acme Gateway",
        summary="Remote code execution through JNDI lookups.",
        description="Gateway 2.0 through 2.17.0 embed a vulnerable log4j.",
        acknowledgments=[{"name": "Jane Reporter", "organization": "Example Labs"}],
    )
    gateway_link = AdvisoryProduct.objects.create(advisory=advisory, product=gateway)
    vault_link = AdvisoryProduct.objects.create(advisory=advisory, product=vault)
    vulnerability = AdvisoryVulnerability.objects.create(
        advisory=advisory,
        cve_id="CVE-2021-44228",
        title="Log4Shell",
        description="JNDI features do not protect against attacker-controlled endpoints.",
        severity="critical",
        cvss_scores=[cvss_entry(9.8, VECTOR)],
        exploitation_status=AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED,
    )
    affected = AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=gateway_link,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
        response=AdvisoryProductStatus.Response.UPDATE,
        action_statement="Upgrade to 2.17.1.",
        recommended_version="2.17.1",
    )
    AdvisoryVersionRange.objects.create(product_status=affected, introduced="2.0", fixed="2.17.1")
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=vault_link,
        status=AdvisoryProductStatus.Status.NOT_AFFECTED,
        justification=AdvisoryProductStatus.Justification.CODE_NOT_REACHABLE,
        impact_statement="The vault never logs request bodies.",
    )
    AdvisoryReference.objects.create(
        advisory=advisory,
        reference_type="cve",
        external_id="CVE-2021-44228",
        url="https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
        summary="NVD entry",
    )
    result = publish_advisory(team, sample_user, advisory.id, visibility=SecurityAdvisory.Visibility.PUBLIC)
    assert result.ok, result.error
    advisory.refresh_from_db()
    return advisory


@pytest.fixture
def client(authenticated_api_client):
    return authenticated_api_client[0]


def _by_name(document: dict) -> dict[str, str]:
    return {entry["name"]: entry["product_id"] for entry in document["product_tree"]["full_product_names"]}


class TestTheDocument:
    def test_it_validates_and_names_the_advisory(self, client, team, rich_advisory) -> None:
        response = client.get(_csaf(team.key, rich_advisory.tracking_id))

        assert response.status_code == 200, response.content
        document = response.json()
        validate_csaf(document)

        head = document["document"]
        assert head["category"] == "csaf_security_advisory"
        assert head["csaf_version"] == "2.0"
        assert head["title"] == "Log4Shell in Acme Gateway"
        assert head["publisher"]["category"] == "vendor"
        assert head["publisher"]["name"] == team.display_name
        assert head["publisher"]["namespace"].startswith("http")
        assert head["tracking"]["id"] == rich_advisory.tracking_id
        assert head["tracking"]["status"] == "final"
        assert head["tracking"]["version"] == "1"
        assert head["tracking"]["revision_history"][0]["summary"].startswith("Published as")
        assert head["tracking"]["initial_release_date"] == rich_advisory.published_at.isoformat()
        assert head["distribution"]["tlp"]["label"] == "WHITE"
        assert head["aggregate_severity"] == {"text": "Critical"}
        assert {n["category"] for n in head["notes"]} == {"summary", "description"}
        assert head["acknowledgments"] == [{"names": ["Jane Reporter"]}]
        assert head["references"][0]["category"] == "self"
        assert head["references"][0]["url"].endswith(f"/advisories/{rich_advisory.tracking_id}/")
        assert {r["url"] for r in head["references"][1:]} == {"https://nvd.nist.gov/vuln/detail/CVE-2021-44228"}

    def test_versions_become_products_and_statuses(self, client, team, rich_advisory) -> None:
        """CSAF says which versions are affected by naming each version span as its own product."""
        document = client.get(_csaf(team.key, rich_advisory.tracking_id)).json()
        validate_csaf(document)

        ids = _by_name(document)
        assert set(ids) == {"Acme Gateway >= 2.0, < 2.17.1", "Acme Gateway >= 2.17.1", "Acme Vault"}
        [vulnerability] = document["vulnerabilities"]
        assert vulnerability["cve"] == "CVE-2021-44228"
        assert vulnerability["product_status"] == {
            "known_affected": [ids["Acme Gateway >= 2.0, < 2.17.1"]],
            "fixed": [ids["Acme Gateway >= 2.17.1"]],
            "known_not_affected": [ids["Acme Vault"]],
        }
        assert vulnerability["flags"] == [
            {"label": "vulnerable_code_not_in_execute_path", "product_ids": [ids["Acme Vault"]]}
        ]
        assert vulnerability["remediations"] == [
            {
                "category": "vendor_fix",
                "details": "Upgrade to 2.17.1.",
                "product_ids": [ids["Acme Gateway >= 2.0, < 2.17.1"]],
            }
        ]
        [score] = vulnerability["scores"]
        assert score["cvss_v3"] == {
            "version": "3.1",
            "vectorString": VECTOR,
            "baseScore": 9.8,
            "baseSeverity": "CRITICAL",
        }
        assert score["products"] == [ids["Acme Gateway >= 2.0, < 2.17.1"]]
        threats = {t["category"]: t for t in vulnerability["threats"]}
        assert threats["impact"]["details"] == "The vault never logs request bodies."
        assert threats["impact"]["product_ids"] == [ids["Acme Vault"]]
        assert threats["exploit_status"]["details"] == "Exploitation is known."

    def test_a_withdrawal_is_a_revision_and_a_note(self, client, team, sample_user, rich_advisory) -> None:
        assert withdraw_advisory(team, sample_user, rich_advisory.id, reason="The vault was affected after all.").ok

        document = client.get(_csaf(team.key, rich_advisory.tracking_id)).json()
        validate_csaf(document)

        tracking = document["document"]["tracking"]
        assert tracking["version"] == "2"
        assert [r["number"] for r in tracking["revision_history"]] == ["1", "2"]
        assert tracking["revision_history"][-1]["summary"] == "The vault was affected after all."
        assert tracking["current_release_date"] == tracking["revision_history"][-1]["date"]
        withdrawn = [n for n in document["document"]["notes"] if n.get("title") == "Withdrawn"]
        assert withdrawn == [{"category": "other", "title": "Withdrawn", "text": "The vault was affected after all."}]

    def test_a_not_affected_product_is_named_without_a_placeholder(self, client, team, rich_advisory) -> None:
        """The table prints "None"/"All" there; a CSAF product name must not carry them."""
        document = client.get(_csaf(team.key, rich_advisory.tracking_id)).json()
        validate_csaf(document)

        names = list(_by_name(document))
        assert "Acme Vault" in names
        assert not [n for n in names if n.endswith(" None") or n.endswith(" All")], names

    def test_a_notice_without_products_is_a_base_document(self, client, team, sample_user) -> None:
        """The advisory profile needs a product tree; a workspace notice has none to give."""
        notice = SecurityAdvisory.objects.create(
            team=team,
            title="Not affected by CVE-2024-3094",
            summary="No shipped product embeds xz.",
            advisory_type=SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE,
        )
        result = publish_advisory(team, sample_user, notice.id, visibility=SecurityAdvisory.Visibility.PUBLIC)
        assert result.ok, result.error
        notice.refresh_from_db()

        document = client.get(_csaf(team.key, notice.tracking_id)).json()
        validate_csaf(document)

        assert document["document"]["category"] == "csaf_base"
        assert "product_tree" not in document
        assert "vulnerabilities" not in document

    def test_a_reader_gets_only_the_products_they_may_see(
        self, authenticated_api_client, team, rich_advisory, vault
    ) -> None:
        """Passing the gate on one product is not permission to learn the others."""
        from sbomify.apps.core.tests.shared_fixtures import get_api_headers

        client, token = authenticated_api_client
        Product.objects.filter(pk=vault.pk).update(is_public=False)

        anonymous = client.get(_csaf(team.key, rich_advisory.tracking_id)).json()
        insider = client.get(_csaf(team.key, rich_advisory.tracking_id), **get_api_headers(token)).json()
        validate_csaf(anonymous)
        validate_csaf(insider)

        assert "Acme Vault" not in _by_name(anonymous)
        assert "known_not_affected" not in anonymous["vulnerabilities"][0]["product_status"]
        assert "Acme Vault" in _by_name(insider)

    def test_a_gated_advisory_travels_as_amber_for_its_readers_only(
        self, authenticated_api_client, team, sample_user, gateway
    ) -> None:
        from sbomify.apps.core.tests.shared_fixtures import get_api_headers

        client, token = authenticated_api_client
        advisory = SecurityAdvisory.objects.create(team=team, title="Embargoed")
        link = AdvisoryProduct.objects.create(advisory=advisory, product=gateway)
        vulnerability = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2024-0001")
        AdvisoryProductStatus.objects.create(
            vulnerability=vulnerability,
            advisory_product=link,
            status=AdvisoryProductStatus.Status.IN_TRIAGE,
        )
        result = publish_advisory(team, sample_user, advisory.id, visibility=SecurityAdvisory.Visibility.GATED)
        assert result.ok, result.error
        advisory.refresh_from_db()

        assert client.get(_csaf(team.key, advisory.tracking_id)).status_code == 404
        document = client.get(_csaf(team.key, advisory.tracking_id), **get_api_headers(token)).json()
        validate_csaf(document)

        assert document["document"]["distribution"]["tlp"]["label"] == "AMBER"
        assert document["vulnerabilities"][0]["product_status"] == {
            "under_investigation": [_by_name(document)["Acme Gateway"]]
        }
