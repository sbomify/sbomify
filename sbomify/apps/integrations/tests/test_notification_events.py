"""The three messages, from the change that causes each to the post that carries it."""

from __future__ import annotations

import json

import pytest

from sbomify.apps.core.models import Component
from sbomify.apps.integrations import events
from sbomify.apps.integrations.exceptions import ProviderUnavailable
from sbomify.apps.integrations.models import Integration, NotificationRoute
from sbomify.apps.integrations.services import messages
from sbomify.apps.integrations.tasks import notifications as tasks
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.models import VexSubmission

pytestmark = pytest.mark.django_db

Event = NotificationRoute.Event


def _route(integration: Integration, event: str, **kwargs) -> NotificationRoute:
    defaults = {"channel_id": "C001", "channel_name": "security"}
    return NotificationRoute.objects.create(integration=integration, event=event, **{**defaults, **kwargs})


@pytest.fixture
def queued(monkeypatch) -> list[tuple]:
    sent: list[tuple] = []
    monkeypatch.setattr(tasks.notify_vex_submission, "send", lambda *args: sent.append(("vex", *args)))
    monkeypatch.setattr(tasks.notify_new_vulnerabilities, "send", lambda *args: sent.append(("new", *args)))
    monkeypatch.setattr(tasks.send_digest, "send", lambda *args: sent.append(("digest", *args)))
    return sent


@pytest.fixture
def component(sample_team_with_owner_member) -> Component:
    return Component.objects.create(name="payments-api", team=sample_team_with_owner_member.team)


def _scan(component: Component, findings: list[dict]) -> AssessmentRun:
    sbom = SBOM.objects.create(
        name="app",
        version=f"1.0.{SBOM.objects.filter(component=component).count()}",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="app.json",
        component=component,
    )
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status="completed",
        result={"summary": {"total_findings": len(findings)}, "findings": findings},
    )


def _finding(advisory_id: str, severity: str, package: str = "libexample") -> dict:
    return {
        "id": advisory_id,
        "severity": severity,
        "cvss_score": {"critical": 9.8, "high": 7.5, "medium": 5.0, "low": 2.0}.get(severity),
        "component": {"name": package, "version": "1.0.0", "purl": f"pkg:pypi/{package}@1.0.0"},
    }


def _submission(component: Component, **kwargs) -> VexSubmission:
    defaults = {
        "team": component.team,
        "component": component,
        "kind": VexSubmission.Kind.DECISIONS,
        "channel": VexSubmission.Channel.AGENT,
        "document": b"{}",
        "document_format": "decisions",
        "decisions": [{"vuln_id": "CVE-2026-0001", "state": "not_affected"}],
        "advisory_ids": ["CVE-2026-0001"],
        "submitted_token_description": "nightly triage",
    }
    return VexSubmission.objects.create(**{**defaults, **kwargs})


class TestQueuedOnCommit:
    def test_nothing_is_queued_without_a_route(self, component, queued, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            events.vex_submission_created("sub1", component.team_id)
            events.vulnerabilities_opened(component.id, component.team_id, ["CVE-1"])

        assert queued == []

    def test_a_routed_event_is_queued_after_commit(
        self, component, connected_slack, queued, django_capture_on_commit_callbacks
    ):
        _route(connected_slack, Event.VEX_SUBMISSIONS)
        _route(connected_slack, Event.NEW_VULNERABILITIES)

        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            events.vex_submission_created("sub1", component.team_id)
            events.vulnerabilities_opened(component.id, component.team_id, ["CVE-2", "CVE-1"])
        assert queued == []

        for callback in callbacks:
            callback()
        assert queued == [("vex", "sub1"), ("new", component.id, ["CVE-1", "CVE-2"])]

    def test_a_revoked_connection_is_not_queued(
        self, component, connected_slack, queued, django_capture_on_commit_callbacks
    ):
        _route(connected_slack, Event.VEX_SUBMISSIONS)
        connected_slack.status = Integration.Status.REVOKED
        connected_slack.save()

        with django_capture_on_commit_callbacks(execute=True):
            events.vex_submission_created("sub1", component.team_id)

        assert queued == []


class TestTheProducersCallIn:
    def test_a_new_submission_announces_itself(
        self, component, connected_slack, queued, django_capture_on_commit_callbacks
    ):
        from sbomify.apps.vulnerability_scanning.services.vex_submissions import create_submission, parse_decisions

        _route(connected_slack, Event.VEX_SUBMISSIONS)
        parsed = parse_decisions(
            [{"vuln_id": "CVE-2026-0001", "state": "not_affected", "justification": "code_not_reachable"}],
            channel=VexSubmission.Channel.AGENT,
        )
        assert parsed.ok, parsed.error

        with django_capture_on_commit_callbacks(execute=True):
            result = create_submission(component=component, parsed=parsed.value, channel=VexSubmission.Channel.AGENT)

        assert result.ok, result.error
        assert ("vex", result.value.id) in queued

    def test_a_scan_announces_only_what_is_new_to_the_component(
        self, component, connected_slack, queued, django_capture_on_commit_callbacks
    ):
        from sbomify.apps.plugins.lifecycle import record_run

        _route(connected_slack, Event.NEW_VULNERABILITIES)

        with django_capture_on_commit_callbacks(execute=True):
            record_run(_scan(component, [_finding("CVE-1", "high")]))
        with django_capture_on_commit_callbacks(execute=True):
            record_run(_scan(component, [_finding("CVE-1", "high"), _finding("CVE-2", "critical")]))
        with django_capture_on_commit_callbacks(execute=True):
            # A rescan reporting nothing new announces nothing.
            record_run(_scan(component, [_finding("CVE-1", "high"), _finding("CVE-2", "critical")]))

        assert queued == [("new", component.id, ["CVE-1"]), ("new", component.id, ["CVE-2"])]


class TestNotifyVexSubmission:
    def test_posts_the_submission(self, component, connected_slack, fake_slack):
        _route(connected_slack, Event.VEX_SUBMISSIONS)
        submission = _submission(component, context="Reachability checked <!channel>")

        tasks.notify_vex_submission(submission.id)

        [post] = fake_slack.posts
        assert post["text"] == "1 VEX ruling for payments-api is waiting for approval."
        body = json.dumps(post["blocks"])
        assert "nightly triage" in body
        assert "?view=review" in body
        # Slack mention syntax from a submitter never reaches the channel as a mention.
        assert "<!channel>" not in body
        assert "&lt;!channel&gt;" in body

    def test_a_decided_submission_is_not_announced(self, component, connected_slack, fake_slack):
        _route(connected_slack, Event.VEX_SUBMISSIONS)
        submission = _submission(component, status=VexSubmission.Status.APPROVED)

        tasks.notify_vex_submission(submission.id)

        assert fake_slack.posts == []

    def test_one_channel_failing_does_not_silence_the_others(self, monkeypatch):
        """Every route is tried, and the outage is raised afterwards so dramatiq retries."""
        from types import SimpleNamespace

        attempts: list[str] = []

        def deliver(route, message):
            attempts.append(route.channel_id)
            if route.channel_id == "C001":
                raise ProviderUnavailable("Slack is not answering.", service="slack")
            return SimpleNamespace(ok=True)

        monkeypatch.setattr(tasks, "deliver", deliver)
        routes = [SimpleNamespace(channel_id="C001"), SimpleNamespace(channel_id="C002")]

        with pytest.raises(ProviderUnavailable):
            tasks._deliver_all(routes, lambda _route: messages.Message(text="", blocks=[]))

        assert attempts == ["C001", "C002"]


class TestNotifyNewVulnerabilities:
    @pytest.fixture
    def scanned(self, component):
        from sbomify.apps.vulnerability_scanning.findings import sync_findings

        run = _scan(
            component,
            [
                _finding("CVE-LOW", "low", "leftpad"),
                _finding("CVE-CRIT", "critical", "openssl"),
                _finding("CVE-HIGH", "high", "requests"),
            ],
        )
        sync_findings(run, fresh=True)
        return run

    def test_lists_the_new_ones_worst_first(self, component, scanned, connected_slack, fake_slack):
        _route(connected_slack, Event.NEW_VULNERABILITIES, min_severity="low")

        tasks.notify_new_vulnerabilities(component.id, ["CVE-LOW", "CVE-CRIT", "CVE-HIGH"])

        [post] = fake_slack.posts
        assert post["text"] == "3 new vulnerabilities in payments-api: 1 critical, 1 high, 1 low."
        listing = json.dumps(post["blocks"])
        assert listing.index("CVE-CRIT") < listing.index("CVE-HIGH") < listing.index("CVE-LOW")
        assert "openssl@1.0.0" in listing
        assert post["blocks"][0]["type"] == "header"

    def test_each_route_applies_its_own_severity(self, component, scanned, connected_slack, fake_slack):
        _route(connected_slack, Event.NEW_VULNERABILITIES, min_severity="critical")

        tasks.notify_new_vulnerabilities(component.id, ["CVE-LOW", "CVE-CRIT", "CVE-HIGH"])

        [post] = fake_slack.posts
        assert post["text"] == "1 new vulnerability in payments-api: 1 critical."

    def test_nothing_above_the_bar_posts_nothing(self, component, scanned, connected_slack, fake_slack):
        _route(connected_slack, Event.NEW_VULNERABILITIES, min_severity="high")

        tasks.notify_new_vulnerabilities(component.id, ["CVE-LOW"])

        assert fake_slack.posts == []

    def test_a_vex_suppressed_vulnerability_is_not_news(self, component, scanned, connected_slack, fake_slack):
        from sbomify.apps.vulnerability_scanning.models import Finding

        Finding.objects.filter(record__advisory_id="CVE-CRIT").update(vex_suppressed=True)
        _route(connected_slack, Event.NEW_VULNERABILITIES, min_severity="critical")

        tasks.notify_new_vulnerabilities(component.id, ["CVE-CRIT"])

        assert fake_slack.posts == []


class TestDigest:
    def test_the_digest_carries_the_days_picture(self, component, connected_slack, fake_slack):
        from sbomify.apps.plugins.lifecycle import record_run

        record_run(_scan(component, [_finding("CVE-1", "high")]))
        _submission(component)
        route = _route(connected_slack, Event.DAILY_DIGEST)

        tasks.send_digest(route.id)

        [post] = fake_slack.posts
        assert post["text"].startswith("Vulnerability digest for ")
        body = json.dumps(post["blocks"])
        assert "New in the last 24 hours*\\n1" in body
        assert "VEX rulings waiting*\\n1" in body
        assert "Review VEX queue" in body

    def test_every_routed_workspace_is_queued(self, connected_slack, queued):
        route = _route(connected_slack, Event.DAILY_DIGEST)
        _route(connected_slack, Event.VEX_SUBMISSIONS)

        tasks.send_due_digests()

        assert queued == [("digest", route.id)]

    def test_a_revoked_connection_gets_no_digest(self, connected_slack, fake_slack):
        route = _route(connected_slack, Event.DAILY_DIGEST)
        connected_slack.status = Integration.Status.REVOKED
        connected_slack.save()

        tasks.send_digest(route.id)

        assert fake_slack.posts == []


class TestMessages:
    def test_a_component_name_cannot_ping_a_channel(self, sample_team_with_owner_member):
        component = Component.objects.create(name="<!here> & co", team=sample_team_with_owner_member.team)

        message = messages.new_vulnerabilities_message(
            component, [{"advisory_id": "CVE-1", "severity": "high", "package": "<@U1>", "version": ""}]
        )

        body = json.dumps(message.blocks[1:])
        assert "<!here>" not in body
        assert "<@U1>" not in body
        assert "&lt;!here&gt; &amp; co" in body

    def test_long_headers_are_cut_to_slacks_limit(self, sample_team_with_owner_member):
        component = Component.objects.create(name="x" * 250, team=sample_team_with_owner_member.team)

        message = messages.new_vulnerabilities_message(
            component, [{"advisory_id": "CVE-1", "severity": "high", "package": "", "version": ""}]
        )

        assert len(message.blocks[0]["text"]["text"]) <= messages.MAX_HEADER_CHARS

    def test_a_long_list_is_capped(self, sample_team_with_owner_member):
        component = Component.objects.create(name="big", team=sample_team_with_owner_member.team)
        rows = [{"advisory_id": f"CVE-{n}", "severity": "high", "package": "p", "version": ""} for n in range(25)]

        message = messages.new_vulnerabilities_message(component, rows)

        listing = message.blocks[3]["text"]["text"]
        assert listing.count("CVERecord") == messages.MAX_LISTED
        assert "15 more" in listing
