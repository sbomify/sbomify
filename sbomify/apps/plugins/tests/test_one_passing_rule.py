"""The dependency gate and the public badge judge a run one way.

Each kept its own copy of "is this run passing", and the copies drifted: a
skipped scan or one that flagged a malicious package satisfied a gate while the
public page refused it a badge, and a run with no result earned a badge the
gate refused.
"""

import pytest

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.orchestrator import PluginOrchestrator
from sbomify.apps.plugins.public_assessment_utils import _is_run_passing
from sbomify.apps.plugins.sdk.enums import RunStatus

COMPLETED = RunStatus.COMPLETED.value
NO_VULNERABILITIES = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "unknown": 0}
ONE_PASS = {"fail_count": 0, "error_count": 0, "pass_count": 1}


def test_the_gate_uses_the_public_rule() -> None:
    assert PluginOrchestrator._is_passing is _is_run_passing


JUDGES = [
    pytest.param(lambda run: PluginOrchestrator()._is_passing(run), id="dependency gate"),
    pytest.param(_is_run_passing, id="public badge"),
]

SHAPES = [
    pytest.param("compliance", COMPLETED, None, False, id="no result asserts nothing"),
    pytest.param("compliance", COMPLETED, {"summary": None}, False, id="summary that is not a dict"),
    pytest.param("compliance", RunStatus.PENDING.value, {"summary": ONE_PASS}, False, id="unfinished run"),
    pytest.param(
        "security", COMPLETED, {"summary": {"by_severity": {}}, "metadata": {"skipped": True}}, False, id="skipped scan"
    ),
    pytest.param("security", COMPLETED, {"summary": {"error_count": 1}}, False, id="scan that errored"),
    pytest.param(
        "security",
        COMPLETED,
        {"summary": {"by_severity": NO_VULNERABILITIES, "malicious_count": 1}},
        False,
        id="malicious package",
    ),
    pytest.param("security", COMPLETED, {"summary": {"by_severity": NO_VULNERABILITIES}}, True, id="clean scan"),
    pytest.param(
        "attestation",
        COMPLETED,
        {"summary": {**ONE_PASS, "warning_count": 3}},
        True,
        id="warnings beside a real pass",
    ),
    pytest.param(
        "compliance", COMPLETED, {"summary": {"fail_count": 0, "error_count": 0}}, True, id="legacy run with no pass count"
    ),
]


@pytest.mark.parametrize("judge", JUDGES)
@pytest.mark.parametrize(("category", "status", "result", "passing"), SHAPES)
def test_every_judge_gives_the_same_answer(judge, category, status, result, passing) -> None:
    run = AssessmentRun(plugin_name="any", category=category, status=status, result=result)

    assert judge(run) is passing
