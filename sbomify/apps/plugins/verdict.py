"""The single implementation of "is this compliance-style summary passing?".

Two consumers encode this judgement, and they must not drift:

* ``public_assessment_utils._is_run_passing`` — decides whether a public
  component or product page renders the "All checks passed" badge.
* ``orchestrator._is_passing`` — decides whether a run satisfies another
  plugin's ``requires_one_of`` dependency gate.

They share this function; the one axis they differ on is explicit.

``warnings_block`` exists because the two consumers make different claims. A
public badge says every check passed, which is false the moment any check
warned — a document whose per-component elements are all exempt still passes
its document-level checks, and without this the reader is told "All checks
passed" about a run that graded nothing. The dependency gate asks a weaker
question — "did this plugin positively verify anything?" — and must tolerate
warnings: the verification plugin deliberately reports unverified *sources* as
warnings rather than failures so that one verified source (provenance, say)
satisfies the attestation requirement while another (a detached signature) is
merely absent. Its aggregating summary finding is the designed fail signal for
"no source verified"; a gate that blocked on warnings would fail attestation
for every provenance-verified unsigned SBOM.
"""

from __future__ import annotations

from typing import Any


def compliance_summary_passing(summary: dict[str, Any], *, warnings_block: bool) -> bool:
    """Judge a non-security run's summary counts.

    ``pass_count`` was added to summary payloads later than the other counts,
    so a run predating it carries no key at all. Key-absent (legacy schema) is
    distinguished from present-and-zero (a modern run with nothing positive to
    assert) so historical runs that satisfied the old contract keep passing.
    """
    if summary.get("fail_count", 0) != 0 or summary.get("error_count", 0) != 0:
        return False
    if warnings_block and summary.get("warning_count", 0):
        return False
    pass_count = summary.get("pass_count")
    if pass_count is None:
        return True
    return bool(pass_count)
