"""An artifact the scanner cannot read is not worth re-uploading every hour.

Dependency Track rejects a CycloneDX spec version it does not know, and the
plugin already classifies that as a skip rather than an error. What it did not
change is the sweep cadence: ``hourly_dt_scan_task`` runs with
``skip_hours=1``, so the same document was uploaded, rejected, and skipped
again on the next hour, indefinitely. From staging, four SBOMs over 48 hours:

    [DT] SBOM <id> uses a spec version this Dependency Track does not accept:
    Dependency Track error (400): The uploaded BOM is invalid: Unrecognized specVersion 1.7

Backing off rather than blocking, because the gap closes on its own — a later
Dependency Track release adds the spec version and the SBOM becomes scannable
with no change here.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.plugins.models import (
    AssessmentRun,
    RegisteredPlugin,
    RunStatus,
    TeamPluginSettings,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.sboms.models import SBOM


def _make_dt_plugin() -> None:
    RegisteredPlugin.objects.get_or_create(
        name="dependency-track",
        defaults={
            "display_name": "Dependency Track",
            "description": "DT",
            "category": AssessmentCategory.SECURITY.value,
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.dependency_track.DependencyTrackPlugin",
            "is_enabled": True,
        },
    )


@pytest.fixture
def scannable_sbom(sample_team_with_owner_member):
    """A paid team with one release-linked CycloneDX SBOM — the minimum the
    hourly sweep needs to consider an SBOM eligible."""
    team = sample_team_with_owner_member.team
    team.billing_plan = "business"
    team.save()

    _make_dt_plugin()
    settings, _ = TeamPluginSettings.objects.get_or_create(team=team)
    settings.enabled_plugins = ["dependency-track"]
    settings.save()

    product = Product.objects.create(name="p", team=team)
    component = Component.objects.create(name="c", team=team)
    product.components.add(component)
    sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", sbom_filename="s.json")
    ReleaseArtifact.objects.get_or_create(release=Release.get_or_create_latest_release(product), sbom=sbom)
    return sbom


def _run_at_age(sbom: SBOM, *, hours_ago: float, metadata: dict) -> AssessmentRun:
    """A completed DT run backdated past the hourly skip window.

    ``result_skipped`` is denormalised from ``result`` by the model's save, so
    creating the row the ordinary way is what keeps the fixture honest — the
    sweep narrows on that column before it reads the JSON.
    """
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        category=AssessmentCategory.SECURITY.value,
        status=RunStatus.COMPLETED.value,
        result={"summary": {"total_findings": 1}, "findings": [], "metadata": metadata},
    )
    # created_at is auto_now_add, so it has to be written back.
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(hours=hours_ago))
    return run


def _sweep(monkeypatch) -> list[dict]:
    """Run the hourly sweep, capturing what it would have enqueued."""
    from sbomify.apps.plugins.tasks import _is_paid_team, _run_scheduled_security_scans

    captured: list[dict] = []
    monkeypatch.setattr(
        "sbomify.apps.plugins.tasks.enqueue_assessment",
        lambda **kwargs: captured.append(kwargs),
    )
    _run_scheduled_security_scans(
        plugin_name="dependency-track",
        plan_filter=_is_paid_team,
        skip_hours=1,
        task_name="test_hourly_dt_scan",
        only_cyclonedx=True,
    )
    return captured


@pytest.mark.django_db
class TestTheHourlySweepBacksOff:
    def test_an_unreadable_artifact_is_not_retried_next_hour(self, scannable_sbom, monkeypatch) -> None:
        """The defect: two hours after the rejection the ordinary skip window
        has lapsed, and the sweep re-uploaded a document it already knows the
        server cannot parse."""
        _run_at_age(scannable_sbom, hours_ago=2, metadata={"skipped": True, "unsupported_input": True})

        assert _sweep(monkeypatch) == []

    def test_it_is_retried_once_the_backoff_lapses(self, scannable_sbom, monkeypatch) -> None:
        """Backed off, not blocked. A Dependency Track upgrade that adds the
        spec version has to be picked up without anyone intervening."""
        _run_at_age(scannable_sbom, hours_ago=25, metadata={"skipped": True, "unsupported_input": True})

        captured = _sweep(monkeypatch)

        assert len(captured) == 1
        assert captured[0]["sbom_id"] == str(scannable_sbom.id)


@pytest.mark.django_db
class TestEverythingElseKeepsItsCadence:
    """The backoff is keyed on one specific marker, and must not widen."""

    def test_an_ordinary_skip_still_rescans_hourly(self, scannable_sbom, monkeypatch) -> None:
        """A skip for an unmet precondition — no release association, say — can
        become scannable at any moment, so it keeps the hourly cadence."""
        _run_at_age(scannable_sbom, hours_ago=2, metadata={"skipped": True})

        assert len(_sweep(monkeypatch)) == 1

    def test_a_successful_scan_still_rescans_hourly(self, scannable_sbom, monkeypatch) -> None:
        """The whole point of the hourly sweep: new advisories land against
        unchanged SBOMs."""
        _run_at_age(scannable_sbom, hours_ago=2, metadata={"scanner": "dependency-track"})

        assert len(_sweep(monkeypatch)) == 1

    def test_an_errored_scan_still_rescans_hourly(self, scannable_sbom, monkeypatch) -> None:
        """A failed upload may well be transient."""
        _run_at_age(scannable_sbom, hours_ago=2, metadata={"error": True})

        assert len(_sweep(monkeypatch)) == 1

    def test_the_skip_window_still_applies_within_the_hour(self, scannable_sbom, monkeypatch) -> None:
        """The backoff extends the window; it must not shorten it for anyone."""
        _run_at_age(scannable_sbom, hours_ago=0.25, metadata={"scanner": "dependency-track"})

        assert _sweep(monkeypatch) == []


@pytest.mark.django_db
class TestTheMarkerTheBackoffReads:
    """The scheduler keys on metadata the plugin writes; if the two disagree
    the backoff silently never fires."""

    def test_the_spec_version_skip_carries_the_marker(self) -> None:
        import dataclasses

        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        result = DependencyTrackPlugin().create_skipped_result(
            finding_id="dependency-track:unsupported-spec-version",
            title="Spec Version Not Supported",
            description="x",
            unsupported_input=True,
        )
        as_dict = result.model_dump() if hasattr(result, "model_dump") else dataclasses.asdict(result)

        assert as_dict["metadata"]["unsupported_input"] is True
        assert as_dict["metadata"]["skipped"] is True

    def test_an_ordinary_skip_does_not_carry_it(self) -> None:
        import dataclasses

        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        result = DependencyTrackPlugin().create_skipped_result(
            finding_id="dependency-track:no-release",
            title="No Release",
            description="x",
        )
        as_dict = result.model_dump() if hasattr(result, "model_dump") else dataclasses.asdict(result)

        assert "unsupported_input" not in as_dict["metadata"]


@pytest.mark.django_db
class TestALaterScanClearsTheBackoff:
    """Keyed on the SBOM's latest run, not on any run in the window."""

    def test_a_successful_rescan_puts_it_back_in_the_sweep(self, scannable_sbom, monkeypatch) -> None:
        """The defect: an SBOM rejected at 09:00, made scannable by a server
        upgrade and scanned successfully at 10:00, stayed out of the hourly
        sweep until the original rejection aged out — a paid workspace missing
        a day of new advisories on an artifact the scanner can now read."""
        _run_at_age(scannable_sbom, hours_ago=6, metadata={"skipped": True, "unsupported_input": True})
        _run_at_age(scannable_sbom, hours_ago=5, metadata={"scanner": "dependency-track"})

        assert len(_sweep(monkeypatch)) == 1

    def test_a_later_rejection_still_backs_off(self, scannable_sbom, monkeypatch) -> None:
        """The order matters, not merely the presence of a success."""
        _run_at_age(scannable_sbom, hours_ago=5, metadata={"scanner": "dependency-track"})
        _run_at_age(scannable_sbom, hours_ago=4, metadata={"skipped": True, "unsupported_input": True})

        assert _sweep(monkeypatch) == []


@pytest.mark.django_db
class TestItDoesNotReadTheFatBlobForEveryRun:
    """``result`` runs to several MB and a JSON-path read de-TOASTs all of it,
    which is why ``result_skipped`` exists as a plain column. The sweep narrows
    on that column first so the hourly cron does not de-TOAST every completed
    run in the window."""

    def test_unskipped_runs_are_excluded_before_the_json_read(self, scannable_sbom, monkeypatch) -> None:
        from sbomify.apps.plugins.models import AssessmentRun

        _run_at_age(scannable_sbom, hours_ago=2, metadata={"scanner": "dependency-track"})

        # None rather than False: the model only records a bool when the result
        # actually carries a ``skipped`` key. The pre-filter matches on True, so
        # either falsy value is excluded — asserting "not True" is what the
        # query relies on, and asserting False would have been wrong.
        run = AssessmentRun.objects.get(sbom=scannable_sbom)
        assert run.result_skipped is not True, "a successful run must not be marked skipped"

        assert len(_sweep(monkeypatch)) == 1

    def test_the_marker_run_is_marked_skipped(self, scannable_sbom, monkeypatch) -> None:
        """If the denormalised column and the JSON ever disagree, the pre-filter
        silently drops the SBOM out of the backoff."""
        from sbomify.apps.plugins.models import AssessmentRun

        _run_at_age(scannable_sbom, hours_ago=2, metadata={"skipped": True, "unsupported_input": True})

        assert AssessmentRun.objects.get(sbom=scannable_sbom).result_skipped is True
        assert _sweep(monkeypatch) == []


@pytest.mark.django_db
class TestOnlyTheLatestRunsMarkerCounts:
    """The latest run has to mean the latest run — not "the latest run was
    skipped and something in the window carried the marker".

    Selecting the JSON read by SBOM id rather than by run id left that gap: an
    SBOM whose most recent run is a different kind of skip stayed backed off on
    the strength of an older unsupported-input run — the same "any run in the
    window" defect this whole function replaced, one level down.
    """

    def test_a_later_skip_of_another_kind_clears_the_backoff(self, scannable_sbom, monkeypatch) -> None:
        _run_at_age(scannable_sbom, hours_ago=6, metadata={"skipped": True, "unsupported_input": True})
        # A precondition skip — no product membership, say. Still skipped, so
        # still result_skipped=True, but it carries no marker.
        _run_at_age(scannable_sbom, hours_ago=5, metadata={"skipped": True})

        assert len(_sweep(monkeypatch)) == 1

    def test_the_latest_run_carrying_the_marker_still_backs_off(self, scannable_sbom, monkeypatch) -> None:
        """The half that must not regress."""
        _run_at_age(scannable_sbom, hours_ago=6, metadata={"skipped": True})
        _run_at_age(scannable_sbom, hours_ago=5, metadata={"skipped": True, "unsupported_input": True})

        assert _sweep(monkeypatch) == []
