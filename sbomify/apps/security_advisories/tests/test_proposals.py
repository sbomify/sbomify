"""Changes an AI agent makes to a published advisory wait for a person.

An agent token may shape a draft freely, because publishing is the review.
After that, its timeline, fields and product statuses are what the Trust
Center serves, so each of the agent's writes is held as a proposal. These
drive the API the agent uses, the page the reviewer uses, and what the Trust
Center shows either side of the decision.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core import authz
from sbomify.apps.core.tests.shared_fixtures import get_api_headers, setup_authenticated_client_session
from sbomify.apps.security_advisories.models import AdvisoryEvent, AdvisoryProposal, SecurityAdvisory
from sbomify.apps.security_advisories.services import proposals as proposal_service
from sbomify.apps.security_advisories.services.advisories import edit_message, post_update, withdraw_advisory
from sbomify.apps.security_advisories.services.trust_center import anonymous_projection

from .conftest import publish

pytestmark = pytest.mark.django_db


def _url(advisory_id: str, suffix: str = "") -> str:
    return f"/api/v1/advisories/{advisory_id}{suffix}"


@pytest.fixture
def owner(sample_team_with_owner_member):
    return sample_team_with_owner_member.user


@pytest.fixture
def agent_token(sample_user, sample_team_with_owner_member):
    return AccessToken.objects.create(
        user=sample_user,
        encoded_token=create_personal_access_token(sample_user),
        description="Advisory agent",
        scopes=authz.SCOPE_PRESETS["agent"],
    )


@pytest.fixture
def agent(agent_token):
    return Client(), get_api_headers(agent_token)


@pytest.fixture
def person(authenticated_api_client, sample_team_with_owner_member):
    """The owner's own full token: the reviewer, over the API."""
    client, token = authenticated_api_client
    return client, get_api_headers(token)


@pytest.fixture
def published(make_publishable):
    return publish(make_publishable, visibility=SecurityAdvisory.Visibility.PUBLIC)


_NO = {"reason": "premature", "decision_note": "No."}


def _post(client, headers, url: str, data: dict) -> object:
    return client.post(url, data=data, content_type="application/json", **headers)


def _patch(client, headers, url: str, data: dict) -> object:
    return client.patch(url, data=data, content_type="application/json", **headers)


class TestAnAgentOnAPublishedAdvisory:
    def test_a_new_update_is_held(self, agent, published) -> None:
        client, headers = agent

        response = _post(
            client,
            headers,
            _url(published.id, "/updates"),
            {"kind": "update", "note": "Patch merged.", "context": "Saw the fix land in main."},
        )

        assert response.status_code == 202, response.content
        body = response.json()
        assert body["kind"] == "post_update"
        assert body["status"] == "pending"
        assert body["note"] == "Patch merged."
        assert body["context"] == "Saw the fix land in main."
        assert not published.events.filter(event_type=AdvisoryEvent.EventType.UPDATE).exists()

    def test_a_status_move_is_held(self, agent, published) -> None:
        client, headers = agent

        response = _post(client, headers, _url(published.id, "/updates"), {"kind": "fix_in_progress", "note": ""})

        assert response.status_code == 202, response.content
        published.refresh_from_db()
        assert published.remediation_status == "identified"

    def test_a_field_edit_is_held_with_its_diff(self, agent, published) -> None:
        client, headers = agent

        response = _patch(client, headers, _url(published.id), {"severity": "critical", "title": "Worse than thought"})

        assert response.status_code == 202, response.content
        changes = {c["label"]: (c["before"], c["after"]) for c in response.json()["changes"]}
        assert changes == {
            "Title": ("Log4Shell in Acme Gateway", "Worse than thought"),
            "Severity": ("", "Critical"),
        }
        published.refresh_from_db()
        assert published.title == "Log4Shell in Acme Gateway"

    def test_a_product_status_change_is_held(self, agent, published, product) -> None:
        client, headers = agent

        response = _patch(
            client,
            headers,
            _url(published.id, f"/products/{product.id}/status"),
            {"status": "resolved", "fixed_version": "1.4.3"},
        )

        assert response.status_code == 202, response.content
        assert response.json()["kind"] == "product_status"
        assert published.vulnerabilities.get().product_statuses.get().status == "exploitable"

    def test_adding_a_product_is_held(self, agent, published, team) -> None:
        from sbomify.apps.core.models import Product

        other = Product.objects.create(name="Acme Edge", team=team)
        client, headers = agent

        response = _post(client, headers, _url(published.id, "/products"), {"product_id": other.id})

        assert response.status_code == 202, response.content
        assert not published.products.filter(product=other).exists()

    def test_an_edit_to_an_update_is_held(self, agent, published, owner, team) -> None:
        assert post_update(team, owner, published.id, kind="update", note="Fixed in 1.4.2.").ok
        event = published.events.get(event_type=AdvisoryEvent.EventType.UPDATE)
        client, headers = agent

        response = _patch(client, headers, _url(published.id, f"/updates/{event.id}"), {"note": "Fixed in 1.4.3."})

        assert response.status_code == 202, response.content
        assert response.json()["changes"] == [{"label": "Update", "before": "Fixed in 1.4.2.", "after": "Fixed in 1.4.3."}]
        timeline = client.get(_url(published.id), **headers).json()["timeline"]
        assert next(e for e in timeline if e["id"] == event.id)["body"] == "Fixed in 1.4.2."

    def test_a_draft_is_still_written_at_once(self, agent, advisory) -> None:
        client, headers = agent

        response = _post(client, headers, _url(advisory.id, "/updates"), {"kind": "update", "note": "Drafting."})

        assert response.status_code == 200, response.content
        assert not AdvisoryProposal.objects.exists()

    def test_a_person_is_never_held(self, person, published) -> None:
        client, headers = person

        response = _post(client, headers, _url(published.id, "/updates"), {"kind": "update", "note": "Mine."})

        assert response.status_code == 200, response.content
        assert not AdvisoryProposal.objects.exists()

    def test_a_mistake_is_refused_now_not_at_review(self, agent, published) -> None:
        client, headers = agent

        missing = _patch(client, headers, _url(published.id, "/updates/nope"), {"note": "x"})
        blank = _post(client, headers, _url(published.id, "/updates"), {"kind": "update", "note": " "})

        assert missing.status_code == 404
        assert blank.status_code == 400
        assert not AdvisoryProposal.objects.exists()

    def test_resending_replaces_the_pending_one(self, agent, published) -> None:
        client, headers = agent
        first = _patch(client, headers, _url(published.id), {"summary": "One."}).json()
        second = _patch(client, headers, _url(published.id), {"summary": "Two."}).json()

        assert AdvisoryProposal.objects.get(pk=first["id"]).status == "superseded"
        assert AdvisoryProposal.objects.get(pk=second["id"]).status == "pending"

    def test_it_can_read_back_what_happened(self, agent, person, published) -> None:
        client, headers = agent
        sent = _post(client, headers, _url(published.id, "/updates"), {"kind": "update", "note": "Hi."}).json()
        reviewer, reviewer_headers = person
        _post(reviewer, reviewer_headers, _url(published.id, f"/proposals/{sent['id']}/reject"), _NO)

        mine = client.get(_url(published.id, f"/proposals/{sent['id']}"), **headers).json()
        listed = client.get(_url(published.id, "/proposals"), **headers).json()

        assert (mine["status"], mine["decision_note"], mine["rejection_reason"]) == ("rejected", "No.", "premature")
        assert [row["id"] for row in listed] == [sent["id"]]


class TestDeciding:
    def test_approving_applies_it_as_the_agent_with_the_approver_named(self, agent, person, published) -> None:
        client, headers = agent
        sent = _post(client, headers, _url(published.id, "/updates"), {"kind": "fix_in_progress", "note": "PR up."})
        reviewer, reviewer_headers = person

        decided = _post(reviewer, reviewer_headers, _url(published.id, f"/proposals/{sent.json()['id']}/approve"), {})

        assert decided.status_code == 200, decided.content
        assert decided.json()["status"] == "approved"
        published.refresh_from_db()
        assert published.remediation_status == "fix_in_progress"
        event = published.events.get(event_type=AdvisoryEvent.EventType.STATUS_CHANGE, payload__to="fix_in_progress")
        assert event.payload["via"]["channel"] == "agent"
        assert event.payload["via"]["proposal_id"] == sent.json()["id"]
        assert event.payload["via"]["approved_by"]

    def test_the_reviewer_can_reword_it_first(self, agent, owner, team, published) -> None:
        client, headers = agent
        sent = _post(client, headers, _url(published.id, "/updates"), {"kind": "update", "note": "fixd"}).json()

        result = proposal_service.approve_proposal(team, owner, published.id, sent["id"], note="Fixed.")

        assert result.ok
        assert published.events.get(event_type=AdvisoryEvent.EventType.UPDATE).body == "Fixed."
        proposal = AdvisoryProposal.objects.get(pk=sent["id"])
        assert proposal.revised
        assert proposal.payload["proposed_note"] == "fixd"

    def test_rejecting_changes_nothing(self, agent, person, published) -> None:
        client, headers = agent
        sent = _patch(client, headers, _url(published.id), {"title": "Nope"}).json()
        reviewer, reviewer_headers = person

        decided = _post(reviewer, reviewer_headers, _url(published.id, f"/proposals/{sent['id']}/reject"), _NO)

        assert decided.status_code == 200
        published.refresh_from_db()
        assert published.title == "Log4Shell in Acme Gateway"

    def test_an_agent_cannot_decide(self, agent, published) -> None:
        client, headers = agent
        sent = _post(client, headers, _url(published.id, "/updates"), {"kind": "update", "note": "Hi."}).json()

        assert _post(client, headers, _url(published.id, f"/proposals/{sent['id']}/approve"), {}).status_code == 403
        assert AdvisoryProposal.objects.get(pk=sent["id"]).status == "pending"

    def test_a_decided_change_cannot_be_decided_again(self, agent, person, published) -> None:
        client, headers = agent
        sent = _post(client, headers, _url(published.id, "/updates"), {"kind": "update", "note": "Hi."}).json()
        reviewer, reviewer_headers = person
        url = _url(published.id, f"/proposals/{sent['id']}")
        _post(reviewer, reviewer_headers, f"{url}/approve", {})

        assert _post(reviewer, reviewer_headers, f"{url}/reject", _NO).status_code == 409
        assert published.events.filter(event_type=AdvisoryEvent.EventType.UPDATE).count() == 1

    def test_a_refused_write_leaves_it_pending(self, agent, owner, team, published) -> None:
        """Resolving while a product is still affected is refused for a person too."""
        client, headers = agent
        sent = _post(client, headers, _url(published.id, "/updates"), {"kind": "resolved", "note": ""}).json()

        result = proposal_service.approve_proposal(team, owner, published.id, sent["id"])

        assert not result.ok
        assert "Set a status for each product" in (result.error or "")
        assert AdvisoryProposal.objects.get(pk=sent["id"]).status == "pending"

    def test_it_says_when_someone_changed_the_same_thing_since(self, agent, owner, team, published) -> None:
        client, headers = agent
        sent = _patch(client, headers, _url(published.id), {"title": "Agent title"}).json()
        assert not sent["is_stale"]
        from sbomify.apps.security_advisories.services.advisories import update_advisory

        assert update_advisory(team, owner, published.id, title="Person title").ok

        row = proposal_service.get_proposal(team, published.id, sent["id"]).value
        assert row is not None and row["is_stale"]
        # The diff is against what approving replaces now, not what the agent saw.
        assert row["changes"][0]["before"] == "Person title"

    def test_withdrawing_the_advisory_closes_what_was_waiting(self, agent, owner, team, published) -> None:
        client, headers = agent
        sent = _post(client, headers, _url(published.id, "/updates"), {"kind": "update", "note": "Hi."}).json()

        assert withdraw_advisory(team, owner, published.id, reason="Duplicate.").ok

        assert AdvisoryProposal.objects.get(pk=sent["id"]).status == "superseded"


class TestEditingAnUpdate:
    @pytest.fixture
    def update(self, team, owner, published):
        assert post_update(team, owner, published.id, kind="update", note="Fixed in 1.4.2.").ok
        return published.events.get(event_type=AdvisoryEvent.EventType.UPDATE)

    def test_the_original_stays_on_record(self, team, owner, published, update) -> None:
        assert edit_message(team, owner, published.id, update.id, note="Fixed in 1.4.3.").ok

        update.refresh_from_db()
        assert update.body == "Fixed in 1.4.2."
        edit = published.events.get(event_type=AdvisoryEvent.EventType.MESSAGE_EDITED)
        assert edit.payload["old"] == "Fixed in 1.4.2."
        assert edit.body == "Fixed in 1.4.3."

    def test_every_reader_shows_the_new_text_once(self, team, owner, published, update, person) -> None:
        assert edit_message(team, owner, published.id, update.id, note="Fixed in 1.4.3.").ok
        client, headers = person

        timeline = client.get(_url(published.id), **headers).json()["timeline"]
        public = anonymous_projection(team, SecurityAdvisory.objects.get(pk=published.pk))

        entry = next(e for e in timeline if e["id"] == update.id)
        assert entry["body"] == "Fixed in 1.4.3." and entry["edited_at"]
        assert not any(e["kind"] == "message_edited" for e in timeline)
        public_entry = next(e for e in public["timeline"] if e["id"] == update.id)
        assert public_entry["note"] == "Fixed in 1.4.3."
        assert len(public["timeline"]) == len([e for e in timeline if e["kind"] in AdvisoryEvent.PUBLIC_EVENT_TYPES])

    def test_an_internal_comment_edit_stays_internal(self, team, owner, published) -> None:
        comment = AdvisoryEvent.objects.create(
            advisory=published, event_type=AdvisoryEvent.EventType.COMMENT, actor=owner, body="Ask legal."
        )

        assert edit_message(team, owner, published.id, comment.id, note="Legal said yes.").ok

        public = anonymous_projection(team, SecurityAdvisory.objects.get(pk=published.pk))
        assert "Legal said yes." not in str(public)

    def test_a_field_change_cannot_be_rewritten(self, team, owner, published) -> None:
        change = AdvisoryEvent.objects.create(
            advisory=published,
            event_type=AdvisoryEvent.EventType.FIELD_CHANGE,
            actor=owner,
            body="Title changed.",
            payload={"field": "title", "old": "a", "new": "b"},
        )

        result = edit_message(team, owner, published.id, change.id, note="Nothing changed.")

        assert result.status_code == 404

    def test_the_page_edits_in_place(self, client, sample_team_with_owner_member, published, update) -> None:
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)
        url = reverse("core:security_advisory_detail", args=[published.id])

        response = client.post(url, {"intent": "edit_update", "update_id": update.id, "note": "Fixed in **1.4.3**."})

        assert response.status_code == 302
        page = client.get(url).content.decode()
        assert "Fixed in <strong>1.4.3</strong>." in page
        assert "Edited " in page


class TestTheReviewPage:
    @pytest.fixture
    def page(self, client, sample_team_with_owner_member, published):
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)
        return client, reverse("core:security_advisory_detail", args=[published.id])

    def test_it_shows_what_is_waiting_where_it_would_land(self, page, agent, published) -> None:
        api, headers = agent
        sent = _post(api, headers, _url(published.id, "/updates"), {"kind": "update", "note": "Patch **merged**."})
        _patch(api, headers, _url(published.id), {"severity": "critical", "context": "CVSS 9.8 per NVD."})
        client, url = page

        html = client.get(url).content.decode()

        assert "Waiting for review" in html
        assert f'id="proposal-{sent.json()["id"]}"' in html
        assert "Awaiting review" in html
        assert "Patch <strong>merged</strong>." in html
        assert "CVSS 9.8 per NVD." in html
        assert "Change the severity" in html
        assert "Edit, then approve" in html

    def test_it_approves_and_rejects(self, page, agent, published) -> None:
        api, headers = agent
        update = _post(api, headers, _url(published.id, "/updates"), {"kind": "update", "note": "fixd"}).json()
        title = _patch(api, headers, _url(published.id), {"title": "Nope"}).json()
        client, url = page

        client.post(url, {"intent": "approve_proposal", "proposal_id": update["id"], "note": "Fixed."})
        client.post(
            url,
            {"intent": "reject_proposal", "proposal_id": title["id"], "reason": "duplicate", "decision_note": "Keep it."},
        )

        assert published.events.get(event_type=AdvisoryEvent.EventType.UPDATE).body == "Fixed."
        published.refresh_from_db()
        assert published.title == "Log4Shell in Acme Gateway"
        html = client.get(url).content.decode()
        assert "Recently decided" in html
        assert "Approved by" in html
        assert "Feedback to the agent" in html
        assert "Already covered" in html

    def test_a_member_who_cannot_publish_cannot_decide(self, page, agent, published, sample_team_with_owner_member):
        api, headers = agent
        sent = _post(api, headers, _url(published.id, "/updates"), {"kind": "update", "note": "Hi."}).json()
        client, url = page
        sample_team_with_owner_member.role = "member"
        sample_team_with_owner_member.save()

        response = client.post(url, {"intent": "approve_proposal", "proposal_id": sent["id"]})

        assert response.status_code == 404
        assert AdvisoryProposal.objects.get(pk=sent["id"]).status == "pending"

    def test_the_list_says_which_advisories_wait(self, page, agent, published) -> None:
        api, headers = agent
        _post(api, headers, _url(published.id, "/updates"), {"kind": "update", "note": "Hi."})
        client, _url_unused = page

        html = client.get(reverse("core:security_advisories_dashboard")).content.decode()

        assert '"pending_review": 1' in html
        assert "to review" in html


class TestRejectionFeedback:
    """A rejection is feedback: the agent learns why and what to do next."""

    def _send(self, agent, published, note: str = "Fixed.") -> dict:
        client, headers = agent
        return _post(client, headers, _url(published.id, "/updates"), {"kind": "update", "note": note}).json()

    def test_a_reason_and_a_note_are_both_required(self, agent, person, published) -> None:
        sent = self._send(agent, published)
        reviewer, reviewer_headers = person
        url = _url(published.id, f"/proposals/{sent['id']}/reject")

        no_reason = _post(reviewer, reviewer_headers, url, {"decision_note": "Not yet."})
        no_note = _post(reviewer, reviewer_headers, url, {"reason": "premature"})
        made_up = _post(reviewer, reviewer_headers, url, {"reason": "vibes", "decision_note": "Not yet."})

        assert {no_reason.status_code, no_note.status_code, made_up.status_code} == {400}
        assert AdvisoryProposal.objects.get(pk=sent["id"]).status == "pending"

    def test_the_agent_reads_every_decision_in_one_call(self, agent, person, published, team) -> None:
        rejected = self._send(agent, published, "Fixed.")
        approved = self._send(agent, published, "Patch merged.")
        reviewer, reviewer_headers = person
        _post(
            reviewer,
            reviewer_headers,
            _url(published.id, f"/proposals/{rejected['id']}/reject"),
            {"reason": "premature", "decision_note": "Not released yet."},
        )
        _post(reviewer, reviewer_headers, _url(published.id, f"/proposals/{approved['id']}/approve"), {})
        client, headers = agent

        feed = client.get("/api/v1/advisories/proposals?status=rejected", **headers)

        assert feed.status_code == 200, feed.content
        [row] = feed.json()
        assert row["id"] == rejected["id"]
        assert row["advisory_id"] == published.id
        assert row["rejection_reason"] == "premature"
        assert row["decision_note"] == "Not released yet."
        assert row["next_step"].startswith("Wait until")

    def test_the_feed_is_only_the_callers_own(self, agent, person, published) -> None:
        self._send(agent, published)
        reviewer, reviewer_headers = person

        assert reviewer.get("/api/v1/advisories/proposals", **reviewer_headers).json() == []

    def test_since_narrows_to_what_is_new(self, agent, published) -> None:
        self._send(agent, published)
        client, headers = agent

        later = client.get("/api/v1/advisories/proposals?since=2999-01-01T00:00:00Z", **headers)

        assert later.json() == []

    def test_a_resend_shows_the_earlier_rejection(self, agent, owner, team, published) -> None:
        client, headers = agent
        first = _patch(client, headers, _url(published.id), {"severity": "critical"}).json()
        proposal_service.reject_proposal(
            team, owner, published.id, first["id"], reason="inaccurate", decision_note="NVD says high."
        )
        again = _patch(client, headers, _url(published.id), {"severity": "critical"}).json()

        row = proposal_service.get_proposal(team, published.id, again["id"]).value

        assert row is not None
        assert row["previous_rejection"]["label"] == "Not accurate"
        assert row["previous_rejection"]["note"] == "NVD says high."

    def test_the_dialog_offers_every_reason(self, client, sample_team_with_owner_member, agent, published) -> None:
        self._send(agent, published)
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        html = client.get(reverse("core:security_advisory_detail", args=[published.id])).content.decode()

        for label in ("Not accurate", "Too early", "Needs rewording", "Already covered", "Something else"):
            assert label in html
        assert 'name="reason"' in html
        assert "What should the agent do differently?" in html
