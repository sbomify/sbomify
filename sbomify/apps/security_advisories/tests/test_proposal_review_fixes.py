"""Regression coverage for advisory proposal publication, review and conflict handling."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from django.db import OperationalError, connection, transaction

from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProductStatus,
    AdvisoryProposal,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services import proposals as proposal_service
from sbomify.apps.security_advisories.services.advisories import post_update, update_product_status, withdraw_advisory

from . import test_proposals
from .test_proposals import _url

agent = test_proposals.agent
agent_token = test_proposals.agent_token
owner = test_proposals.owner
published = test_proposals.published

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["fields", "update", "edit_update", "status", "product_status", "add_product"])
def test_agent_write_locks_publication_until_applied(
    agent: Any,
    make_publishable: SecurityAdvisory,
    owner: Any,
    team: Any,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """A concurrent publisher cannot lock the draft while its agent write is in flight."""
    from sbomify.apps.core.models import Product
    from sbomify.apps.security_advisories.services import advisories as advisory_service

    advisory = make_publishable
    assert post_update(team, owner, advisory.id, kind="update", note="Original.").ok
    event = advisory.events.get(event_type=AdvisoryEvent.EventType.UPDATE)
    status = advisory.vulnerabilities.get().product_statuses.get()
    assert status.advisory_product is not None
    other = Product.objects.create(name="Other product", team=team)
    requests = {
        "fields": ("patch", "", {"summary": "New summary"}),
        "update": ("post", "/updates", {"kind": "update", "note": "New update"}),
        "edit_update": ("patch", f"/updates/{event.id}", {"note": "Corrected update"}),
        "status": ("patch", f"/statuses/{status.id}", {"action_statement": "New guidance"}),
        "product_status": (
            "patch",
            f"/products/{status.advisory_product.product_id}/status",
            {"action_statement": "New guidance"},
        ),
        "add_product": ("post", "/products", {"product_id": other.id}),
    }

    def publication_is_locked() -> bool:
        try:
            with transaction.atomic():
                SecurityAdvisory.objects.select_for_update(nowait=True).get(pk=advisory.id)
        except OperationalError as error:
            if getattr(error.__cause__, "pgcode", None) != "55P03":
                raise
            return True
        finally:
            connection.close()
        return False

    original_gate = proposal_service.needs_approval
    original_write = getattr(
        advisory_service,
        {
            "fields": "update_advisory",
            "update": "post_update",
            "edit_update": "edit_message",
            "status": "update_product_status",
            "product_status": "update_product_statuses",
            "add_product": "add_advisory_product",
        }[operation],
    )
    checked = []

    def check_lock() -> None:
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(publication_is_locked).result(timeout=10)
        checked.append(True)

    def gated(snapshot: SecurityAdvisory, channel: str) -> bool:
        check_lock()
        return original_gate(snapshot, channel)

    def write(*args: Any, **kwargs: Any) -> Any:
        check_lock()
        return original_write(*args, **kwargs)

    monkeypatch.setattr(proposal_service, "needs_approval", gated)
    monkeypatch.setattr(advisory_service, original_write.__name__, write)
    client, headers = agent
    method, suffix, payload = requests[operation]
    response = getattr(client, method)(
        _url(advisory.id, suffix), data=payload, content_type="application/json", **headers
    )
    assert response.status_code == 200, response.content
    assert len(checked) == 2
    assert not AdvisoryProposal.objects.exists()


def test_product_proposal_tracks_every_vulnerability(
    agent: Any,
    published: SecurityAdvisory,
    team: Any,
    owner: Any,
) -> None:
    client, headers = agent
    link = published.products.get()
    vulnerability = AdvisoryVulnerability.objects.create(advisory=published, cve_id="CVE-2021-45046")
    second = AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability, advisory_product=link, status="exploitable", action_statement="Second guidance"
    )
    sent = client.patch(
        _url(published.id, f"/products/{link.product_id}/status"),
        data={"action_statement": "Agent guidance"},
        content_type="application/json",
        **headers,
    )
    assert sent.status_code == 202, sent.content
    assert not sent.json()["is_stale"]
    assert {change["before"] for change in sent.json()["changes"]} == {"Upgrade to 1.4.3.", "Second guidance"}
    assert any("CVE-2021-45046" in change["label"] for change in sent.json()["changes"])

    assert update_product_status(
        team, owner, published.id, second.id, changes={"action_statement": "Human guidance"}
    ).ok
    current = client.get(_url(published.id, f"/proposals/{sent.json()['id']}"), **headers).json()
    assert current["is_stale"]
    assert {change["before"] for change in current["changes"]} == {"Upgrade to 1.4.3.", "Human guidance"}

    result = proposal_service.approve_proposal(team, owner, published.id, sent.json()["id"])
    assert result.ok
    assert set(
        AdvisoryProductStatus.objects.filter(vulnerability__advisory=published).values_list(
            "action_statement", flat=True
        )
    ) == {"Agent guidance"}


@pytest.mark.parametrize("operation", ["fields", "update"])
def test_withdrawn_agent_write_returns_conflict(
    agent: Any,
    published: SecurityAdvisory,
    team: Any,
    owner: Any,
    operation: str,
) -> None:
    assert withdraw_advisory(team, owner, published.id, reason="Duplicate.").ok
    client, headers = agent
    response = (
        client.patch(_url(published.id), data={"title": "New title"}, content_type="application/json", **headers)
        if operation == "fields"
        else client.post(
            _url(published.id, "/updates"),
            data={"kind": "update", "note": "New update"},
            content_type="application/json",
            **headers,
        )
    )
    assert response.status_code == 409, response.content
    assert not AdvisoryProposal.objects.exists()
