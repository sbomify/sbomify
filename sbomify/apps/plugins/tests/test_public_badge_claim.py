"""The public badge must not claim more than the run did.

A run that passed one check and left six ungraded rendered as
``sbom-verification 1/7`` with the tooltip "All checks passed — 1/7 checks
passed", which contradicts itself in one sentence.

The badge is still shown. Measured across the corpus, 11 of the 25 non-security
runs that currently render a public pass carry warnings, and every one of them
is ``sbom-verification`` reporting an *absence* — no signature attached, no
provenance attached, no VCS metadata found. Those are optional things that were
not there, not failures, so withdrawing the badge would be the wrong reading of
a green run. Only the wording was wrong.
"""

from __future__ import annotations

import re

import pytest
from django.template.loader import render_to_string

from sbomify.apps.plugins.public_assessment_utils import (
    PassingAssessment,
    passing_assessments_to_dict,
)


def _render(**kwargs) -> str:
    """Render the badge the way the pages do.

    Through ``passing_assessments_to_dict`` deliberately. The template is handed
    that dict, never the dataclass, so rendering the dataclass directly would
    pass while the field it needs was missing from the conversion — which is
    exactly what happened.
    """
    assessment = PassingAssessment(
        plugin_name="sbom-verification",
        plugin_display_name="SBOM Verification",
        category="compliance",
        **kwargs,
    )
    return render_to_string(
        "plugins/components/_public_assessment_badge_inner.html.j2",
        {
            "assessment": passing_assessments_to_dict([assessment])[0],
            "badge_class": "badge-compliance",
            "badge_icon": "fa-check-circle",
            "status_phrase": "All checks passed",
        },
    )


def _title(html: str) -> str:
    return (re.search(r'title="([^"]*)"', html) or [None, ""])[1]


def test_a_clean_run_still_says_all_checks_passed() -> None:
    title = _title(_render(pass_count=7, total_findings=7, warning_count=0))

    assert "All checks passed" in title
    assert "7/7 checks passed" in title


def test_a_run_with_ungraded_checks_does_not_claim_all_passed() -> None:
    """The reported defect, in its own words."""
    title = _title(_render(pass_count=1, total_findings=7, warning_count=6))

    assert "All checks passed" not in title
    assert "No failed checks" in title


def test_the_ungraded_count_is_named_rather_than_hidden() -> None:
    """"1/7" alone reads as six failures. Saying what the six were is the
    difference between a badge that misleads and one that informs."""
    title = _title(_render(pass_count=1, total_findings=7, warning_count=6))

    assert "1/7 checks passed" in title
    assert "6 warned" in title


def test_a_run_with_no_count_information_is_unchanged() -> None:
    """Product-level aggregates drop the counts, so the phrase is all there is."""
    title = _title(_render())

    assert "All checks passed" in title
    assert "checks passed —" not in title


@pytest.mark.django_db
def test_the_two_passing_predicates_agree_about_a_legacy_run() -> None:
    """``pass_count`` was added later, so an older run carries no key.

    The orchestrator lets that run pass a dependency gate; the public helper
    read a default of 0 and refused it a badge. One judgement, two answers.
    """
    from sbomify.apps.plugins.models import AssessmentRun, RunStatus
    from sbomify.apps.plugins.orchestrator import PluginOrchestrator
    from sbomify.apps.plugins.public_assessment_utils import _is_run_passing

    legacy = AssessmentRun(
        plugin_name="ntia",
        category="compliance",
        status=RunStatus.COMPLETED.value,
        # No pass_count: the shape a run predating the field has.
        result={"summary": {"fail_count": 0, "error_count": 0}},
    )

    assert PluginOrchestrator()._is_passing(legacy) is True
    assert _is_run_passing(legacy) is True


@pytest.mark.django_db
def test_they_also_agree_that_zero_passes_is_not_passing() -> None:
    """A modern run that graded nothing has nothing to assert, and the
    reconciliation above must not have quietly re-opened that."""
    from sbomify.apps.plugins.models import AssessmentRun, RunStatus
    from sbomify.apps.plugins.orchestrator import PluginOrchestrator
    from sbomify.apps.plugins.public_assessment_utils import _is_run_passing

    graded_nothing = AssessmentRun(
        plugin_name="ntia",
        category="compliance",
        status=RunStatus.COMPLETED.value,
        result={"summary": {"fail_count": 0, "error_count": 0, "pass_count": 0, "warning_count": 4}},
    )

    assert PluginOrchestrator()._is_passing(graded_nothing) is False
    assert _is_run_passing(graded_nothing) is False


def test_the_conversion_carries_the_warning_count() -> None:
    """The dataclass and the dict are two places one field has to exist.

    The template reads the dict; a field added to only the dataclass renders as
    empty and the badge goes on claiming what it did before.
    """
    assessment = PassingAssessment(
        plugin_name="sbom-verification",
        plugin_display_name="SBOM Verification",
        category="compliance",
        pass_count=1,
        total_findings=7,
        warning_count=6,
    )

    assert passing_assessments_to_dict([assessment])[0]["warning_count"] == 6
